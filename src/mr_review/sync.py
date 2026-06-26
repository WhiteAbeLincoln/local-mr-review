# src/mr_review/sync.py
from dataclasses import dataclass, field
from pathlib import Path

from mr_review.diffcontext import build_context
from mr_review.domain import MergeRef
from mr_review.git import GitRunner
from mr_review.layout import ensure_gitignore, state_path, thread_path
from mr_review.parse import ParseError, parse_thread
from mr_review.render import RenderInputs, render_thread
from mr_review.store import (
    assign_handles,
    dict_to_position,
    load_state,
    save_state,
)


@dataclass
class SyncResult:
    written: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)


def sync(forge, review_dir: Path, mr_ref: MergeRef, git: GitRunner, now: str) -> SyncResult:
    mr = forge.fetch_mr(mr_ref)
    discussions = forge.list_discussions(mr_ref)
    prev = load_state(state_path(review_dir, mr.iid))
    prev_threads = {t.native_id: t for t in prev.threads} if prev else {}

    new_state = assign_handles(
        prev,
        discussions,
        forge="gitlab",
        project=mr.project,
        mr=mr.iid,
        base_sha=mr.base_sha,
        start_sha=mr.start_sha,
        head_sha=mr.head_sha,
        current_user=mr.current_user,
        synced_at=now,
    )

    result = SyncResult()
    for thread in new_state.threads:
        prior = prev_threads.get(thread.native_id)
        path = thread_path(review_dir, mr.iid, thread.local_id, dict_to_position(thread.position))
        reply_draft, publish, resolve, edit_notes, overrides, conflicts = _merge_local(
            path, thread, prior
        )
        diff_block = build_context(dict_to_position(thread.position), git)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            render_thread(
                RenderInputs(
                    thread=thread,
                    diff_block=diff_block,
                    reply_draft=reply_draft,
                    publish=publish,
                    resolve=resolve,
                    edit_notes=edit_notes,
                    note_overrides=overrides,
                    conflicts=conflicts,
                    mr_head_sha=mr.head_sha,
                )
            )
        )
        result.written.append(path)
        for h in conflicts:
            result.conflicts.append((thread.local_id, h))

    save_state(state_path(review_dir, mr.iid), new_state)
    ensure_gitignore(review_dir)
    return result


def _merge_local(path: Path, thread, prior):
    """Recover drafts/edits from an existing file; preserve and flag conflicts."""
    if not path.exists():
        return ("", False, False, [], {}, set())
    try:
        parsed = parse_thread(path.read_text())
    except ParseError:
        return ("", False, False, [], {}, set())  # malformed file: regenerate clean

    fm = parsed.frontmatter or {}
    prior_bodies = {n.local_id: n.body for n in prior.notes} if prior else {}
    new_bodies = {n.local_id: n.body for n in thread.notes}

    overrides: dict[int, str] = {}
    conflicts: set[int] = set()
    for handle, file_body in parsed.note_edits.items():
        new_body = new_bodies.get(handle)
        if new_body == file_body:
            # upstream already matches my local edit (e.g. I just published it):
            # reconciled — not a pending draft, not a conflict.
            continue
        prev_body = prior_bodies.get(handle)
        if prev_body is not None and file_body != prev_body:  # locally edited
            overrides[handle] = file_body
            if new_body != prev_body:  # upstream also changed
                conflicts.add(handle)
    return (
        parsed.reply,
        bool(fm.get("publish")),
        bool(fm.get("resolve")),
        list(fm.get("edit_notes") or []),
        overrides,
        conflicts,
    )
