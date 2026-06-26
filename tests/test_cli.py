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
