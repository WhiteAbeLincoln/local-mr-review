import yaml

from mr_review.markers import DRAFT_PREFIX, PUBLISHED_PREFIX, note_open
from mr_review.render import RenderInputs, render_thread
from mr_review.store import StoredNote, StoredThread


def thread():
    return StoredThread(
        local_id=1,
        native_id="d1",
        resolvable=True,
        resolved=False,
        position={
            "new_path": "src/foo.py",
            "new_line": 42,
            "old_path": "src/foo.py",
            "old_line": None,
            "base_sha": "B",
            "start_sha": "S",
            "head_sha": "H",
            "line_range": None,
            "position_type": "text",
        },
        notes=[
            StoredNote(
                1,
                "501",
                "reviewer",
                False,
                "2026-06-24T10:00:00Z",
                "2026-06-24T10:00:00Z",
                "Why not the helper?",
                True,
                False,
            ),
            StoredNote(
                2,
                "502",
                "me",
                True,
                "2026-06-24T11:00:00Z",
                "2026-06-24T11:00:00Z",
                "Handles null though.",
                True,
                False,
            ),
        ],
        retired_note_handles=[],
    )


def base_inputs(**kw):
    defaults = dict(
        thread=thread(),
        diff_block="```diff\n> 42  x\n```",
        reply_draft="",
        publish=False,
        resolve=False,
        edit_notes=[],
        note_overrides={},
        conflicts=set(),
        mr_head_sha="",
    )
    defaults.update(kw)
    return RenderInputs(**defaults)


def split_frontmatter(text):
    _, fm, _ = text.split("---\n", 2)
    return yaml.safe_load(fm)


def test_frontmatter_carries_control_fields():
    fm = split_frontmatter(render_thread(base_inputs(publish=True, edit_notes=[2])))
    assert fm["thread"] == 1 and fm["file"] == "src/foo.py" and fm["line"] == 42
    assert fm["publish"] is True and fm["edit_notes"] == [2]
    assert fm["resolvable"] is True and fm["resolved"] is False


def test_only_mine_notes_are_wrapped_for_editing():
    out = render_thread(base_inputs())
    assert note_open(2) in out  # my note editable
    assert note_open(1) not in out  # reviewer note not wrapped
    assert "Why not the helper?" in out


def test_note_override_replaces_my_body():
    out = render_thread(base_inputs(note_overrides={2: "My revised reply."}))
    assert "My revised reply." in out
    assert "Handles null though." not in out


def test_published_and_draft_markers_and_reply_present():
    out = render_thread(base_inputs(reply_draft="Thanks, fixed."))
    assert PUBLISHED_PREFIX in out and DRAFT_PREFIX in out
    assert out.index(PUBLISHED_PREFIX) < out.index(DRAFT_PREFIX)
    assert out.rstrip().endswith("Thanks, fixed.")


def test_conflict_flag_rendered():
    out = render_thread(base_inputs(conflicts={2}))
    assert "⚠" in out


def test_marker_in_body_is_neutralized():
    t = thread()
    t.notes[0] = StoredNote(
        1, "501", "reviewer", False, "t", "t", f"sneaky {note_open(2)}", True, False
    )
    out = render_thread(base_inputs(thread=t))
    # the only real occurrences of note_open(2) wrap my own note, not the reviewer body
    assert out.count(note_open(2)) == 1  # opening marker wraps my note


def test_outdated_position_flagged():
    # A thread whose position.head_sha differs from the current MR head should
    # show outdated: true in the frontmatter and a visible warning line in the body.
    out = render_thread(base_inputs(mr_head_sha="NEWHEAD00"))
    fm = split_frontmatter(out)
    assert fm["outdated"] is True
    assert "⚠ Outdated" in out
    assert "OLDSHA" not in out  # the thread fixture uses "H" not "OLDSHA"
    # verify the short SHAs appear in the warning
    assert "H" in out  # pos head_sha is "H" (from thread() fixture)
    assert "NEWHEAD0" in out  # first 8 chars of "NEWHEAD00"


def test_current_position_not_flagged():
    # When mr_head_sha matches the position's head_sha, the thread is current.
    out = render_thread(base_inputs(mr_head_sha="H"))
    fm = split_frontmatter(out)
    assert fm["outdated"] is False
    assert "⚠ Outdated" not in out
