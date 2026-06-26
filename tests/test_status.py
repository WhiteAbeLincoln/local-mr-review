from mr_review.domain import DiffPosition, Discussion, MergeRef, MergeRequest, Note
from mr_review.status import format_status, gather_status, status_json
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


def synced(tmp_path):
    f = sync(FakeForge(MR, [disc()]), tmp_path, MergeRef(ref="1"), fake_git(), now="N").written[0]
    return f


def test_status_reports_pending_reply(tmp_path):
    f = synced(tmp_path)
    text = f.read_text().replace("publish: false", "publish: true").rstrip() + "\nReady reply.\n"
    f.write_text(text)
    report = gather_status(tmp_path, "1")
    data = status_json(report)
    assert data["threads"][0]["actions"][0]["type"] == "ReplyAction"
    assert "Ready reply" in format_status(report)


def test_status_reports_nothing_when_no_drafts(tmp_path):
    synced(tmp_path)
    report = gather_status(tmp_path, "1")
    assert status_json(report)["threads"][0]["actions"] == []


def outdated_mr():
    return MergeRequest(
        "2", "t2", "https://gitlab.com/g/r/-/merge_requests/2", "g/r", "B", "S", "CURRENTSHA", "me"
    )


def outdated_disc():
    pos = DiffPosition("src/baz.py", "src/baz.py", 5, None, "B", "S", "OLDSHA", None, "text")
    return Discussion(
        "d3",
        True,
        False,
        pos,
        (Note("701", "reviewer", False, False, "t", "t", "Stale.", True, False),),
    )


def test_status_marks_outdated_thread(tmp_path):
    # After syncing a thread whose position.head_sha differs from MR.head_sha,
    # gather_status should report outdated=True and format_status should mention it.
    mr = outdated_mr()
    forge = FakeForge(mr, [outdated_disc()])
    sync(forge, tmp_path, MergeRef(ref="2"), fake_git(), now="N")
    report = gather_status(tmp_path, "2")
    assert len(report.threads) == 1
    ts = report.threads[0]
    assert ts.outdated is True
    assert "outdated" in format_status(report)
