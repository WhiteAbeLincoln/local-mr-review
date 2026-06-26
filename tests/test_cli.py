from types import SimpleNamespace

from click.testing import CliRunner

from mr_review.cli import _resolve_iid
from mr_review.domain import DiffPosition, Discussion, MergeRef, MergeRequest, Note
from mr_review.layout import state_path, thread_path
from mr_review.parse import parse_thread
from mr_review.store import dict_to_position, load_state
from mr_review.sync import sync
from tests.fakes import FakeForge, fake_git

MR = MergeRequest("1", "t", "https://gitlab.com/g/r/-/merge_requests/1", "g/r", "B", "S", "H", "me")


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


def _setup(monkeypatch, tmp_path, *, do_sync=True):
    from mr_review import cli

    if do_sync:
        sync(FakeForge(MR, [_disc()]), tmp_path, MergeRef(ref="1"), fake_git(), now="N")
    monkeypatch.setattr(cli, "_context", lambda: tmp_path)
    monkeypatch.setattr(cli, "make_forge", lambda: object())
    return cli


def _thread_file(tmp_path, local_id):
    st = load_state(state_path(tmp_path, "1"))
    assert st is not None
    t = next(t for t in st.threads if t.local_id == local_id)
    return thread_path(tmp_path, "1", local_id, dict_to_position(t.position))


def test_draft_cli_writes_reply_and_sets_publish(monkeypatch, tmp_path):
    cli = _setup(monkeypatch, tmp_path)
    res = CliRunner().invoke(
        cli.main, ["draft", "1", "--thread", "1", "--publish"], input="Done, thanks.\n"
    )
    assert res.exit_code == 0, res.output
    parsed = parse_thread(_thread_file(tmp_path, 1).read_text())
    assert parsed.reply == "Done, thanks."
    assert parsed.frontmatter["publish"] is True


def test_reply_alias_works(monkeypatch, tmp_path):
    cli = _setup(monkeypatch, tmp_path)
    res = CliRunner().invoke(cli.main, ["reply", "1", "--thread", "1"], input="via alias\n")
    assert res.exit_code == 0, res.output
    assert parse_thread(_thread_file(tmp_path, 1).read_text()).reply == "via alias"


def test_draft_cli_edits_own_note(monkeypatch, tmp_path):
    cli = _setup(monkeypatch, tmp_path)
    res = CliRunner().invoke(
        cli.main, ["draft", "1", "--thread", "1", "--note", "2"], input="reworded\n"
    )
    assert res.exit_code == 0, res.output
    parsed = parse_thread(_thread_file(tmp_path, 1).read_text())
    assert parsed.note_edits[2] == "reworded"
    assert parsed.frontmatter["edit_notes"] == [2]


def test_mark_cli_flips_publish_only(monkeypatch, tmp_path):
    cli = _setup(monkeypatch, tmp_path)
    res = CliRunner().invoke(cli.main, ["mark", "1", "--thread", "1", "--publish"])
    assert res.exit_code == 0, res.output
    parsed = parse_thread(_thread_file(tmp_path, 1).read_text())
    assert parsed.frontmatter["publish"] is True
    assert parsed.reply == ""  # body untouched


def test_show_cli_dumps_full_content(monkeypatch, tmp_path):
    cli = _setup(monkeypatch, tmp_path)
    res = CliRunner().invoke(cli.main, ["show", "1"])
    assert res.exit_code == 0, res.output
    assert "Why?" in res.output  # full reviewer body, not an excerpt


def test_draft_missing_thread_fails(monkeypatch, tmp_path):
    cli = _setup(monkeypatch, tmp_path)
    res = CliRunner().invoke(cli.main, ["draft", "1", "--thread", "99"], input="x\n")
    assert res.exit_code != 0
    assert "99" in res.output


def test_draft_not_synced_fails(monkeypatch, tmp_path):
    cli = _setup(monkeypatch, tmp_path, do_sync=False)
    res = CliRunner().invoke(cli.main, ["draft", "1", "--thread", "1"], input="x\n")
    assert res.exit_code != 0
    assert "sync" in res.output.lower()


def test_draft_empty_stdin_fails(monkeypatch, tmp_path):
    cli = _setup(monkeypatch, tmp_path)
    res = CliRunner().invoke(cli.main, ["draft", "1", "--thread", "1"], input="")
    assert res.exit_code != 0


def test_draft_non_own_note_fails(monkeypatch, tmp_path):
    cli = _setup(monkeypatch, tmp_path)
    res = CliRunner().invoke(
        cli.main, ["draft", "1", "--thread", "1", "--note", "1"], input="nope\n"
    )
    assert res.exit_code != 0


def test_resolve_iid_numeric_skips_forge():
    class NoFetch:
        def fetch_mr(self, mr):
            raise AssertionError("numeric iid must not trigger a forge call")

    assert _resolve_iid(NoFetch(), "1294", None) == "1294"


def test_resolve_iid_branch_resolves_via_forge():
    calls = []

    class Fake:
        def fetch_mr(self, mr):
            calls.append(mr)
            return SimpleNamespace(iid="77")

    assert _resolve_iid(Fake(), "my-branch", None) == "77"
    assert calls, "branch ref must resolve via the forge"


def test_status_cli_passes_filters(monkeypatch, tmp_path):
    from mr_review import cli
    from mr_review.status import StatusReport

    captured = {}

    def fake_gather(review_dir, mr, *, unresolved=False, file=None, thread=None, full=False):
        captured.update(mr=mr, unresolved=unresolved, file=file, thread=thread, full=full)
        r = StatusReport(mr=mr)
        r.summary = {"threads": 0, "unresolved": 0, "ready": 0, "wip": 0, "warnings": 0}
        r.filter = {"unresolved": unresolved, "file": file}
        return r

    monkeypatch.setattr(cli, "_context", lambda: tmp_path)
    monkeypatch.setattr(cli, "make_forge", lambda: object())
    monkeypatch.setattr(cli.status_mod, "gather_status", fake_gather)

    res = CliRunner().invoke(cli.main, ["status", "7", "--unresolved", "--file", "src/x.py"])
    assert res.exit_code == 0, res.output
    assert captured == {
        "mr": "7",
        "unresolved": True,
        "file": "src/x.py",
        "thread": None,
        "full": False,
    }
