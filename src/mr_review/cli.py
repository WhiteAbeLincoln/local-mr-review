import datetime as _dt
import json as _json
from pathlib import Path

import click

from mr_review import publish as publish_mod
from mr_review import status as status_mod
from mr_review import sync as sync_mod
from mr_review.config import make_forge, repo_root, review_dir
from mr_review.domain import MergeRef
from mr_review.git import GitRunner


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat()


def _context() -> Path:
    root = repo_root(Path.cwd(), GitRunner())
    return review_dir(root)


def _resolve_iid(forge, mr: str | None, repo: str | None) -> str:
    # A numeric <mr> is already the iid — no forge/network call needed.
    if mr is not None and mr.isdigit():
        return mr
    # A branch name or no argument (current branch) must be resolved via the forge.
    return forge.fetch_mr(MergeRef(ref=mr, repo=repo)).iid


@click.group()
def main() -> None:
    """Manage GitLab merge request reviews locally."""


@main.command()
@click.argument("mr", required=False)
@click.option("-R", "--repo", default=None, help="OWNER/REPO override passed to the forge.")
def sync(mr: str | None, repo: str | None) -> None:
    """Pull discussions into local thread files."""
    rdir = _context()
    forge = make_forge()
    result = sync_mod.sync(forge, rdir, MergeRef(ref=mr, repo=repo), GitRunner(), _now())
    click.echo(f"Synced {len(result.written)} threads; {len(result.conflicts)} conflict(s).")


@main.command()
@click.argument("mr", required=False)
@click.option("-R", "--repo", default=None, help="OWNER/REPO override passed to the forge.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.option("--unresolved", is_flag=True, help="Show only unresolved threads.")
@click.option("--file", "file", default=None, help="Show only threads on this source file path.")
def status(
    mr: str | None, repo: str | None, as_json: bool, unresolved: bool, file: str | None
) -> None:
    """Show drafted replies/edits and what is marked ready."""
    rdir = _context()
    forge = make_forge()
    mr_iid = _resolve_iid(forge, mr, repo)
    report = status_mod.gather_status(rdir, mr_iid, unresolved=unresolved, file=file)
    click.echo(
        _json.dumps(status_mod.status_json(report), indent=2)
        if as_json
        else status_mod.format_status(report)
    )


@main.command()
@click.argument("mr", required=False)
@click.option("-R", "--repo", default=None, help="OWNER/REPO override passed to the forge.")
@click.option("--dry-run", is_flag=True, help="Show the publish plan without posting.")
def publish(mr: str | None, repo: str | None, dry_run: bool) -> None:
    """Post ready replies/edits/resolves to GitLab."""
    rdir = _context()
    forge = make_forge()
    result = publish_mod.publish(
        forge, rdir, MergeRef(ref=mr, repo=repo), GitRunner(), _now(), dry_run=dry_run
    )
    verb = "Would post" if dry_run else "Posted"
    click.echo(f"{verb}: {len(result.posted)} item(s); {len(result.failed)} failed.")
    for name, err in result.failed:
        click.echo(f"  ✗ {name}: {err}")
