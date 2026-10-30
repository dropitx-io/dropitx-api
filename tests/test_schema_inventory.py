"""Schema inventory: every table, column and RPC the app reaches through the DB shim
must exist in a database built from infra/init/*.sql.

Static side: an AST walk over app/ and core/ finds every `.table("t")` and
`.rpc("fn", {...})` call and follows its builder chain:
  - select("a, b, t!fk(c, d)")    -> main-table columns, the embed (join), nested columns
  - insert/upsert/update(payload)  -> payload keys
  - eq/neq/.../in_/is_/not_.<op>   -> filter column
  - order(col, foreign_table=t)    -> sort column
  - rpc("fn", {"p_a": ...})        -> function name and argument names
Builders kept in a variable (`q = client.table(...)`, later `q.eq(...)`) and
payloads built up in a variable (`row = {...}`, `row["k"] = ...`, `rows.append({...})`,
dict comprehensions over a literal key set) are followed within the enclosing
function. Any argument the walk cannot resolve to literal strings fails the test
with its file:line, so a new call shape is caught rather than skipped.

Live side: information_schema.columns (tables and views) and pg_proc on the
CI database, which local-ci and CI build fresh from infra/init.

Key types: an embed is resolved with the shim's own rule (core.db.embed_join) and
its two join columns must have the same type. A filter whose value expression names
a Firebase uid (`user_id`, `uid`, `user.id`, ...) must not compare a uuid column:
uids are TEXT, so `user_profiles.id` (UUID) is never the column to match them on.
"""

from __future__ import annotations

import ast
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from core.db import _parse_select_columns, embed_join

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = ("app", "core")

FILTERS = frozenset({
    "eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "in_", "is_", "contains", "overlaps",
})
PAYLOAD_METHODS = frozenset({"insert", "upsert", "update"})


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ColumnRef:
    table: str
    column: str | None  # None: the table itself (e.g. select("*"))
    where: str


@dataclass(frozen=True)
class JoinRef:
    table: str
    foreign: str
    hint: str | None
    where: str


@dataclass(frozen=True)
class RpcRef:
    function: str
    args: tuple[str, ...]
    where: str


@dataclass
class Inventory:
    columns: set[ColumnRef]
    rpcs: set[RpcRef]
    unresolved: list[str]
    joins: set[JoinRef] = field(default_factory=set)
    uid_filters: set[ColumnRef] = field(default_factory=set)  # column compared with a uid value


class Unresolved(Exception):
    pass


# ---------------------------------------------------------------------------
# Static extraction
# ---------------------------------------------------------------------------

# A filter value expression that carries a Firebase uid.
_UID_VALUE = re.compile(r"\b(user_ids?|uids?|invited_by|owner_id|shared_by)\b|\buser\.id\b")


def _select_refs(table: str, spec: str, where: str) -> tuple[set[ColumnRef], set[JoinRef]]:
    """Columns and embeds a PostgREST select string touches, parsed as core/db.py parses it."""
    main, embeds = _parse_select_columns(spec)
    refs = {ColumnRef(table, None, where)}
    refs |= {ColumnRef(table, c, where) for c in main if c != "*"}
    joins = set()
    for foreign, hint, inner in embeds:
        joins.add(JoinRef(table, foreign, hint, where))
        refs.add(ColumnRef(foreign, None, where))
        refs |= {ColumnRef(foreign, c, where) for c in inner if c != "*"}
    return refs, joins


