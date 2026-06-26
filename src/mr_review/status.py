import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mr_review.layout import line_label, state_path, thread_path
from mr_review.markers import PUBLISHED_PREFIX
from mr_review.parse import ParsedThread, ParseError, parse_thread
from mr_review.plan import plan_thread
from mr_review.store import dict_to_position, load_state, position_is_outdated

_EXCERPT_LEN = 80

_DIFF_RE = re.compile(r"```diff\n.*?```", re.DOTALL)


def _extract_diff(text: str) -> str | None:
    # The diff fence is rendered above the published marker; a reviewer comment
    # below it could also contain a ```diff fence, so only search the head.
    head = text.split(PUBLISHED_PREFIX, 1)[0]
    m = _DIFF_RE.search(head)
    return m.group(0) if m else None


def _notes_full(notes: list) -> list[dict]:
    return [
        {
            "handle": n.local_id,
            "author": n.author,
            "created_at": n.created_at,
            "body": n.body,
            "mine": n.mine,
        }
        for n in notes
    ]


@dataclass
class ThreadStatus:
    local_id: int
    file: str | None
    line: str
    resolved: bool
    reviewers: list[str]
    note_count: int
    excerpt: str
    draft_state: str
    outdated: bool = False
    actions: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    diff: str | None = None
    notes: list | None = None
    draft: dict | None = None


@dataclass
class StatusReport:
    mr: str
    summary: dict = field(default_factory=dict)
    filter: dict = field(default_factory=dict)
    threads: list = field(default_factory=list)
    full: bool = False


def _excerpt(body: str) -> str:
    text = " ".join(body.split())
    return text[: _EXCERPT_LEN - 1] + "…" if len(text) > _EXCERPT_LEN else text


def _reviewers(notes: list, current_user: str) -> list[str]:
    return sorted({n.author for n in notes if n.author != current_user})


def _summary(threads: list) -> dict:
    return {
        "threads": len(threads),
        "unresolved": sum(1 for t in threads if not t.resolved),
        "ready": sum(1 for t in threads if t.draft_state == "ready"),
        "wip": sum(1 for t in threads if t.draft_state == "wip"),
        "warnings": sum(1 for t in threads if t.warnings),
    }


def gather_status(
    review_dir: Path,
    mr: str,
    *,
    unresolved: bool = False,
    file: str | None = None,
    thread: int | None = None,
    full: bool = False,
) -> StatusReport:
    state = load_state(state_path(review_dir, mr))
    report = StatusReport(mr=mr, filter={"unresolved": unresolved, "file": file}, full=full)
    if state is None:
        report.summary = _summary([])
        return report
    for thread_obj in state.threads:
        if unresolved and thread_obj.resolved:
            continue
        if thread is not None and thread_obj.local_id != thread:
            continue
        pos = dict_to_position(thread_obj.position)
        if file is not None:
            paths = {p for p in ((pos.new_path, pos.old_path) if pos else ()) if p}
            if file not in paths:
                continue
        source_file = (pos.new_path or pos.old_path) if pos else None
        path = thread_path(review_dir, mr, thread_obj.local_id, pos)
        outdated = position_is_outdated(thread_obj.position, state.head_sha)
        reviewers = _reviewers(thread_obj.notes, state.current_user)
        note_count = len(thread_obj.notes)
        excerpt = _excerpt(thread_obj.notes[0].body) if thread_obj.notes else ""
        file_text = path.read_text() if path.exists() else None
        diff = _extract_diff(file_text) if (full and file_text) else None
        notes = _notes_full(thread_obj.notes) if full else None
        if file_text is not None:
            try:
                parsed = parse_thread(file_text)
            except ParseError as e:
                report.threads.append(
                    ThreadStatus(
                        local_id=thread_obj.local_id,
                        file=source_file,
                        line=line_label(pos),
                        resolved=thread_obj.resolved,
                        reviewers=reviewers,
                        note_count=note_count,
                        excerpt=excerpt,
                        draft_state="error",
                        outdated=outdated,
                        warnings=[f"parse error: {e}"],
                        diff=diff,
                        notes=notes,
                        draft=None,
                    )
                )
                continue
        else:
            parsed = ParsedThread(frontmatter={}, reply="", note_edits={})
        plan = plan_thread(parsed, thread_obj)
        actions = [{"type": type(a).__name__, **asdict(a)} for a in plan.actions]
        if actions:
            draft_state = "ready"
        elif parsed.reply.strip():
            draft_state = "wip"
        else:
            draft_state = "clean"
        report.threads.append(
            ThreadStatus(
                local_id=thread_obj.local_id,
                file=source_file,
                line=line_label(pos),
                resolved=thread_obj.resolved,
                reviewers=reviewers,
                note_count=note_count,
                excerpt=excerpt,
                draft_state=draft_state,
                outdated=outdated,
                actions=actions,
                warnings=[w.message for w in plan.warnings],
                diff=diff,
                notes=notes,
                draft={"reply": parsed.reply, "note_edits": parsed.note_edits} if full else None,
            )
        )
    report.summary = _summary(report.threads)
    return report


