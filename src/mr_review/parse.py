import re
from dataclasses import dataclass

import yaml

from mr_review.markers import NS


class ParseError(Exception):
    pass


@dataclass
class ParsedThread:
    frontmatter: dict
    reply: str
    note_edits: dict[int, str]


_FM = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_DRAFT_LINE = re.compile(rf"^<!-- {re.escape(NS)}:draft\b.*?-->\s*$", re.MULTILINE)
_NOTE_OPEN = re.compile(rf"<!-- {re.escape(NS)}:note (\d+) -->")
_NOTE_CLOSE = re.compile(rf"<!-- {re.escape(NS)}:/note (\d+) -->")


def parse_thread(text: str) -> ParsedThread:
    m = _FM.match(text)
    if not m:
        raise ParseError("missing or malformed frontmatter block")
    try:
        frontmatter = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise ParseError(f"invalid frontmatter YAML: {e}") from e
    body = text[m.end() :]

    draft_markers = list(_DRAFT_LINE.finditer(body))
    if len(draft_markers) != 1:
        raise ParseError(f"expected exactly one draft marker, found {len(draft_markers)}")
    draft_at = draft_markers[0]
    published, reply = body[: draft_at.start()], body[draft_at.end() :].strip()

    note_edits = _extract_note_edits(published)
    return ParsedThread(frontmatter=frontmatter, reply=reply, note_edits=note_edits)


def _extract_note_edits(published: str) -> dict[int, str]:
    # Collect every open/close marker in document order, then require a strict
    # alternation of (open H, close H) pairs. This rejects lone markers,
    # mismatched handles, out-of-order (close before open), and interleaved
    # ("open 2, open 3, close 2, close 3") structures.
    tokens = sorted(
        [(m.start(), "open", int(m.group(1)), m.end()) for m in _NOTE_OPEN.finditer(published)]
        + [(m.start(), "close", int(m.group(1)), m.end()) for m in _NOTE_CLOSE.finditer(published)]
    )
    edits: dict[int, str] = {}
    i = 0
    while i < len(tokens):
        o_start, o_kind, o_handle, o_end = tokens[i]
        if o_kind != "open":
            raise ParseError(f"note close marker for handle {o_handle} without a matching open")
        if i + 1 >= len(tokens):
            raise ParseError("unbalanced note markers")
        c_start, c_kind, c_handle, c_end = tokens[i + 1]
        if c_kind != "close" or c_handle != o_handle:
            raise ParseError("mismatched, out-of-order, or interleaved note markers")
        if o_handle in edits:
            raise ParseError(f"duplicate note marker for handle {o_handle}")
        edits[o_handle] = published[o_end:c_start].strip()
        i += 2
    return edits