class _Module:
    def __init__(self, path: Path, root: Path):
        self.path = path
        self.rel = path.relative_to(root).as_posix()
        self.tree = ast.parse(path.read_text(), filename=str(path))
        self.parent: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(self.tree):
            for child in ast.iter_child_nodes(node):
                self.parent[child] = node

    def where(self, node: ast.AST) -> str:
        return f"{self.rel}:{node.lineno}"

    # --- scopes -----------------------------------------------------------
    def scopes(self, node: ast.AST) -> list[ast.AST]:
        """Enclosing lambdas/functions innermost first, then the module."""
        out = []
        cur = self.parent.get(node)
        while cur is not None:
            if isinstance(cur, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append(cur)
            cur = self.parent.get(cur)
        out.append(self.tree)
        return out

    def _own_nodes(self, scope: ast.AST):
        """Nodes of `scope` excluding nested function bodies."""
        stack = list(ast.iter_child_nodes(scope))
        while stack:
            node = stack.pop()
            yield node
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                stack.extend(ast.iter_child_nodes(node))

    def bindings(self, name: str, at: ast.AST) -> list[tuple[str, ast.AST]]:
        """How `name` is built in its nearest binding scope.

        Returns (kind, node) pairs: ("value", expr) for assignments and lambda
        defaults, ("key", key_expr) for `name[key] = ...`, ("item", expr) for
        `name.append(expr)`, ("merge", expr) for `name.update(expr)`.
        """
        for scope in self.scopes(at):
            if isinstance(scope, ast.Lambda):
                args = scope.args
                if at in set(ast.walk(args)):
                    continue  # a default value is evaluated in the enclosing scope
                positional = args.args[len(args.args) - len(args.defaults):]
                for arg, default in zip(positional, args.defaults):
                    if arg.arg == name:
                        return [("value", default)]
                if any(a.arg == name for a in args.args + args.kwonlyargs):
                    return []
                continue
            found: list[tuple[str, ast.AST]] = []
            for node in self._own_nodes(scope):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == name:
                            found.append(("value", node.value))
                        elif (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
                              and target.value.id == name):
                            found.append(("key", target.slice))
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    if node.target.id == name and node.value is not None:
                        found.append(("value", node.value))
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and isinstance(node.func.value, ast.Name) and node.func.value.id == name
                      and node.func.attr in ("append", "update") and len(node.args) == 1):
                    found.append(("item" if node.func.attr == "append" else "merge", node.args[0]))
            if found:
                return found
        return []

    # --- value resolution -------------------------------------------------
    def strings(self, node: ast.AST) -> set[str]:
        """Every string `node` can evaluate to, or Unresolved."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {node.value}
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            out: set[str] = set()
            for elt in node.elts:
                out |= self.strings(elt)
            return out
        if isinstance(node, ast.Name):
            values = [n for kind, n in self.bindings(node.id, node) if kind == "value"]
            if not values or len(values) != len(self.bindings(node.id, node)):
                raise Unresolved(f"{self.where(node)}: cannot resolve {node.id!r} to strings")
            out = set()
            for value in values:
                out |= self.strings(value)
            return out
        # {"a": "x", "b": "y"}.get(key, "z")
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and isinstance(node.func.value, ast.Dict)):
            out = set()
            for value in node.func.value.values:
                out |= self.strings(value)
            for arg in node.args[1:]:
                out |= self.strings(arg)
            return out
        raise Unresolved(f"{self.where(node)}: cannot resolve {ast.unparse(node)!r} to strings")

    def keys(self, node: ast.AST) -> set[str]:
        """Every dict key a payload expression can carry, or Unresolved."""
        if isinstance(node, ast.Dict):
            out: set[str] = set()
            for key in node.keys:
                if key is None:
                    raise Unresolved(f"{self.where(node)}: `**` spread in payload")
                out |= self.strings(key)
            return out
        if isinstance(node, (ast.List, ast.Tuple)):
            out = set()
            for elt in node.elts:
                out |= self.keys(elt)
            return out
        if isinstance(node, ast.DictComp):
            return self._comprehension_keys(node)
        if isinstance(node, ast.Name):
            found = self.bindings(node.id, node)
            if not found:
                raise Unresolved(f"{self.where(node)}: cannot find how {node.id!r} is built")
            out = set()
            for kind, value in found:
                out |= self.strings(value) if kind == "key" else self.keys(value)
            return out
        raise Unresolved(f"{self.where(node)}: cannot resolve payload {ast.unparse(node)!r}")

    def _comprehension_keys(self, node: ast.DictComp) -> set[str]:
        if not isinstance(node.key, ast.Name) or len(node.generators) != 1:
            raise Unresolved(f"{self.where(node)}: unsupported dict comprehension")
        gen = node.generators[0]
        var = node.key.id
        target = gen.target
        loop_vars = [target.id] if isinstance(target, ast.Name) else [
            e.id for e in getattr(target, "elts", []) if isinstance(e, ast.Name)
        ]
        if var not in loop_vars:
            raise Unresolved(f"{self.where(node)}: dict comprehension key is not a loop variable")
        if isinstance(target, ast.Name):
            try:
                return self.strings(gen.iter)
            except Unresolved:
                pass
        # {k: v for k, v in body.items() if k in allowed}
        for cond in gen.ifs:
            if (isinstance(cond, ast.Compare) and isinstance(cond.left, ast.Name) and cond.left.id == var
                    and len(cond.ops) == 1 and isinstance(cond.ops[0], ast.In)):
                return self.strings(cond.comparators[0])
        raise Unresolved(f"{self.where(node)}: dict comprehension keys are not a literal set")

    # --- chains -----------------------------------------------------------
    def _chain_up(self, start: ast.AST) -> tuple[list[tuple[str, ast.Call]], ast.AST]:
        """Method calls applied after `start`, and the outermost expression of the chain."""
        calls: list[tuple[str, ast.Call]] = []
        node = start
        while True:
            attr = self.parent.get(node)
            if not (isinstance(attr, ast.Attribute) and attr.value is node):
                return calls, node
            if attr.attr == "not_":
                node = attr
                continue
            call = self.parent.get(attr)
            if not (isinstance(call, ast.Call) and call.func is attr):
                return calls, node
            calls.append((attr.attr, call))
            node = call

    def _builder_assignment(self, top: ast.AST) -> str | None:
        """Variable name a builder chain is assigned to, if any."""
        node = top
        parent = self.parent.get(node)
        if isinstance(parent, ast.Assign) and len(parent.targets) == 1 and isinstance(parent.targets[0], ast.Name):
            return parent.targets[0].id
        return None

    def inventory(self, inv: Inventory) -> None:
        builder_vars: dict[tuple[ast.AST, str], str] = {}  # (scope, var) -> table
        pending: list[tuple[str, ast.AST]] = []  # (table, chain start)
        traced: set[ast.Call] = set()

        for node in ast.walk(self.tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in ("table", "rpc") or not node.args:
                continue
            try:
                (name,) = self.strings(node.args[0])
                if node.func.attr == "rpc":
                    args = tuple(sorted(self.keys(node.args[1]))) if len(node.args) > 1 else ()
                    inv.rpcs.add(RpcRef(name, args, self.where(node)))
                    traced |= {call for _, call in self._chain_up(node)[0]}
                else:
                    pending.append((name, node))
            except (Unresolved, ValueError) as exc:
                inv.unresolved.append(str(exc) or f"{self.where(node)}: ambiguous target")

        while pending:
            table, start = pending.pop()
            calls, top = self._chain_up(start)
            traced |= {call for _, call in calls}
            for method, call in calls:
                try:
                    inv.columns |= self._call_refs(table, method, call, inv)
                except Unresolved as exc:
                    inv.unresolved.append(str(exc))
            var = self._builder_assignment(top)
            if var is None:
                continue
            scope = self.scopes(top)[0]
            if (scope, var) in builder_vars:
                continue
            builder_vars[(scope, var)] = table
            for use in self._own_nodes(scope):
                if isinstance(use, ast.Name) and use.id == var and isinstance(use.ctx, ast.Load):
                    pending.append((table, use))
            # lambdas inside the scope see the variable too
            for lam in ast.walk(scope):
                if isinstance(lam, ast.Lambda) and lam is not scope:
                    for use in ast.walk(lam.body):
                        if isinstance(use, ast.Name) and use.id == var and isinstance(use.ctx, ast.Load):
                            pending.append((table, use))

        # A builder that reaches .execute() from anywhere else (a helper's parameter,
        # an attribute) was never traced: report it rather than skip it.
        for node in ast.walk(self.tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "execute" and node not in traced):
                inv.unresolved.append(f"{self.where(node)}: .execute() on a builder of unknown origin")

    def _call_refs(self, table: str, method: str, call: ast.Call, inv: Inventory) -> set[ColumnRef]:
        where = self.where(call)
        if method == "select":
            spec = call.args[0] if call.args else ast.Constant("*")
            refs: set[ColumnRef] = set()
            for s in self.strings(spec):
                cols, joins = _select_refs(table, s, where)
                refs |= cols
                inv.joins |= joins
            return refs
        if method in PAYLOAD_METHODS:
            refs = {ColumnRef(table, None, where)}
            refs |= {ColumnRef(table, k, where) for k in self.keys(call.args[0])}
            for kw in call.keywords:
                if kw.arg == "on_conflict":
                    for s in self.strings(kw.value):
                        refs |= {ColumnRef(table, c.strip(), where) for c in s.split(",")}
            return refs
        if method in FILTERS:
            refs = {ColumnRef(table, c, where) for c in self.strings(call.args[0])}
            if len(call.args) > 1 and _UID_VALUE.search(ast.unparse(call.args[1])):
                inv.uid_filters |= refs
            return refs
        if method == "order":
            target = table
            for kw in call.keywords:
                if kw.arg == "foreign_table":
                    (target,) = self.strings(kw.value)
            return {ColumnRef(target, c, where) for c in self.strings(call.args[0])}
        if method == "delete":
            return {ColumnRef(table, None, where)}
        return set()


def build_inventory(paths, root: Path = ROOT) -> Inventory:
    inv = Inventory(set(), set(), [])
    for path in paths:
        _Module(path, root).inventory(inv)
    return inv


def _source_files():
    for d in SOURCE_DIRS:
        yield from sorted((ROOT / d).rglob("*.py"))


# ---------------------------------------------------------------------------
# Live catalog
# ---------------------------------------------------------------------------

def _split_table(name: str) -> tuple[str, str]:
    return tuple(name.split(".", 1)) if "." in name else ("public", name)


def _catalog():
    from core.db import _get_pool, _run_async

    async def read():
        pool = await _get_pool()
        async with pool.acquire() as conn:
            cols = await conn.fetch(
                "SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema IN ('public', 'auth')"
            )
            procs = await conn.fetch(
                """
                SELECT p.proname, p.pronargs, p.pronargdefaults,
                       COALESCE(p.proargnames, '{}') AS names,
                       COALESCE(p.proargmodes::text[], '{}') AS modes
                FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public'
                """
            )
            return cols, procs

    cols, procs = _run_async(read())
    tables: dict[tuple[str, str], dict[str, str]] = {}  # (schema, table) -> column -> data_type
    for r in cols:
        tables.setdefault((r["table_schema"], r["table_name"]), {})[r["column_name"]] = r["data_type"]
    functions: dict[str, list[tuple[list[str], int]]] = {}
    for r in procs:
        names, modes = list(r["names"]), list(r["modes"])
        inputs = [n for i, n in enumerate(names) if not modes or modes[i] in ("i", "b", "v")]
        required = r["pronargs"] - r["pronargdefaults"]
        functions.setdefault(r["proname"], []).append((inputs, required))
    return tables, functions


def find_mismatches(inv: Inventory, tables, functions) -> list[str]:
    missing: dict[str, set[str]] = {}
    for ref in inv.columns:
        cols = tables.get(_split_table(ref.table))
        if cols is None:
            key = f"table {ref.table}"
        elif ref.column is not None and ref.column not in cols:
            key = f"column {ref.table}.{ref.column}"
        else:
            continue
        missing.setdefault(key, set()).add(ref.where)

    for ref in inv.joins:
        base, foreign = tables.get(_split_table(ref.table)), tables.get(_split_table(ref.foreign))
        if base is None or foreign is None:
            continue  # reported as a missing table above
        try:
            _, base_col, foreign_col = embed_join(ref.table, ref.foreign, ref.hint, base, foreign)
        except ValueError as exc:
            key = f"embed {ref.foreign} in {ref.table}: {exc}"
        else:
            types = (base.get(base_col), foreign.get(foreign_col))
            if types[0] is not None and types[0] == types[1]:
                continue
            key = (f"embed {ref.foreign} in {ref.table} joins {ref.table}.{base_col} ({types[0]}) "
                   f"= {ref.foreign}.{foreign_col} ({types[1]})")
        missing.setdefault(key, set()).add(ref.where)

    for ref in inv.uid_filters:
        cols = tables.get(_split_table(ref.table)) or {}
        if cols.get(ref.column) == "uuid":
            key = f"uid value compared with uuid column {ref.table}.{ref.column}"
            missing.setdefault(key, set()).add(ref.where)

    for ref in inv.rpcs:
        overloads = functions.get(ref.function)
        if overloads is None:
            key = f"function {ref.function}"
        elif not any(
            set(ref.args) <= set(inputs) and set(inputs[:required]) <= set(ref.args)
            for inputs, required in overloads
        ):
            sigs = " | ".join(f"({', '.join(i)})" for i, _ in overloads)
            key = f"function {ref.function}({', '.join(ref.args)}) — infra/init has {sigs}"
        else:
            continue
        missing.setdefault(key, set()).add(ref.where)

    return [f"{k}  <- {', '.join(sorted(v))}" for k, v in sorted(missing.items())]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_every_shim_call_site_resolves_statically():
    inv = build_inventory(_source_files())
    assert not inv.unresolved, "Shim call shapes the inventory cannot read:\n" + "\n".join(inv.unresolved)


def test_code_references_exist_in_infra_init_schema():
    inv = build_inventory(_source_files())
    tables, functions = _catalog()
    mismatches = find_mismatches(inv, tables, functions)
    assert not mismatches, "Referenced by app code but missing from, or mistyped against, infra/init:\n" + "\n".join(mismatches)


_SAMPLE = textwrap.dedent('''
    LIST_COLS = "id, slug"

    def handler(client, body, sort, flag):
        q = client.table("things").select(LIST_COLS + "", count="exact") if False else None
        query = client.table("things").select("*, owners!owner_id(name)").not_.is_("gone_at", "null")
        if flag:
            query = query.eq("kind", 1)
        lambda: query.order({"new": "created_at", "big": "size"}.get(sort, "created_at")).execute()

        row: dict = {"a": 1}
        row["b"] = 2
        lambda rd=row: client.table("things").insert(rd).execute()

        rows = []
        rows.append({"c": 3})
        client.table("parts").upsert(rows, on_conflict="c,d").execute()

        allowed = {"e", "f"}
        client.table("things").update({k: v for k, v in body.items() if k in allowed}).eq("id", 1).execute()
        client.table("things").update({k: body[k] for k in ("g",) if k in body}).execute()
        client.rpc("do_it", {"p_x": 1, "p_y": 2}).execute()

    def run(builder):
        return builder.execute()
''')


def test_extractor_follows_variables_lambdas_and_comprehensions(tmp_path):
    path = tmp_path / "sample.py"
    path.write_text(_SAMPLE)
    inv = build_inventory([path], root=tmp_path)

    got = {(r.table, r.column) for r in inv.columns}
    assert got == {
        ("things", None), ("owners", None), ("owners", "name"),
        ("things", "gone_at"), ("things", "kind"), ("things", "created_at"), ("things", "size"),
        ("things", "a"), ("things", "b"), ("parts", None), ("parts", "c"), ("parts", "d"),
        ("things", "e"), ("things", "f"), ("things", "g"), ("things", "id"),
    }
    assert {(j.table, j.foreign, j.hint) for j in inv.joins} == {("things", "owners", "owner_id")}
    assert {(r.function, r.args) for r in inv.rpcs} == {("do_it", ("p_x", "p_y"))}
    assert sorted(inv.unresolved) == [
        "sample.py:25: .execute() on a builder of unknown origin",
        "sample.py:5: cannot resolve \"LIST_COLS + ''\" to strings",
    ]


_KEYS_SAMPLE = textwrap.dedent('''
    def handler(client, share, user, user_ids):
        client.table("members").select("*, user_profiles!user_id(name), teams(name)").execute()
        client.table("members").select("*, groups!user_id(name)").execute()
        client.table("members").select("*, badges(name)").execute()
        client.table("user_profiles").select("name").in_("id", user_ids).execute()
        client.table("user_profiles").select("name").not_.eq("id", user.id).execute()
        client.table("user_profiles").select("name").eq("user_id", share["user_id"]).execute()
        client.table("teams").select("name").eq("id", share["team_id"]).execute()
''')

_KEYS_CATALOG = {
    ("public", "members"): {"id": "uuid", "user_id": "text", "team_id": "uuid"},
    ("public", "user_profiles"): {"id": "uuid", "user_id": "text", "name": "text"},
    ("public", "teams"): {"id": "uuid", "name": "text"},
    ("public", "groups"): {"id": "uuid", "name": "text"},
    ("public", "badges"): {"id": "uuid", "name": "text"},
}


def test_joins_and_uid_filters_must_compare_same_typed_keys(tmp_path):
    path = tmp_path / "keys.py"
    path.write_text(_KEYS_SAMPLE)
    inv = build_inventory([path], root=tmp_path)

    assert find_mismatches(inv, _KEYS_CATALOG, {}) == [
        "embed badges in members: select spec: no column relates members to badges  <- keys.py:5",
        "embed groups in members joins members.user_id (text) = groups.id (uuid)  <- keys.py:4",
        "uid value compared with uuid column user_profiles.id  <- keys.py:6, keys.py:7",
    ]
