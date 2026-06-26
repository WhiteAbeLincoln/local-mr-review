# tests/test_sync.py
from mr_review.domain import DiffPosition, Discussion, MergeRef, MergeRequest, Note
from mr_review.parse import parse_thread
from mr_review.sync import sync
from tests.fakes import FakeForge, fake_git

MR = MergeRequest(
    iid="1",
    title="t",
    web_url="https://gitlab.com/g/r/-/merge_requests/1",
    project="g/r",
    base_sha="B",
    start_sha="S",
    head_sha="H",
    current_user="me",
)


def disc():
    pos = DiffPosition("src/foo.py", "src/foo.py", 42, None, "B", "S", "H", None, "text")
    return Discussion(
        "d1",
        True,
        False,
        pos,
        (
            Note("501", "reviewer", False, False, "t", "t", "Why not helper?", True, False),
            Note("502", "me", True, False, "t", "t", "canonical body", True, False),
        ),
    )


def test_sync_writes_thread_file_and_state(tmp_path):
    forge = FakeForge(MR, [disc()])
    result = sync(forge, tmp_path, MergeRef(ref="1"), fake_git("a\nb\nc\n" * 20), now="NOW")
    assert len(result.written) == 1
    f = result.written[0]
    assert f.exists() and f.suffix == ".md"
    assert (tmp_path / ".state" / "1.json").exists()
    assert (tmp_path / ".gitignore").read_text() == "*\n"


def test_resync_preserves_reply_draft(tmp_path):
    forge = FakeForge(MR, [disc()])
    f = sync(forge, tmp_path, MergeRef(ref="1"), fake_git(), now="NOW").written[0]
    text = f.read_text().rstrip() + "\nMy drafted reply.\n"
    f.write_text(text)
    sync(forge, tmp_path, MergeRef(ref="1"), fake_git(), now="NOW2")  # re-sync
    assert "My drafted reply." in f.read_text()


def outdated_disc():
    """A discussion whose position.head_sha differs from MR.head_sha ("H")."""
    pos = DiffPosition("src/bar.py", "src/bar.py", 7, None, "B", "S", "OLDSHA", None, "text")
    return Discussion(
        "d2",
        True,
        False,
        pos,
        (Note("601", "reviewer", False, False, "t", "t", "Old comment.", True, False),),
    )


def test_outdated_thread_frontmatter_and_warning(tmp_path):
    # When a discussion's position.head_sha differs from MR.head_sha, the
    # written file should have outdated: true in its frontmatter and contain
    # the ⚠ Outdated warning so reviewers know the linked line may have moved.
    forge = FakeForge(MR, [outdated_disc()])
    result = sync(forge, tmp_path, MergeRef(ref="1"), fake_git(), now="NOW")
    assert len(result.written) == 1
    text = result.written[0].read_text()
    import yaml

    _, fm_raw, _ = text.split("---\n", 2)
    fm = yaml.safe_load(fm_raw)
    assert fm["outdated"] is True
    assert "⚠ Outdated" in text
    assert "OLDSHA"[:8] in text
    assert MR.head_sha[:8] in text


def test_resync_preserves_inline_edit_and_flags_upstream_conflict(tmp_path):
    forge = FakeForge(MR, [disc()])
    f = sync(forge, tmp_path, MergeRef(ref="1"), fake_git(), now="NOW").written[0]
    # locally edit my note (handle 2)
    edited = f.read_text().replace("canonical body", "my local edit")
    f.write_text(edited)
    # upstream also changes that note's body
    changed = disc()
    new_notes = list(changed.notes)
    new_notes[1] = Note("502", "me", True, False, "t", "t2", "UPSTREAM CHANGED", True, False)
    forge2 = FakeForge(MR, [Discussion("d1", True, False, changed.position, tuple(new_notes))])
    sync(forge2, tmp_path, MergeRef(ref="1"), fake_git(), now="NOW2")
    out = f.read_text()
    assert "my local edit" in out  # local edit preserved, not clobbered
    assert "⚠" in out  # conflict flagged
    assert parse_thread(out).note_edits[2] == "my local edit"
