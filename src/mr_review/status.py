from dataclasses import asdict, dataclass, field
from pathlib import Path

from mr_review.layout import line_label, state_path, thread_path
from mr_review.parse import ParsedThread, ParseError, parse_thread
from mr_review.plan import plan_thread
from mr_review.store import dict_to_position, load_state, position_is_outdated

_EXCERPT_LEN = 80


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


@dataclass
class StatusReport:
    mr: str
    summary: dict = field(default_factory=dict)
    filter: dict = field(default_factory=dict)
    threads: list = field(default_factory=list)


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
    review_dir: Path, mr: str, *, unresolved: bool = False, file: str | None = None
) -> StatusReport:
    state = load_state(state_path(review_dir, mr))
    report = StatusReport(mr=mr, filter={"unresolved": unresolved, "file": file})
    if state is None:
        report.summary = _summary([])
        return report
    for thread in state.threads:
        if unresolved and thread.resolved:
            continue
        pos = dict_to_position(thread.position)
        if file is not None:
            paths = {p for p in ((pos.new_path, pos.old_path) if pos else ()) if p}
            if file not in paths:
                continue
        source_file = (pos.new_path or pos.old_path) if pos else None
        path = thread_path(review_dir, mr, thread.local_id, pos)
        outdated = position_is_outdated(thread.position, state.head_sha)
        reviewers = _reviewers(thread.notes, state.current_user)
        note_count = len(thread.notes)
        excerpt = _excerpt(thread.notes[0].body) if thread.notes else ""
        if path.exists():
            try:
                parsed = parse_thread(path.read_text())
            except ParseError as e:
                report.threads.append(
                    ThreadStatus(
                        local_id=thread.local_id,
                        file=source_file,
                        line=line_label(pos),
                        resolved=thread.resolved,
                        reviewers=reviewers,
                        note_count=note_count,
                        excerpt=excerpt,
                        draft_state="error",
                        outdated=outdated,
                        warnings=[f"parse error: {e}"],
                    )
                )
                continue
        else:
            parsed = ParsedThread(frontmatter={}, reply="", note_edits={})
        plan = plan_thread(parsed, thread)
        actions = [{"type": type(a).__name__, **asdict(a)} for a in plan.actions]
        if actions:
            draft_state = "ready"
        elif parsed.reply.strip():
            draft_state = "wip"
        else:
            draft_state = "clean"
        report.threads.append(
            ThreadStatus(
                local_id=thread.local_id,
                file=source_file,
                line=line_label(pos),
                resolved=thread.resolved,
                reviewers=reviewers,
                note_count=note_count,
                excerpt=excerpt,
                draft_state=draft_state,
                outdated=outdated,
                actions=actions,
                warnings=[w.message for w in plan.warnings],
            )
        )
    report.summary = _summary(report.threads)
    return report


def status_json(report: StatusReport) -> dict:
    return {
        "mr": report.mr,
        "summary": report.summary,
        "filter": report.filter,
        "threads": [asdict(t) for t in report.threads],
    }


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
        if t.excerpt:
            lines.append(f'      "{t.excerpt}"')
        for w in t.warnings:
            lines.append(f"      ⚠ {w}")
    if s.get("ready", 0) == 0:
        lines.append("  (nothing marked ready)")
    return "\n".join(lines)
