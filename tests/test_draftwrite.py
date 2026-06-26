import pytest

from mr_review import draftwrite
from mr_review.parse import parse_thread
from mr_review.render import RenderInputs, render_thread
from mr_review.store import StoredNote, StoredThread

POSITION = {
    "new_path": "src/foo.py",
    "old_path": "src/foo.py",
    "new_line": 42,
    "old_line": None,
    "base_sha": "B",
    "start_sha": "S",
    "head_sha": "H",
    "line_range": None,
    "position_type": "text",
}


def sample(*, reply="", publish=False, resolve=False, edit_notes=()):
    """A realistic thread file: reviewer note (handle 1) + own note (handle 2)."""
    thread = StoredThread(
        local_id=2,
        native_id="d1",
        resolvable=True,
        resolved=False,
        position=POSITION,
        notes=[
            StoredNote(1, "501", "reviewer", False, "t", "t", "Why not the helper?", True, False),
            StoredNote(2, "502", "me", True, "t", "t", "canonical", True, False),
        ],
    )
    return render_thread(
        RenderInputs(
            thread=thread,
            diff_block=None,
            reply_draft=reply,
            publish=publish,
            resolve=resolve,
            edit_notes=list(edit_notes),
            mr_head_sha="H",
        )
    )


def test_write_reply_sets_and_replaces_body():
    out = draftwrite.write_reply(sample(), "Good catch — fixed in abc123.")
    assert parse_thread(out).reply == "Good catch — fixed in abc123."
    # re-drafting replaces rather than appends
    out2 = draftwrite.write_reply(out, "Second take.")
    assert parse_thread(out2).reply == "Second take."
    assert "fixed in abc123" not in out2


def test_write_reply_neutralizes_embedded_markers():
    # a body that itself contains a draft marker must not break parsing
    body = "Compare:\n<!-- mr-review:draft — bogus -->\ndone"
    out = draftwrite.write_reply(sample(), body)
    parsed = parse_thread(out)  # must not raise "expected exactly one draft marker"
    assert "done" in parsed.reply


def test_write_note_edit_updates_body_and_edit_notes():
    out = draftwrite.write_note_edit(sample(), 2, "Revised wording.")
    parsed = parse_thread(out)
    assert parsed.note_edits[2] == "Revised wording."
    assert parsed.frontmatter["edit_notes"] == [2]


def test_write_note_edit_rejects_non_own_note():
    with pytest.raises(draftwrite.DraftError):
        draftwrite.write_note_edit(sample(), 1, "cannot edit reviewer note")


def test_set_flags_flips_publish_and_leaves_rest():
    out = draftwrite.set_flags(sample(reply="kept"), publish=True)
    parsed = parse_thread(out)
    assert parsed.frontmatter["publish"] is True
    assert parsed.frontmatter["resolve"] is False
    assert parsed.reply == "kept"


def test_omitted_flag_preserves_prior_value():
    out = draftwrite.set_flags(sample(publish=True), resolve=True)
    parsed = parse_thread(out)
    assert parsed.frontmatter["publish"] is True  # untouched
    assert parsed.frontmatter["resolve"] is True


def test_write_reply_can_also_set_publish():
    out = draftwrite.write_reply(sample(), "ship it", publish=True)
    assert parse_thread(out).frontmatter["publish"] is True
