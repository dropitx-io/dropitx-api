"""Language detection for code syntax highlighting.

Maps file extensions to Shiki language identifiers.
Provides auto-detection from filename and content heuristics.
"""

from __future__ import annotations

# Extension -> Shiki language ID mapping (100+ languages)
EXTENSION_TO_LANGUAGE: dict[str, str] = {
    # JavaScript / TypeScript
    ".js": "javascript",
    ".jsx": "jsx",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".mts": "typescript",
    ".cts": "typescript",
    # Web
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    ".vue": "vue",
    ".svelte": "svelte",
    ".astro": "astro",
    # Python
    ".py": "python",
    ".pyw": "python",
    ".pyi": "python",
    # Rust
    ".rs": "rust",
    # Go
    ".go": "go",
    # Java / Kotlin / Scala
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".sc": "scala",
    # C / C++ / C#
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".cs": "csharp",
    ".csx": "csharp",
    # Ruby
    ".rb": "ruby",
    ".erb": "erb",
    # PHP
    ".php": "php",
    # Swift / Objective-C
    ".swift": "swift",
    ".m": "objective-c",
    ".mm": "objective-c",
    # Shell
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "zsh",
    ".fish": "fish",
    # Data / Config
    ".json": "json",
    ".jsonc": "jsonc",
    ".json5": "json5",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".env": "dotenv",
    # Markup
    ".md": "markdown",
    ".mdx": "mdx",
    ".rst": "rst",
    ".tex": "latex",
    ".bib": "bibtex",
    # SQL
    ".sql": "sql",
    ".psql": "sql",
    ".mysql": "sql",
    ".pgsql": "sql",
    # Haskell / OCaml / F#
    ".hs": "haskell",
    ".lhs": "haskell",
    ".ml": "ocaml",
    ".mli": "ocaml",
    ".fs": "fsharp",
    ".fsi": "fsharp",
    ".fsx": "fsharp",
    # Lisp / Clojure
    ".clj": "clojure",
    ".cljs": "clojure",
    ".cljc": "clojure",
    ".el": "emacs-lisp",
    ".lisp": "lisp",
    ".lsp": "lisp",
    ".rkt": "racket",
    ".scm": "scheme",
    # Erlang / Elixir
    ".erl": "erlang",
    ".hrl": "erlang",
    ".ex": "elixir",
    ".exs": "elixir",
    # Julia / R / MATLAB
    ".jl": "julia",
    ".r": "r",
    ".R": "r",
    ".m": "matlab",  # conflicts with objc; objc wins via priority
    # Dart / Flutter
    ".dart": "dart",
    # Zig / Nim / V
    ".zig": "zig",
    ".nim": "nim",
    ".nimble": "nim",
    ".v": "v",
    ".vsh": "v",
    # Lua
    ".lua": "lua",
    # Perl
    ".pl": "perl",
    ".pm": "perl",
    ".t": "perl",
    # Assembly
    ".asm": "asm",
    ".s": "asm",
    ".nasm": "nasm",
    # Docker / DevOps
    ".dockerfile": "dockerfile",
    ".tf": "hcl",
    ".hcl": "hcl",
    ".proto": "protobuf",
    # Misc
    ".graphql": "graphql",
    ".gql": "graphql",
    ".prisma": "prisma",
    ".sol": "solidity",
    ".cairo": "cairo",
    ".wgsl": "wgsl",
    ".glsl": "glsl",
    ".hlsl": "hlsl",
    ".wgsl": "wgsl",
    ".diff": "diff",
    ".patch": "diff",
    ".csv": "csv",
    ".tsv": "csv",
    ".nginx": "nginx",
    ".apache": "apache",
    ".makefile": "makefile",
    ".cmake": "cmake",
    ".gradle": "kotlin",
    ".groovy": "groovy",
    ".gvy": "groovy",
    ".feature": "gherkin",
    ".robot": "robotframework",
    ".vhd": "vhdl",
    ".vhdl": "vhdl",
    ".sv": "systemverilog",
    ".svh": "systemverilog",
    ".vhd": "vhdl",
    ".tcl": "tcl",
    ".tk": "tcl",
    ".awk": "awk",
    ".sed": "sed",
}

