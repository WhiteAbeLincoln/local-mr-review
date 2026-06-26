import re

import yaml

from mr_review.markers import DRAFT_LINE, neutralize, note_close, note_open
from mr_review.render import dump_frontmatter

_FM = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


class DraftError(Exception):
    pass


def _split(text: str) -> tuple[dict, str]:
    """Return (frontmatter dict, body-after-frontmatter). The body keeps its
    leading blank line so it can be re-joined verbatim."""
    m = _FM.match(text)
    if not m:
        raise DraftError("missing or malformed frontmatter block")
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise DraftError(f"invalid frontmatter YAML: {e}") from e
    return fm, text[m.end() :]


def _replace_reply(body: str, reply_text: str) -> str:
    i = body.find(DRAFT_LINE)
    if i == -1:
        raise DraftError("draft marker not found in thread file")
    published = body[:i]  # keeps the blank line that precedes the marker
    reply = neutralize(reply_text).strip()
    out = published + DRAFT_LINE
    if reply:
        out += "\n\n" + reply
    return out


def _replace_note(body: str, handle: int, new_body: str) -> str:
    open_marker, close_marker = note_open(handle), note_close(handle)
    oi = body.find(open_marker)
    ci = body.find(close_marker)
    if oi == -1 or ci == -1 or ci < oi:
        raise DraftError(f"note {handle} is not one of your own editable notes")
    edited = neutralize(new_body).strip()
    return body[: oi + len(open_marker)] + "\n\n" + edited + "\n\n" + body[ci:]


def _apply(
    text: str,
    *,
    reply: str | None = None,
    note: tuple[int, str] | None = None,
    publish: bool | None = None,
    resolve: bool | None = None,
) -> str:
    fm, body = _split(text)
    if publish is not None:
        fm["publish"] = bool(publish)
    if resolve is not None:
        fm["resolve"] = bool(resolve)
    if note is not None:
        handle, new_body = note
        body = _replace_note(body, handle, new_body)
        marked = list(fm.get("edit_notes") or [])
        if handle not in marked:
            marked.append(handle)
        fm["edit_notes"] = sorted(marked)
    if reply is not None:
        body = _replace_reply(body, reply)
    doc = f"---\n{dump_frontmatter(fm)}\n---\n{body}"
    return doc.rstrip() + "\n"


def write_reply(
    text: str, body: str, *, publish: bool | None = None, resolve: bool | None = None
) -> str:
    return _apply(text, reply=body, publish=publish, resolve=resolve)


def write_note_edit(
    text: str,
    handle: int,
    body: str,
    *,
    publish: bool | None = None,
    resolve: bool | None = None,
) -> str:
    return _apply(text, note=(handle, body), publish=publish, resolve=resolve)


def set_flags(text: str, *, publish: bool | None = None, resolve: bool | None = None) -> str:
    return _apply(text, publish=publish, resolve=resolve)
