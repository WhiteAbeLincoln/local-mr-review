from mr_review.diffcontext import build_context, format_hunk
from mr_review.domain import DiffPosition
from mr_review.git import GitRunner

FILE = "line1\nline2\nline3\nline4\nline5\nline6\n"


def test_format_hunk_marks_highlight_and_windows_around():
    block = format_hunk(FILE, highlight_lines={3}, around=3, radius=1)
    assert "```diff" in block
    assert "> " in block and "line3" in block
    assert "line1" not in block  # outside radius
    assert "line2" in block and "line4" in block


def fake_git(text):
    def exec_runner(args, input):
        return (0, text, "")

    return GitRunner(exec_runner=exec_runner)


def test_build_context_new_side_uses_head_sha_blob():
    pos = DiffPosition(
        new_path="f.py",
        old_path="f.py",
        new_line=3,
        old_line=None,
        base_sha="B",
        start_sha="S",
        head_sha="H",
        line_range=None,
        position_type="text",
    )
    block = build_context(pos, fake_git(FILE))
    assert "line3" in block and "> " in block


def test_build_context_returns_none_for_general_or_image():
    assert build_context(None, fake_git(FILE)) is None
    img = DiffPosition("f", "f", 1, None, "B", "S", "H", None, "image")
    assert build_context(img, fake_git(FILE)) is None


def test_build_context_handles_git_failure_gracefully():
    def boom(args, input):
        return (128, "", "fatal: bad object")

    pos = DiffPosition("f.py", "f.py", 3, None, "B", "S", "H", None, "text")
    assert build_context(pos, GitRunner(exec_runner=boom)) is None


def test_build_context_old_side_uses_base_sha_blob():
    calls = []

    def exec_runner(args, input):
        calls.append(args)
        return (0, FILE, "")

    git = GitRunner(exec_runner=exec_runner)
    pos = DiffPosition(
        new_path="f.py",
        old_path="f.py",
        new_line=None,
        old_line=3,
        base_sha="B",
        start_sha="S",
        head_sha="H",
        line_range=None,
        position_type="text",
    )
    block = build_context(pos, git)
    assert block is not None and "line3" in block
    # git show was asked for the BASE sha blob (old side), not head
    assert any("B:f.py" in " ".join(a) for a in calls)
    assert not any("H:f.py" in " ".join(a) for a in calls)


def test_build_context_highlights_full_line_range_span():
    pos = DiffPosition(
        new_path="f.py",
        old_path="f.py",
        new_line=3,
        old_line=None,
        base_sha="B",
        start_sha="S",
        head_sha="H",
        line_range=(2, 4),
        position_type="text",
    )
    block = build_context(pos, fake_git(FILE), radius=3)
    # lines 2,3,4 are all highlighted
    for n, text in [(2, "line2"), (3, "line3"), (4, "line4")]:
        assert any(line.startswith("> ") and text in line for line in block.splitlines())