# Filename -> language mapping (special files without extensions)
FILENAME_TO_LANGUAGE: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "dockerfile": "dockerfile",
    "Containerfile": "dockerfile",
    "Makefile": "makefile",
    "makefile": "makefile",
    "GNUmakefile": "makefile",
    "CMakeLists.txt": "cmake",
    "Vagrantfile": "ruby",
    "Gemfile": "ruby",
    "Rakefile": "ruby",
    "Brewfile": "ruby",
    ".bashrc": "bash",
    ".bash_profile": "bash",
    ".zshrc": "zsh",
    ".zshenv": "zsh",
    ".vimrc": "vim",
    "vimrc": "vim",
    ".nanorc": "nanorc",
    ".editorconfig": "ini",
    ".gitignore": "gitignore",
    ".gitattributes": "gitignore",
    ".dockerignore": "dockerfile",
    ".eslintignore": "gitignore",
    ".prettierignore": "gitignore",
    "tsconfig.json": "jsonc",
    "jsconfig.json": "jsonc",
    "settings.json": "jsonc",
    "launch.json": "jsonc",
    "tasks.json": "jsonc",
    ".babelrc": "json",
    ".eslintrc": "json",
    ".prettierrc": "json",
    "Cargo.toml": "toml",
    "pyproject.toml": "toml",
    "Pipfile": "toml",
    "go.mod": "go",
    "go.sum": "go",
    "requirements.txt": "text",
    "Pipfile.lock": "json",
    "Cargo.lock": "toml",
    "package.json": "json",
    "package-lock.json": "json",
    "yarn.lock": "yaml",
    "pnpm-lock.yaml": "yaml",
    ".env.example": "dotenv",
    ".env.local": "dotenv",
    ".env.production": "dotenv",
}

# MIME type -> language mapping
MIME_TO_LANGUAGE: dict[str, str] = {
    "text/javascript": "javascript",
    "application/javascript": "javascript",
    "text/typescript": "typescript",
    "application/typescript": "typescript",
    "text/x-python": "python",
    "text/x-java": "java",
    "text/x-csrc": "c",
    "text/x-c++src": "cpp",
    "text/x-csharp": "csharp",
    "text/x-ruby": "ruby",
    "text/x-php": "php",
    "text/x-go": "go",
    "text/x-rust": "rust",
    "text/x-shellscript": "bash",
    "text/x-sql": "sql",
    "text/x-haskell": "haskell",
    "text/x-ocaml": "ocaml",
    "text/x-lua": "lua",
    "text/x-perl": "perl",
    "text/x-rsrc": "r",
    "text/x-scala": "scala",
    "text/x-kotlin": "kotlin",
    "text/x-swift": "swift",
    "text/x-dart": "dart",
    "text/x-elixir": "elixir",
    "text/x-erlang": "erlang",
    "text/x-julia": "julia",
    "text/x-zig": "zig",
    "text/x-nim": "nim",
    "text/x-fsharp": "fsharp",
    "text/x-clojure": "clojure",
    "text/x-scheme": "scheme",
    "text/x-lisp": "lisp",
    "text/x-objcsrc": "objective-c",
    "text/x-cmake": "cmake",
    "text/x-dockerfile": "dockerfile",
    "text/x-protobuf": "protobuf",
    "text/x-graphql": "graphql",
    "text/x-toml": "toml",
    "text/x-yaml": "yaml",
    "application/json": "json",
    "application/xml": "xml",
    "text/xml": "xml",
    "text/html": "html",
    "text/css": "css",
    "text/x-scss": "scss",
    "text/x-sass": "sass",
    "text/x-less": "less",
    "text/markdown": "markdown",
    "text/x-latex": "latex",
    "text/x-diff": "diff",
}

