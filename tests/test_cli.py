from types import SimpleNamespace

from mr_review.cli import _resolve_iid


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

    def fake_gather(review_dir, mr, *, unresolved=False, file=None):
        captured.update(mr=mr, unresolved=unresolved, file=file)
        r = StatusReport(mr=mr)
        r.summary = {"threads": 0, "unresolved": 0, "ready": 0, "wip": 0, "warnings": 0}
        r.filter = {"unresolved": unresolved, "file": file}
        return r

    monkeypatch.setattr(cli, "_context", lambda: tmp_path)
    monkeypatch.setattr(cli, "make_forge", lambda: object())
    monkeypatch.setattr(cli.status_mod, "gather_status", fake_gather)

    from click.testing import CliRunner

    res = CliRunner().invoke(cli.main, ["status", "7", "--unresolved", "--file", "src/x.py"])
    assert res.exit_code == 0, res.output
    assert captured == {"mr": "7", "unresolved": True, "file": "src/x.py"}
