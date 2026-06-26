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
    t0 = data["threads"][0]
    assert t0["draft_state"] == "ready"
    assert t0["actions"][0]["type"] == "ReplyAction"
    assert t0["actions"][0]["body"] == "Ready reply."  # body is in --json
    assert "[reply ready]" in format_status(report)  # text shows a tag, not the body


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


def mine_only_disc():
    # a general (non-diff) thread whose only note is the current user's
    return Discussion(
        "dm",
        False,
        False,
        None,
        (Note("900", "me", True, False, "t", "t", "my own note", False, False),),
    )


def test_clean_when_no_drafts(tmp_path):
    synced(tmp_path)
    t0 = status_json(gather_status(tmp_path, "1"))["threads"][0]
    assert t0["draft_state"] == "clean"
    assert t0["actions"] == []


def test_wip_when_reply_present_but_not_marked(tmp_path):
    f = synced(tmp_path)
    f.write_text(
        f.read_text().rstrip() + "\nDraft in progress, not ready.\n"
    )  # publish stays false
    report = gather_status(tmp_path, "1")
    assert status_json(report)["threads"][0]["draft_state"] == "wip"
    assert "[draft: not ready]" in format_status(report)


def test_reviewers_excludes_current_user(tmp_path):
    # disc() has a "reviewer" note and a "me" note; current_user is "me"
    report = gather_status(synced(tmp_path) and tmp_path, "1")
    t0 = status_json(report)["threads"][0]
    assert t0["reviewers"] == ["reviewer"]
    assert "@reviewer" in format_status(report)


def test_reviewers_self_when_all_mine(tmp_path):
    sync(FakeForge(MR, [mine_only_disc()]), tmp_path, MergeRef(ref="1"), fake_git(), now="N")
    report = gather_status(tmp_path, "1")
    assert status_json(report)["threads"][0]["reviewers"] == []
    assert "(self)" in format_status(report)


def test_excerpt_is_first_note_truncated(tmp_path):
    long = "x" * 200
    d = Discussion(
        "dl",
        True,
        False,
        DiffPosition("a.py", "a.py", 1, None, "B", "S", "H", None, "text"),
        (Note("1", "reviewer", False, False, "t", "t", long, True, False),),
    )
    sync(FakeForge(MR, [d]), tmp_path, MergeRef(ref="1"), fake_git(), now="N")
    excerpt = status_json(gather_status(tmp_path, "1"))["threads"][0]["excerpt"]
    assert excerpt.endswith("…") and len(excerpt) <= 80


def test_note_count(tmp_path):
    synced(tmp_path)
    report = gather_status(tmp_path, "1")
    assert status_json(report)["threads"][0]["note_count"] == 2
    assert "2 notes" in format_status(report)


def test_warning_surfaced_for_unmarked_edit(tmp_path):
    f = synced(tmp_path)
    # edit my own note body (handle 2) WITHOUT listing it in edit_notes -> warning
    f.write_text(f.read_text().replace("canonical", "secretly changed"))
    report = gather_status(tmp_path, "1")
    t0 = status_json(report)["threads"][0]
    assert t0["warnings"]
    assert report.summary["warnings"] == 1


def test_summary_counts(tmp_path):
    f = synced(tmp_path)
    f.write_text(f.read_text().replace("publish: false", "publish: true").rstrip() + "\nyep\n")
    s = status_json(gather_status(tmp_path, "1"))["summary"]
    assert s == {"threads": 1, "unresolved": 1, "ready": 1, "wip": 0, "warnings": 0}


def test_json_is_additive(tmp_path):
    synced(tmp_path)
    data = status_json(gather_status(tmp_path, "1"))
    assert set(data) == {"mr", "summary", "filter", "threads"}
    t0 = data["threads"][0]
    for k in (
        "reviewers",
        "note_count",
        "excerpt",
        "draft_state",
        "actions",
        "warnings",
        "outdated",
    ):
        assert k in t0


def multi_forge():
    foo = Discussion(
        "a",
        True,
        False,
        DiffPosition("src/foo.py", "src/foo.py", 1, None, "B", "S", "H", None, "text"),
        (Note("1", "reviewer", False, False, "t", "t", "on foo", True, False),),
    )
    bar = Discussion(
        "b",
        True,
        True,  # resolved
        DiffPosition("src/bar.py", "src/bar.py", 2, None, "B", "S", "H", None, "text"),
        (Note("2", "reviewer", False, False, "t", "t", "on bar", True, True),),
    )
    gen = Discussion(
        "c",
        False,
        False,
        None,
        (Note("3", "reviewer", False, False, "t", "t", "general", False, False),),
    )
    return FakeForge(MR, [foo, bar, gen])


def synced_multi(tmp_path):
    sync(multi_forge(), tmp_path, MergeRef(ref="1"), fake_git(), now="N")


def test_filter_unresolved(tmp_path):
    synced_multi(tmp_path)
    report = gather_status(tmp_path, "1", unresolved=True)
    assert all(not t.resolved for t in report.threads)
    assert {t.local_id for t in report.threads} == {1, 3}  # foo + general (bar resolved)
    assert report.summary["threads"] == 2


def test_filter_file_excludes_general_and_other_files(tmp_path):
    synced_multi(tmp_path)
    report = gather_status(tmp_path, "1", file="src/foo.py")
    assert [t.file for t in report.threads] == ["src/foo.py"]
    assert report.filter == {"unresolved": False, "file": "src/foo.py"}


def test_filters_compose(tmp_path):
    synced_multi(tmp_path)
    # unresolved + file=bar -> bar is resolved, so empty
    report = gather_status(tmp_path, "1", unresolved=True, file="src/bar.py")
    assert report.threads == []
    assert report.summary["threads"] == 0


def test_unparseable_thread_marked_error(tmp_path):
    f = synced(tmp_path)
    f.write_text("not a valid thread file\n")  # no frontmatter -> parse_thread raises ParseError
    report = gather_status(tmp_path, "1")
    t0 = report.threads[0]
    assert t0.draft_state == "error"
    assert t0.warnings  # the parse error is surfaced as a warning
    assert report.summary["warnings"] == 1