# Content patterns for heuristic detection
_CONTENT_PATTERNS: list[tuple[str, str]] = [
    # Shebang lines
    (r"^#!\s*/usr/bin/env\s+python", "python"),
    (r"^#!\s*/usr/bin/python", "python"),
    (r"^#!\s*/usr/bin/env\s+node", "javascript"),
    (r"^#!\s*/usr/bin/node", "javascript"),
    (r"^#!\s*/usr/bin/env\s+bash", "bash"),
    (r"^#!\s*/bin/bash", "bash"),
    (r"^#!\s*/bin/sh", "bash"),
    (r"^#!\s*/usr/bin/env\s+ruby", "ruby"),
    (r"^#!\s*/usr/bin/ruby", "ruby"),
    (r"^#!\s*/usr/bin/env\s+perl", "perl"),
    (r"^#!\s*/usr/bin/perl", "perl"),
    (r"^#!\s*/usr/bin/env\s+lua", "lua"),
    (r"^#!\s*/usr/bin/lua", "lua"),
    # Common patterns
    (r"^package\s+main\b", "go"),
    (r"^fn\s+main\s*\(\s*\)", "rust"),
    (r"^use\s+std::", "rust"),
    (r"^import\s+React", "typescript"),
    (r"^from\s+React", "typescript"),
    (r"^import\s+django", "python"),
    (r"^from\s+flask", "python"),
    (r"^from\s+fastapi", "python"),
    (r"^import\s+pandas", "python"),
    (r"^import\s+numpy", "python"),
    (r"^class\s+\w+\(unittest\.TestCase\)", "python"),
    (r"^def\s+test_", "python"),
    (r"^<?php", "php"),
    (r"^#include\s*<", "c"),
    (r"^using\s+namespace\s+std", "cpp"),
    (r"^template\s*<", "cpp"),
    (r"^namespace\s+\w+", "csharp"),
    (r"^using\s+System", "csharp"),
    (r"^public\s+class\s+", "java"),
    (r"^import\s+java\.", "java"),
    (r"^fun\s+main", "kotlin"),
    (r"^func\s+main", "go"),
    (r"^SELECT\s+", "sql"),
    (r"^CREATE\s+TABLE", "sql"),
    (r"^INSERT\s+INTO", "sql"),
    (r"^FROM\s+\w+\s+SELECT", "sql"),
    (r"^---", "yaml"),
    (r"^apiVersion:", "yaml"),
    (r"^kind:\s+", "yaml"),
    (r"^\[package\]", "toml"),
    (r"^\[dependencies\]", "toml"),
    (r"^<!DOCTYPE\s+html", "html"),
    (r"^<html", "html"),
    (r"^<\?xml", "xml"),
    (r"^\{", "json"),
    (r"^<svg", "svg"),
    (r"^<\?xml", "xml"),
]


def detect_language_from_extension(filename: str | None) -> str | None:
    """Detect language from file extension."""
    if not filename:
        return None

    # Check special filenames first
    basename = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if basename in FILENAME_TO_LANGUAGE:
        return FILENAME_TO_LANGUAGE[basename]

    # Check extension
    dot_idx = basename.rfind(".")
    if dot_idx >= 0:
        ext = basename[dot_idx:].lower()
        return EXTENSION_TO_LANGUAGE.get(ext)

    return None


def detect_language_from_mime(mime_type: str | None) -> str | None:
    """Detect language from MIME type."""
    if not mime_type:
        return None

    # Normalize
    mime = mime_type.lower().split(";")[0].strip()
    return MIME_TO_LANGUAGE.get(mime)


def detect_language_from_content(content: str) -> str | None:
    """Detect language from content heuristics (first few lines)."""
    import re

    if not content:
        return None

    # Only check first 10 lines
    lines = content.split("\n", 10)
    sample = "\n".join(lines)

    for pattern, lang in _CONTENT_PATTERNS:
        if re.search(pattern, sample, re.MULTILINE | re.IGNORECASE):
            return lang

    return None


