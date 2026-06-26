import re
from pathlib import Path

from mr_review.domain import DiffPosition


def line_label(position: DiffPosition | None) -> str:
    if position is None:
        return "general"
    if position.line_range:
        return f"{position.line_range[0]}-{position.line_range[1]}"
    if position.new_line is not None:
        return str(position.new_line)
    if position.old_line is not None:
        return f"old:{position.old_line}"
    return "general"


def _path_slug(position: DiffPosition | None) -> str:
    path = None if position is None else (position.new_path or position.old_path)
    if not path:
        return "general"
    return re.sub(r"[^A-Za-z0-9._-]", "-", path.replace("/", "-"))


def slug_for(local_id: int, position: DiffPosition | None) -> str:
    prefix = f"{local_id:03d}"
    if position is None:
        return f"{prefix}-general"
    label = line_label(position).replace("old:", "old").replace("-", "_")
    return f"{prefix}-{_path_slug(position)}-L{label}"


def thread_path(review_dir: Path, mr: str, local_id: int, position: DiffPosition | None) -> Path:
    return review_dir / mr / f"{slug_for(local_id, position)}.md"


def state_path(review_dir: Path, mr: str) -> Path:
    return review_dir / ".state" / f"{mr}.json"


def ensure_gitignore(review_dir: Path) -> None:
    review_dir.mkdir(parents=True, exist_ok=True)
    gi = review_dir / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n")