def status_json(report: StatusReport) -> dict:
    return {
        "mr": report.mr,
        "summary": report.summary,
        "filter": report.filter,
        "threads": [_thread_json(t, report.full) for t in report.threads],
    }


def _thread_json(t: ThreadStatus, full: bool) -> dict:
    d = asdict(t)
    if full:
        d.pop("excerpt", None)
    else:
        for k in ("diff", "notes", "draft"):
            d.pop(k, None)
    return d


def _location(t: ThreadStatus) -> str:
    return f"{t.file}:{t.line}" if t.file else "general"


def _notes_label(n: int) -> str:
    return f"{n} note" if n == 1 else f"{n} notes"


def _draft_tag(t: ThreadStatus) -> str:
    if t.draft_state == "ready":
        present = {a["type"] for a in t.actions}
        kinds = [
            label
            for name, label in (
                ("ReplyAction", "reply ready"),
                ("EditAction", "edit ready"),
                ("ResolveAction", "resolve ready"),
            )
            if name in present
        ]
        return f" · [{', '.join(kinds)}]"
    if t.draft_state == "wip":
        return " · [draft: not ready]"
    return ""


def _append_full(lines: list, t: ThreadStatus) -> None:
    if t.diff:
        lines.extend("    " + ln for ln in t.diff.splitlines())
    for n in t.notes or []:
        lines.append(f"    @{n['author']} · {n['created_at']} · note {n['handle']}")
        lines.extend("    " + ln for ln in n["body"].splitlines())
    draft = t.draft or {}
    if draft.get("reply"):
        lines.append("    --- draft reply ---")
        lines.extend("    " + ln for ln in draft["reply"].splitlines())
    for handle, body in (draft.get("note_edits") or {}).items():
        lines.append(f"    --- draft edit to note {handle} ---")
        lines.extend("    " + ln for ln in body.splitlines())


def format_status(report: StatusReport) -> str:
    s = report.summary
    lines = [
        f"MR !{report.mr} — {s['threads']} thread(s): {s['unresolved']} unresolved, "
        f"{s['ready']} ready to publish, {s['wip']} WIP, {s['warnings']} warnings"
    ]
    active = []
    if report.filter.get("unresolved"):
        active.append("unresolved")
    if report.filter.get("file"):
        active.append(f"file={report.filter['file']}")
    if active:
        lines.append(f"  (filtered: {', '.join(active)})")
    for t in report.threads:
        state = "resolved" if t.resolved else "unresolved"
        reviewer = ", ".join(f"@{r}" for r in t.reviewers) if t.reviewers else "(self)"
        outdated = " · outdated" if t.outdated else ""
        lines.append(
            f"  thread {t.local_id} · {reviewer} · {_location(t)} · {state}{outdated} · "
            f"{_notes_label(t.note_count)}{_draft_tag(t)}"
        )
        if report.full:
            _append_full(lines, t)
        elif t.excerpt:
            lines.append(f'      "{t.excerpt}"')
        for w in t.warnings:
            lines.append(f"      ⚠ {w}")
    if s.get("ready", 0) == 0:
        lines.append("  (nothing marked ready)")
    return "\n".join(lines)