def detect_language(
    filename: str | None = None,
    mime_type: str | None = None,
    content: str | None = None,
    explicit_language: str | None = None,
) -> str | None:
    """Detect language using multiple strategies in priority order.

    Priority:
    1. Explicit language parameter (user-specified)
    2. Filename extension
    3. MIME type
    4. Content heuristics
    """
    # 1. Explicit
    if explicit_language:
        lang = explicit_language.lower().strip()
        # Validate it's a known language
        all_languages = get_all_languages()
        lang_ids = {l["id"] for l in all_languages}
        if lang in lang_ids:
            return lang
        # Try common aliases
        aliases = {
            "js": "javascript",
            "ts": "typescript",
            "py": "python",
            "rb": "ruby",
            "rs": "rust",
            "yml": "yaml",
            "sh": "bash",
            "shell": "bash",
            "zsh": "zsh",
            "docker": "dockerfile",
            "docker-compose": "yaml",
            "tf": "hcl",
            "terraform": "hcl",
            "c#": "csharp",
            "c++": "cpp",
            "f#": "fsharp",
            "objc": "objective-c",
            "obj-c": "objective-c",
            "tex": "latex",
            "md": "markdown",
            "gql": "graphql",
            "pg": "sql",
            "postgres": "sql",
            "postgresql": "sql",
            "mysql": "sql",
            "sqlite": "sql",
            "rs": "rust",
            "kt": "kotlin",
            "jl": "julia",
            "ex": "elixir",
            "erl": "erlang",
            "clj": "clojure",
            "ml": "ocaml",
            "hs": "haskell",
            "nim": "nim",
            "zig": "zig",
            "v": "v",
            "lua": "lua",
            "pl": "perl",
            "r": "r",
            "R": "r",
            "asm": "asm",
            "nasm": "nasm",
            "vhdl": "vhdl",
            "verilog": "systemverilog",
            "sv": "systemverilog",
            "proto": "protobuf",
            "protobuf": "protobuf",
            "nginx": "nginx",
            "apache": "apache",
            "make": "makefile",
            "cmake": "cmake",
            "groovy": "groovy",
            "gradle": "kotlin",
            "gherkin": "gherkin",
            "robot": "robotframework",
            "tcl": "tcl",
            "awk": "awk",
            "sed": "sed",
            "csv": "csv",
            "tsv": "csv",
            "diff": "diff",
            "patch": "diff",
            "gitignore": "gitignore",
            "dotenv": "dotenv",
            "env": "dotenv",
            "vim": "vim",
            "nanorc": "nanorc",
            "wgsl": "wgsl",
            "glsl": "glsl",
            "hlsl": "hlsl",
            "cairo": "cairo",
            "solidity": "solidity",
            "sol": "solidity",
            "prisma": "prisma",
            "sass": "sass",
            "scss": "scss",
            "less": "less",
            "vue": "vue",
            "svelte": "svelte",
            "astro": "astro",
            "mdx": "mdx",
            "rst": "rst",
            "bibtex": "bibtex",
            "latex": "latex",
            "jsonc": "jsonc",
            "json5": "json5",
            "erb": "erb",
            "emacs-lisp": "emacs-lisp",
            "elisp": "emacs-lisp",
            "scheme": "scheme",
            "racket": "racket",
        }
        if lang in aliases:
            return aliases[lang]
        return None

    # 2. Filename
    lang = detect_language_from_extension(filename)
    if lang:
        return lang

    # 3. MIME type
    lang = detect_language_from_mime(mime_type)
    if lang:
        return lang

    # 4. Content
    if content:
        lang = detect_language_from_content(content)
        if lang:
            return lang

    return None


