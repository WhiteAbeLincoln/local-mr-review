from pathlib import Path

from mr_review.forge.gitlab import GitLabForge
from mr_review.forge.glab import GlabRunner
from mr_review.git import GitRunner


def repo_root(cwd: Path, git: GitRunner) -> Path:
    return Path(git.toplevel())


def review_dir(root: Path) -> Path:
    return root / "mr-review"


def make_forge(name: str = "gitlab") -> GitLabForge:
    return GitLabForge(GlabRunner())
