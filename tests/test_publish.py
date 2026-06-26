# tests/test_publish.py
from mr_review.domain import DiffPosition, Discussion, MergeRef, MergeRequest, Note
from mr_review.publish import publish
from mr_review.sync import sync
from tests.fakes import FakeForge, fake_git

MR = MergeRequest("1", "t", "https://gitlab.com/g/r/-/merge_requests/1", "g/r", "B", "S", "H", "me")


def disc():
    pos = DiffPosition("src/foo.py", "src/foo.py", 42, None, "B", "S", "H", None, "text")
    return Discussion(
        "d1",
        True,
        False,
        pos,
        (
            Note("501", "reviewer", False, False, "t", "t", "Why?", True, False),
            Note("502", "me", True, False, "t", "t", "canonical", True, False),
        ),
    )


def setup_ready_reply(tmp_path):
    forge = FakeForge(MR, [disc()])
    f = sync(forge, tmp_path, MergeRef(ref="1"), fake_git(), now="N").written[0]
    text = f.read_text().replace("publish: false", "publish: true").rstrip() + "\nThanks, fixed.\n"
    f.write_text(text)
    return forge, f


def test_dry_run_posts_nothing(tmp_path):
    forge, _ = setup_ready_reply(tmp_path)
    result = publish(forge, tmp_path, MergeRef(ref="1"), fake_git(), now="N2", dry_run=True)
    assert result.dry_run
    assert forge.calls == []  # dry-run must post nothing of any kind


def test_publish_posts_reply_and_clears_draft(tmp_path):
    forge, f = setup_ready_reply(tmp_path)
    publish(forge, tmp_path, MergeRef(ref="1"), fake_git(), now="N2")
    assert ("reply", "d1", "Thanks, fixed.") in forge.calls
    # draft cleared: publish back to false, reply text gone
    from mr_review.parse import parse_thread

    parsed = parse_thread(f.read_text())
    assert parsed.frontmatter["publish"] is False
    assert parsed.reply == ""


def test_publish_resolve_calls_forge(tmp_path):
    forge = FakeForge(MR, [disc()])
    f = sync(forge, tmp_path, MergeRef(ref="1"), fake_git(), now="N").written[0]
    f.write_text(f.read_text().replace("resolve: false", "resolve: true"))
    publish(forge, tmp_path, MergeRef(ref="1"), fake_git(), now="N2")
    assert ("resolve", "d1", True) in forge.calls


def test_publish_edit_no_spurious_conflict(tmp_path):
    """After publishing an inline edit, the re-sync must not flag the edit as a conflict."""
    from mr_review.parse import parse_thread

    forge = FakeForge(MR, [disc()])
    f = sync(forge, tmp_path, MergeRef(ref="1"), fake_git(), now="N").written[0]

    # Inline-edit the author's own note (handle 2, native "502") and mark it for edit.
    # disc() has the note body "canonical" — replace it inside the note markers.
    edited = f.read_text().replace("canonical", "my revised body")
    edited = edited.replace("edit_notes: []", "edit_notes: [2]")
    f.write_text(edited)

    publish(forge, tmp_path, MergeRef(ref="1"), fake_git(), now="N2")

    # 1. The edit was sent to the forge.
    assert ("edit", "d1", "502", "my revised body") in forge.calls

    # 2. After publish, handle 2 is no longer in edit_notes.
    assert parse_thread(f.read_text()).frontmatter["edit_notes"] == []

    # 3. No conflict marker — this is the key assertion that catches the Fix 1 bug.
    assert "⚠" not in f.read_text()

    # 4. The edited body is present in the re-rendered file.
    assert "my revised body" in f.read_text()
