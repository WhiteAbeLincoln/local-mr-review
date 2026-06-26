# tests/test_plan.py
from mr_review.parse import ParsedThread
from mr_review.plan import (
    plan_thread,
)
from mr_review.store import StoredNote, StoredThread


def thread(resolved=False):
    return StoredThread(
        local_id=1,
        native_id="d1",
        resolvable=True,
        resolved=resolved,
        position=None,
        notes=[
            StoredNote(1, "501", "reviewer", False, "t", "t", "review", True, False),
            StoredNote(2, "502", "me", True, "t", "t", "canonical body", True, False),
        ],
        retired_note_handles=[],
    )


def parsed(publish=False, reply="", resolve=False, edit_notes=None, note_edits=None):
    return ParsedThread(
        frontmatter={
            "publish": publish,
            "reply": reply,
            "resolve": resolve,
            "edit_notes": edit_notes or [],
        },
        reply=reply,
        note_edits=note_edits or {},
    )


def types(plan):
    return [type(a).__name__ for a in plan.actions]


def test_ready_reply_becomes_reply_action():
    plan = plan_thread(parsed(publish=True, reply="Thanks!"), thread())
    assert types(plan) == ["ReplyAction"]
    assert plan.actions[0].body == "Thanks!" and plan.actions[0].discussion_id == "d1"


def test_publish_true_empty_reply_warns():
    plan = plan_thread(parsed(publish=True, reply=""), thread())
    assert not plan.actions and plan.warnings


def test_marked_changed_edit_becomes_edit_action():
    plan = plan_thread(parsed(edit_notes=[2], note_edits={2: "new body"}), thread())
    assert types(plan) == ["EditAction"]
    a = plan.actions[0]
    assert a.note_id == "502" and a.note_local_id == 2 and a.body == "new body"


def test_marked_but_unchanged_edit_warns_no_action():
    plan = plan_thread(parsed(edit_notes=[2], note_edits={2: "canonical body"}), thread())
    assert not plan.actions and plan.warnings


def test_unmarked_divergent_edit_warns():
    plan = plan_thread(parsed(edit_notes=[], note_edits={2: "secretly changed"}), thread())
    assert not plan.actions
    assert any("note 2" in w.message for w in plan.warnings)


def test_edit_notes_referencing_non_mine_or_unknown_warns():
    plan = plan_thread(parsed(edit_notes=[1], note_edits={1: "x"}), thread())  # note 1 not mine
    assert not plan.actions and plan.warnings
    plan2 = plan_thread(parsed(edit_notes=[9], note_edits={}), thread())  # unknown handle
    assert not plan2.actions and plan2.warnings


def test_resolve_true_when_unresolved_adds_resolve_action():
    plan = plan_thread(parsed(resolve=True), thread(resolved=False))
    assert "ResolveAction" in types(plan)


def test_resolve_true_when_already_resolved_noop():
    plan = plan_thread(parsed(resolve=True), thread(resolved=True))
    assert "ResolveAction" not in types(plan)


def test_marked_edit_with_missing_block_warns():
    plan = plan_thread(parsed(edit_notes=[2], note_edits={}), thread())
    assert not plan.actions
    assert plan.warnings
