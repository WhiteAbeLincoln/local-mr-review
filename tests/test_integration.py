# tests/test_integration.py
from mr_review import draftwrite
from mr_review.domain import DiffPosition, Discussion, MergeRef, MergeRequest, Note
from mr_review.parse import parse_thread
from mr_review.publish import publish
from mr_review.status import gather_status, status_json
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
        (Note("501", "reviewer", False, False, "t", "t", "Why not the helper?", True, False),),
    )


def test_full_round_trip(tmp_path):
    forge = FakeForge(MR, [disc()])
    ref = MergeRef(ref="1")

    # 1. sync creates the thread file
    f = sync(forge, tmp_path, ref, fake_git("x\n" * 60), now="N1").written[0]
    assert "Why not the helper?" in f.read_text()

    # 2. draft a reply and mark ready
    f.write_text(
        f.read_text().replace("publish: false", "publish: true").rstrip() + "\nFixed in def456.\n"
    )

    # 3. status shows it ready
    report = status_json(gather_status(tmp_path, "1"))
    assert report["threads"][0]["actions"][0]["type"] == "ReplyAction"

    # 4. publish posts it and clears the draft
    publish(forge, tmp_path, ref, fake_git(), now="N2")
    assert ("reply", "d1", "Fixed in def456.") in forge.calls
    assert parse_thread(f.read_text()).frontmatter["publish"] is False

    # 5. status is now clean
    report2 = status_json(gather_status(tmp_path, "1"))
    assert report2["threads"][0]["actions"] == []


_MR = MergeRequest(
    "1", "t", "https://gitlab.com/g/r/-/merge_requests/1", "g/r", "B", "S", "H", "me"
)


def _disc():
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


def test_draft_then_sync_is_stable(tmp_path):
    # A drafted-and-marked file must be a fixed point under the next sync:
    # the draft is preserved AND the file is not reformatted (frontmatter order,
    # spacing, trailing newline all match what render produces).
    f = sync(FakeForge(_MR, [_disc()]), tmp_path, MergeRef(ref="1"), fake_git(), now="N").written[0]
    f.write_text(draftwrite.write_reply(f.read_text(), "Fixed, thanks.", publish=True))
    before = f.read_text()
    sync(FakeForge(_MR, [_disc()]), tmp_path, MergeRef(ref="1"), fake_git(), now="N")
    assert f.read_text() == before
