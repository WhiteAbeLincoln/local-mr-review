from mr_review.domain import DiffPosition
from mr_review.git import GitError, GitRunner


def format_hunk(file_text: str, highlight_lines: set[int], around: int, radius: int = 3) -> str:
    lines = file_text.splitlines()
    lo = max(1, around - radius)
    hi = min(len(lines), around + radius)
    width = len(str(hi))
    rows = ["```diff"]
    for n in range(lo, hi + 1):
        marker = "> " if n in highlight_lines else "  "
        rows.append(f"{marker}{str(n).rjust(width)}  {lines[n - 1]}")
    rows.append("```")
    return "\n".join(rows)


def build_context(position: DiffPosition | None, git: GitRunner, radius: int = 3) -> str | None:
    if position is None or position.position_type != "text":
        return None
    if position.new_line is not None:
        sha, path, around = position.head_sha, position.new_path, position.new_line
    elif position.old_line is not None:
        sha, path, around = position.base_sha, position.old_path, position.old_line
    else:
        return None
    if not sha or not path:
        return None
    highlight = (
        set(range(position.line_range[0], position.line_range[1] + 1))
        if position.line_range
        else {around}
    )
    try:
        text = git.show(sha, path)
    except GitError:
        return None
    return format_hunk(text, highlight, around, radius)
