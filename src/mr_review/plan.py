# src/mr_review/plan.py
from dataclasses import dataclass, field

from mr_review.parse import ParsedThread
from mr_review.store import StoredThread


@dataclass(frozen=True)
class ReplyAction:
    thread_local_id: int
    discussion_id: str
    body: str


@dataclass(frozen=True)
class EditAction:
    thread_local_id: int
    discussion_id: str
    note_id: str
    note_local_id: int
    body: str


@dataclass(frozen=True)
class ResolveAction:
    thread_local_id: int
    discussion_id: str


@dataclass(frozen=True)
class PlanWarning:
    thread_local_id: int
    message: str


@dataclass
class ThreadPlan:
    actions: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def plan_thread(parsed: ParsedThread, thread: StoredThread) -> ThreadPlan:
    plan = ThreadPlan()
    fm = parsed.frontmatter
    tid = thread.local_id
    by_handle = {n.local_id: n for n in thread.notes}
    edit_notes = set(fm.get("edit_notes") or [])

    if fm.get("publish"):
        if parsed.reply.strip():
            plan.actions.append(ReplyAction(tid, thread.native_id, parsed.reply.strip()))
        else:
            plan.warnings.append(PlanWarning(tid, "publish: true but the reply is empty"))

    for handle in sorted(edit_notes):
        note = by_handle.get(handle)
        if note is None:
            plan.warnings.append(
                PlanWarning(tid, f"edit_notes references note {handle}, which does not exist")
            )
            continue
        if not note.mine:
            plan.warnings.append(
                PlanWarning(tid, f"note {handle} is not yours and cannot be edited")
            )
            continue
        if handle not in parsed.note_edits:
            plan.warnings.append(
                PlanWarning(tid, f"note {handle} marked for edit but its block is missing")
            )
            continue
        new_body = parsed.note_edits[handle]
        if new_body == note.body:
            plan.warnings.append(PlanWarning(tid, f"note {handle} marked for edit but unchanged"))
            continue
        plan.actions.append(EditAction(tid, thread.native_id, note.native_id, handle, new_body))

    for handle, new_body in parsed.note_edits.items():
        note = by_handle.get(handle)
        if note and note.mine and handle not in edit_notes and new_body != note.body:
            plan.warnings.append(
                PlanWarning(
                    tid, f"note {handle} was edited but not listed in edit_notes — not published"
                )
            )

    if fm.get("resolve") and not thread.resolved:
        plan.actions.append(ResolveAction(tid, thread.native_id))

    return plan
