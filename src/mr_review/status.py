from dataclasses import asdict, dataclass, field
from pathlib import Path

from mr_review.layout import line_label, state_path, thread_path
from mr_review.parse import ParsedThread, ParseError, parse_thread
from mr_review.plan import plan_thread
from mr_review.store import dict_to_position, load_state, position_is_outdated


@dataclass
class ThreadStatus:
    local_id: int
    file: str
    line: str
    resolved: bool
    outdated: bool = False
    actions: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


@dataclass
class StatusReport:
    mr: str
    threads: list = field(default_factory=list)


def gather_status(review_dir: Path, mr: str) -> StatusReport:
    state = load_state(state_path(review_dir, mr))
    report = StatusReport(mr=mr)
    if state is None:
        return report
    for thread in state.threads:
        pos = dict_to_position(thread.position)
        path = thread_path(review_dir, mr, thread.local_id, pos)
        outdated = position_is_outdated(thread.position, state.head_sha)
        if path.exists():
            try:
                parsed = parse_thread(path.read_text())
            except ParseError as e:
                report.threads.append(
                    ThreadStatus(
                        thread.local_id,
                        path.name,
                        line_label(pos),
                        thread.resolved,
                        outdated=outdated,
                        warnings=[f"parse error: {e}"],
                    )
                )
                continue
        else:
            parsed = ParsedThread(frontmatter={}, reply="", note_edits={})
        plan = plan_thread(parsed, thread)
        report.threads.append(
            ThreadStatus(
                local_id=thread.local_id,
                file=path.name,
                line=line_label(pos),
                resolved=thread.resolved,
                outdated=outdated,
                actions=[{"type": type(a).__name__, **asdict(a)} for a in plan.actions],
                warnings=[w.message for w in plan.warnings],
            )
        )
    return report


def status_json(report: StatusReport) -> dict:
    return {"mr": report.mr, "threads": [asdict(t) for t in report.threads]}


def format_status(report: StatusReport) -> str:
    lines = [f"MR !{report.mr}"]
    for t in report.threads:
        state = "resolved" if t.resolved else "unresolved"
        outdated_suffix = " · outdated" if t.outdated else ""
        lines.append(f"  thread {t.local_id} · {t.file} · {t.line} · {state}{outdated_suffix}")
        for a in t.actions:
            detail = a.get("body", "") or ("resolve" if a["type"] == "ResolveAction" else "")
            lines.append(f"    READY {a['type']}: {detail[:60]}")
        for w in t.warnings:
            lines.append(f"    ⚠ {w}")
    if all(not t.actions for t in report.threads):
        lines.append("  (nothing marked ready)")
    return "\n".join(lines)
