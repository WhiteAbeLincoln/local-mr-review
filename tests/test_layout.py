from mr_review.domain import DiffPosition
from mr_review.layout import ensure_gitignore, line_label, slug_for, state_path, thread_path
from mr_review.markers import PUBLISHED_PREFIX, neutralize, note_open


def pos(new_line=None, old_line=None, line_range=None):
    return DiffPosition(
        new_path="src/foo.py",
        old_path="src/foo.py",
        new_line=new_line,
        old_line=old_line,
        base_sha="B",
        start_sha="S",
        head_sha="H",
        line_range=line_range,
        position_type="text",
    )


def test_line_label_variants():
    assert line_label(pos(new_line=42)) == "42"
    assert line_label(pos(old_line=7)) == "old:7"
    assert line_label(pos(new_line=10, line_range=(10, 15))) == "10-15"
    assert line_label(None) == "general"


def test_slug_includes_padded_handle_and_path():
    assert slug_for(1, pos(new_line=42)) == "001-src-foo.py-L42"
    assert slug_for(12, None) == "012-general"


def test_paths_are_under_review_dir(tmp_path):
    assert (
        thread_path(tmp_path, "1294", 1, pos(new_line=42))
        == tmp_path / "1294" / "001-src-foo.py-L42.md"
    )
    assert state_path(tmp_path, "1294") == tmp_path / ".state" / "1294.json"


def test_ensure_gitignore_writes_star_once(tmp_path):
    ensure_gitignore(tmp_path)
    gi = tmp_path / ".gitignore"
    assert gi.read_text() == "*\n"
    gi.write_text("custom\n")
    ensure_gitignore(tmp_path)  # idempotent: does not clobber existing
    assert gi.read_text() == "custom\n"


def test_slug_for_line_range_uses_underscore_separator():
    assert slug_for(5, pos(new_line=10, line_range=(10, 15))) == "005-src-foo.py-L10_15"


def test_neutralize_breaks_only_our_marker():
    out = neutralize(f"text {note_open(2)} more")
    assert note_open(2) not in out
    assert "text" in out and "more" in out


def test_neutralize_breaks_published_prefix():
    sample = f"{PUBLISHED_PREFIX} display -->"
    assert PUBLISHED_PREFIX not in neutralize(sample)
