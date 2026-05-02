"""Text extraction from HTML and Markdown content."""

from __future__ import annotations

import re

# Safety limit — prevent processing absurdly large payloads
_MAX_CHARS = 100_000

# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------

_RE_FENCED_CODE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_RE_INLINE_CODE = re.compile(r"`[^`]+`")
_RE_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_RE_BOLD = re.compile(r"\*{1,2}([^*]+)\*{1,2}")
_RE_ITALIC = re.compile(r"_([^_]+)_")
_RE_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_RE_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_RE_HTML_TAG = re.compile(r"<[^>]+>")


def extract_text_from_markdown(md: str) -> str:
    """Strip Markdown formatting and return plain text.

    Removes code blocks, heading markers, bold/italic, links (keeps text),
    images. Collapses whitespace. Limited to 100 KB.
    """
    text = md[:_MAX_CHARS]
    text = _RE_FENCED_CODE.sub("", text)
    text = _RE_INLINE_CODE.sub("", text)
    text = _RE_HEADING.sub("", text)
    text = _RE_IMAGE.sub("", text)
    text = _RE_LINK.sub(r"\1", text)
    text = _RE_BOLD.sub(r"\1", text)
    text = _RE_ITALIC.sub(r"\1", text)
    text = _RE_HTML_TAG.sub("", text)
    return _collapse_whitespace(text)


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

_RE_SCRIPT = re.compile(r"<script[\s\S]*?</script>", re.IGNORECASE)
_RE_STYLE = re.compile(r"<style[\s\S]*?</style>", re.IGNORECASE)
_RE_BLOCK = re.compile(r"</?(?:p|div|br|h[1-6]|li|tr|blockquote|section|article)[^>]*>", re.IGNORECASE)
_RE_TAG = re.compile(r"<[^>]+>")

# HTML entities
_HTML_ENTITIES = {
    "&amp;": "&", "&lt;": "<", "&gt;": ">",
    "&quot;": '"', "&#39;": "'", "&apos;": "'",
    "&nbsp;": " ",
}


def _decode_entities(text: str) -> str:
    """Decode common HTML entities."""
    for entity, char in _HTML_ENTITIES.items():
        text = text.replace(entity, char)
    # Numeric entities like &#123;
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    text = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), text)
    return text


def extract_text_from_html(html: str) -> str:
    """Strip HTML tags and return plain text.

    Removes script/style, replaces block elements with newlines,
    strips tags, decodes entities. Limited to 100 KB.
    """
    text = html[:_MAX_CHARS]
    text = _RE_SCRIPT.sub("", text)
    text = _RE_STYLE.sub("", text)
    text = _RE_BLOCK.sub("\n", text)
    text = _RE_TAG.sub("", text)
    text = _decode_entities(text)
    return _collapse_whitespace(text)


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------

def _collapse_whitespace(text: str) -> str:
    """Collapse runs of whitespace into single spaces, strip edges."""
    return re.sub(r"\s+", " ", text).strip()