def get_all_languages() -> list[dict]:
    """Get list of all supported languages with metadata.

    Returns list of dicts with: id, name, extensions, aliases
    """
    # Shiki language metadata (subset of 100+ most popular)
    return [
        {"id": "abap", "name": "ABAP", "extensions": [".abap"]},
        {"id": "actionscript-3", "name": "ActionScript 3", "extensions": [".as"]},
        {"id": "ada", "name": "Ada", "extensions": [".ada", ".adb", ".ads"]},
        {"id": "apache", "name": "Apache", "extensions": [".apache"]},
        {"id": "apex", "name": "Apex", "extensions": [".cls", ".trigger"]},
        {"id": "apl", "name": "APL", "extensions": [".apl"]},
        {"id": "applescript", "name": "AppleScript", "extensions": [".applescript"]},
        {"id": "asm", "name": "Assembly", "extensions": [".asm", ".s"]},
        {"id": "astro", "name": "Astro", "extensions": [".astro"]},
        {"id": "awk", "name": "AWK", "extensions": [".awk"]},
        {"id": "bash", "name": "Bash", "extensions": [".sh", ".bash", ".zsh"]},
        {"id": "batch", "name": "Batch", "extensions": [".bat", ".cmd"]},
        {"id": "berry", "name": "Berry", "extensions": [".be"]},
        {"id": "bibtex", "name": "BibTeX", "extensions": [".bib"]},
        {"id": "bicep", "name": "Bicep", "extensions": [".bicep"]},
        {"id": "c", "name": "C", "extensions": [".c", ".h"]},
        {"id": "cairo", "name": "Cairo", "extensions": [".cairo"]},
        {"id": "clojure", "name": "Clojure", "extensions": [".clj", ".cljs"]},
        {"id": "cmake", "name": "CMake", "extensions": [".cmake"]},
        {"id": "cobol", "name": "COBOL", "extensions": [".cob", ".cbl"]},
        {"id": "codeql", "name": "CodeQL", "extensions": [".ql"]},
        {"id": "coffeescript", "name": "CoffeeScript", "extensions": [".coffee"]},
        {"id": "cpp", "name": "C++", "extensions": [".cpp", ".cxx", ".cc", ".hpp"]},
        {"id": "crystal", "name": "Crystal", "extensions": [".cr"]},
        {"id": "csharp", "name": "C#", "extensions": [".cs"]},
        {"id": "css", "name": "CSS", "extensions": [".css"]},
        {"id": "csv", "name": "CSV", "extensions": [".csv", ".tsv"]},
        {"id": "cuda", "name": "CUDA", "extensions": [".cu", ".cuh"]},
        {"id": "d", "name": "D", "extensions": [".d"]},
        {"id": "dart", "name": "Dart", "extensions": [".dart"]},
        {"id": "diff", "name": "Diff", "extensions": [".diff", ".patch"]},
        {"id": "dockerfile", "name": "Dockerfile", "extensions": [".dockerfile"]},
        {"id": "dotenv", "name": "Dotenv", "extensions": [".env"]},
        {"id": "elixir", "name": "Elixir", "extensions": [".ex", ".exs"]},
        {"id": "elm", "name": "Elm", "extensions": [".elm"]},
        {"id": "emacs-lisp", "name": "Emacs Lisp", "extensions": [".el"]},
        {"id": "erb", "name": "ERB", "extensions": [".erb"]},
        {"id": "erlang", "name": "Erlang", "extensions": [".erl", ".hrl"]},
        {"id": "fsharp", "name": "F#", "extensions": [".fs", ".fsx"]},
        {"id": "gdresource", "name": "GDResource", "extensions": [".tres", ".tscn"]},
        {"id": "gdscript", "name": "GDScript", "extensions": [".gd"]},
        {"id": "gherkin", "name": "Gherkin", "extensions": [".feature"]},
        {"id": "gitignore", "name": "Git Ignore", "extensions": [".gitignore"]},
        {"id": "glsl", "name": "GLSL", "extensions": [".glsl", ".vert", ".frag"]},
        {"id": "gnuplot", "name": "Gnuplot", "extensions": [".gp", ".gnu"]},
        {"id": "go", "name": "Go", "extensions": [".go"]},
        {"id": "graphql", "name": "GraphQL", "extensions": [".graphql", ".gql"]},
        {"id": "groovy", "name": "Groovy", "extensions": [".groovy", ".gvy"]},
        {"id": "hack", "name": "Hack", "extensions": [".hack"]},
        {"id": "handlebars", "name": "Handlebars", "extensions": [".hbs"]},
        {"id": "haskell", "name": "Haskell", "extensions": [".hs", ".lhs"]},
        {"id": "hcl", "name": "HCL", "extensions": [".hcl", ".tf"]},
        {"id": "hlsl", "name": "HLSL", "extensions": [".hlsl"]},
        {"id": "html", "name": "HTML", "extensions": [".html", ".htm"]},
        {"id": "http", "name": "HTTP", "extensions": [".http"]},
        {"id": "imba", "name": "Imba", "extensions": [".imba"]},
        {"id": "ini", "name": "INI", "extensions": [".ini", ".cfg"]},
        {"id": "java", "name": "Java", "extensions": [".java"]},
        {"id": "javascript", "name": "JavaScript", "extensions": [".js", ".mjs"]},
        {"id": "jinja-html", "name": "Jinja HTML", "extensions": [".jinja"]},
        {"id": "json", "name": "JSON", "extensions": [".json"]},
        {"id": "json5", "name": "JSON5", "extensions": [".json5"]},
        {"id": "jsonc", "name": "JSON with Comments", "extensions": [".jsonc"]},
        {"id": "jsonl", "name": "JSON Lines", "extensions": [".jsonl"]},
        {"id": "jsx", "name": "JSX", "extensions": [".jsx"]},
        {"id": "julia", "name": "Julia", "extensions": [".jl"]},
        {"id": "kotlin", "name": "Kotlin", "extensions": [".kt", ".kts"]},
        {"id": "latex", "name": "LaTeX", "extensions": [".tex", ".latex"]},
        {"id": "less", "name": "Less", "extensions": [".less"]},
        {"id": "lisp", "name": "Lisp", "extensions": [".lisp", ".lsp"]},
        {"id": "log", "name": "Log", "extensions": [".log"]},
        {"id": "lua", "name": "Lua", "extensions": [".lua"]},
        {"id": "makefile", "name": "Makefile", "extensions": [".makefile"]},
        {"id": "markdown", "name": "Markdown", "extensions": [".md", ".mdx"]},
        {"id": "marko", "name": "Marko", "extensions": [".marko"]},
        {"id": "matlab", "name": "MATLAB", "extensions": [".m"]},
        {"id": "mdx", "name": "MDX", "extensions": [".mdx"]},
        {"id": "mermaid", "name": "Mermaid", "extensions": [".mmd"]},
        {"id": "nasm", "name": "NASM", "extensions": [".nasm"]},
        {"id": "nginx", "name": "Nginx", "extensions": [".nginx"]},
        {"id": "nim", "name": "Nim", "extensions": [".nim", ".nimble"]},
        {"id": "nix", "name": "Nix", "extensions": [".nix"]},
        {"id": "objective-c", "name": "Objective-C", "extensions": [".m", ".mm"]},
        {"id": "objective-cpp", "name": "Objective-C++", "extensions": [".mm"]},
        {"id": "ocaml", "name": "OCaml", "extensions": [".ml", ".mli"]},
        {"id": "pascal", "name": "Pascal", "extensions": [".pas"]},
        {"id": "perl", "name": "Perl", "extensions": [".pl", ".pm"]},
        {"id": "php", "name": "PHP", "extensions": [".php"]},
        {"id": "plsql", "name": "PL/SQL", "extensions": [".pls"]},
        {"id": "postcss", "name": "PostCSS", "extensions": [".pcss"]},
        {"id": "powershell", "name": "PowerShell", "extensions": [".ps1"]},
        {"id": "prisma", "name": "Prisma", "extensions": [".prisma"]},
        {"id": "prolog", "name": "Prolog", "extensions": [".pro"]},
        {"id": "protobuf", "name": "Protocol Buffers", "extensions": [".proto"]},
        {"id": "pug", "name": "Pug", "extensions": [".pug"]},
        {"id": "puppet", "name": "Puppet", "extensions": [".pp"]},
        {"id": "purescript", "name": "PureScript", "extensions": [".purs"]},
        {"id": "python", "name": "Python", "extensions": [".py"]},
        {"id": "r", "name": "R", "extensions": [".r", ".R"]},
        {"id": "racket", "name": "Racket", "extensions": [".rkt"]},
        {"id": "razor", "name": "Razor", "extensions": [".cshtml"]},
        {"id": "reg", "name": "Windows Registry", "extensions": [".reg"]},
        {"id": "robotframework", "name": "Robot Framework", "extensions": [".robot"]},
        {"id": "ruby", "name": "Ruby", "extensions": [".rb"]},
        {"id": "rust", "name": "Rust", "extensions": [".rs"]},
        {"id": "sass", "name": "Sass", "extensions": [".sass"]},
        {"id": "scala", "name": "Scala", "extensions": [".scala", ".sc"]},
        {"id": "scheme", "name": "Scheme", "extensions": [".scm"]},
        {"id": "scss", "name": "SCSS", "extensions": [".scss"]},
        {"id": "shaderlab", "name": "ShaderLab", "extensions": [".shader"]},
        {"id": "shellscript", "name": "Shell Script", "extensions": [".sh"]},
        {"id": "shellsession", "name": "Shell Session", "extensions": [".sh"]},
        {"id": "smalltalk", "name": "Smalltalk", "extensions": [".st"]},
        {"id": "solidity", "name": "Solidity", "extensions": [".sol"]},
        {"id": "sparql", "name": "SPARQL", "extensions": [".sparql"]},
        {"id": "sql", "name": "SQL", "extensions": [".sql"]},
        {"id": "ssh-config", "name": "SSH Config", "extensions": []},
        {"id": "stata", "name": "Stata", "extensions": [".do"]},
        {"id": "stylus", "name": "Stylus", "extensions": [".styl"]},
        {"id": "svelte", "name": "Svelte", "extensions": [".svelte"]},
        {"id": "swift", "name": "Swift", "extensions": [".swift"]},
        {"id": "system-verilog", "name": "SystemVerilog", "extensions": [".sv"]},
        {"id": "tcl", "name": "Tcl", "extensions": [".tcl"]},
        {"id": "toml", "name": "TOML", "extensions": [".toml"]},
        {"id": "tsx", "name": "TSX", "extensions": [".tsx"]},
        {"id": "typescript", "name": "TypeScript", "extensions": [".ts", ".mts"]},
        {"id": "v", "name": "V", "extensions": [".v"]},
        {"id": "vb", "name": "Visual Basic", "extensions": [".vb"]},
        {"id": "verilog", "name": "Verilog", "extensions": [".v"]},
        {"id": "vhdl", "name": "VHDL", "extensions": [".vhd", ".vhdl"]},
        {"id": "viml", "name": "Vim Script", "extensions": [".vim"]},
        {"id": "vue", "name": "Vue", "extensions": [".vue"]},
        {"id": "wasm", "name": "WebAssembly", "extensions": [".wasm"]},
        {"id": "wenyan", "name": "Wenyan", "extensions": [".wy"]},
        {"id": "wgsl", "name": "WGSL", "extensions": [".wgsl"]},
        {"id": "xml", "name": "XML", "extensions": [".xml"]},
        {"id": "xsl", "name": "XSL", "extensions": [".xsl"]},
        {"id": "yaml", "name": "YAML", "extensions": [".yaml", ".yml"]},
        {"id": "zenscript", "name": "ZenScript", "extensions": [".zs"]},
        {"id": "zig", "name": "Zig", "extensions": [".zig"]},
    ]
