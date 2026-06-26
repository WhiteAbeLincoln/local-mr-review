from dataclasses import dataclass, field

import yaml

from mr_review.domain import DiffPosition
from mr_review.layout import line_label
from mr_review.markers import (
    DRAFT_LINE,
    PUBLISHED_PREFIX,
    neutralize,
    note_close,
    note_open,
)
from mr_review.store import StoredThread, dict_to_position, position_is_outdated


@dataclass
class RenderInputs:
    thread: StoredThread
    diff_block: str | None
    reply_draft: str
    publish: bool
    resolve: bool
    edit_notes: list[int]
    note_overrides: dict[int, str] = field(default_factory=dict)
    conflicts: set[int] = field(default_factory=set)
    mr_head_sha: str = ""


def link_for(position: DiffPosition | None) -> str | None:
    if position is None:
        return None
    path = position.new_path or position.old_path
    if not path:
        return None
    line = position.new_line or position.old_line
    anchor = f"#L{line}" if line else ""
    return f"[↗ open {path}:{line if line else ''}](../../{path}{anchor})"


def dump_frontmatter(data: dict) -> str:
    """Serialize frontmatter exactly as thread files store it: insertion order
    preserved (no key sorting), trailing whitespace stripped. Shared with the
    write path so drafted files round-trip through sync without reformatting."""
    return yaml.safe_dump(data, sort_keys=False).rstrip()


def _frontmatter(inp: RenderInputs) -> str:
    pos = dict_to_position(inp.thread.position)
    outdated = position_is_outdated(inp.thread.position, inp.mr_head_sha)
    data = {
        "thread": inp.thread.local_id,
        "file": (pos.new_path or pos.old_path) if pos else None,
        "line": _line_value(pos),
        "resolvable": inp.thread.resolvable,
        "resolved": inp.thread.resolved,
        "outdated": outdated,
        "publish": inp.publish,
        "resolve": inp.resolve,
        "edit_notes": list(inp.edit_notes),
    }
    return dump_frontmatter(data)


def _line_value(pos: DiffPosition | None):
    if pos is None:
        return "general"
    if pos.line_range:
        return f"{pos.line_range[0]}-{pos.line_range[1]}"
    if pos.new_line is not None:
        return pos.new_line
    if pos.old_line is not None:
        return f"old:{pos.old_line}"
    return "general"


def render_thread(inp: RenderInputs) -> str:
    t = inp.thread
    pos = dict_to_position(t.position)
    outdated = position_is_outdated(t.position, inp.mr_head_sha)
    state = "resolved" if t.resolved else "unresolved"
    title_loc = (pos.new_path or pos.old_path) if pos else "general"
    parts: list[str] = []
    parts.append(f"---\n{_frontmatter(inp)}\n---")
    parts.append(
        f"# {title_loc} · {line_label(pos)} · {state}" if pos else f"# general discussion · {state}"
    )
    link = link_for(pos)
    if link:
        parts.append(link)
    if outdated and pos is not None:
        pos_head = (t.position or {}).get("head_sha", "")
        mr_head = inp.mr_head_sha
        parts.append(
            f"> ⚠ Outdated: anchored to commit {pos_head[:8]}, behind the MR head"
            f" ({mr_head[:8]}). The diff context above is what the reviewer saw;"
            f" the linked line may have moved."
        )
    if inp.diff_block:
        parts.append(inp.diff_block)
    parts.append(f"{PUBLISHED_PREFIX} (display only — regenerated each sync) -->")
    for note in t.notes:
        if note.local_id in inp.conflicts:
            parts.append(
                f"⚠ note {note.local_id} changed upstream since you started editing — review your edit"
            )
        parts.append(f"### @{note.author} · {note.created_at} · note {note.local_id}")
        if note.mine:
            body = inp.note_overrides.get(note.local_id, note.body)
            parts.append(note_open(note.local_id))
            parts.append(neutralize(body))
            parts.append(note_close(note.local_id))
        else:
            parts.append(neutralize(note.body))
    parts.append(DRAFT_LINE)
    if inp.reply_draft:
        parts.append(inp.reply_draft)
    return "\n\n".join(parts).rstrip() + "\n"
