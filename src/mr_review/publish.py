# src/mr_review/publish.py
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from mr_review.domain import MergeRef
from mr_review.layout import state_path, thread_path
from mr_review.markers import NS
from mr_review.parse import ParseError, parse_thread
from mr_review.plan import EditAction, ReplyAction, ResolveAction, plan_thread
from mr_review.store import dict_to_position, load_state
from mr_review.sync import sync


@dataclass
class PublishResult:
    posted: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    dry_run: bool = False


def publish(
    forge, review_dir: Path, mr_ref: MergeRef, git, now: str, dry_run: bool = False
) -> PublishResult:
    mr = forge.fetch_mr(mr_ref)
    state = load_state(state_path(review_dir, mr.iid))
    result = PublishResult(dry_run=dry_run)
    if state is None:
        return result

    for thread in state.threads:
        pos = dict_to_position(thread.position)
        path = thread_path(review_dir, mr.iid, thread.local_id, pos)
        if not path.exists():
            continue
        try:
            parsed = parse_thread(path.read_text())
        except ParseError as e:
            result.failed.append((path.name, f"parse error: {e}"))
            continue
        plan = plan_thread(parsed, thread)
        for action in plan.actions:
            if dry_run:
                result.posted.append(_describe(action))
                continue
            try:
                _execute(forge, mr_ref, action)
            except Exception as e:
                # forge post failed: not posted, draft left intact so a retry is safe
                result.failed.append((path.name, f"{_describe(action)}: {e}"))
                continue
            result.posted.append(_describe(action))
            try:
                _clear_draft(path, action)
            except Exception as e:
                # posted successfully but couldn't clear the draft — warn loudly so the
                # user edits the file before re-running, to avoid a double-post
                result.failed.append(
                    (
                        path.name,
                        f"posted {_describe(action)} but FAILED to clear its draft "
                        f"— edit the file to avoid re-posting on next publish: {e}",
                    )
                )

    if not dry_run:
        sync(forge, review_dir, mr_ref, git, now)  # rebuild canonical + re-render
    return result


def _execute(forge, mr_ref, action) -> None:
    if isinstance(action, ReplyAction):
        forge.reply(mr_ref, action.discussion_id, action.body)
    elif isinstance(action, EditAction):
        forge.edit_note(mr_ref, action.discussion_id, action.note_id, action.body)
    elif isinstance(action, ResolveAction):
        forge.set_resolved(mr_ref, action.discussion_id, True)


def _describe(action) -> str:
    return f"{type(action).__name__}@thread{action.thread_local_id}"


_DRAFT_LINE = re.compile(rf"^<!-- {re.escape(NS)}:draft\b.*?-->\s*$", re.MULTILINE)


def _clear_draft(path: Path, action) -> None:
    text = path.read_text()
    if isinstance(action, ReplyAction):
        text = _set_frontmatter(text, "publish", False)
        m = _DRAFT_LINE.search(text)
        if m:
            text = text[: m.end()] + "\n"
    elif isinstance(action, EditAction):
        text = _drop_edit_handle(text, action.note_local_id)
    elif isinstance(action, ResolveAction):
        text = _set_frontmatter(text, "resolve", False)
    path.write_text(text)


def _split_fm(text):
    parts = text.split("---\n", 2)
    return parts[1], parts[2]  # (frontmatter_yaml, body)


def _set_frontmatter(text: str, key: str, value) -> str:
    fm_text, body = _split_fm(text)
    fm = yaml.safe_load(fm_text) or {}
    fm[key] = value
    return f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n{body}"


def _drop_edit_handle(text: str, handle: int) -> str:
    fm_text, body = _split_fm(text)
    fm = yaml.safe_load(fm_text) or {}
    fm["edit_notes"] = [h for h in (fm.get("edit_notes") or []) if h != handle]
    return f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n{body}"
