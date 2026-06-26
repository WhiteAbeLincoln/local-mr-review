import datetime as _dt
import json as _json
from pathlib import Path

import click

from mr_review import draftwrite
from mr_review import publish as publish_mod
from mr_review import status as status_mod
from mr_review import sync as sync_mod
from mr_review.config import make_forge, repo_root, review_dir
from mr_review.domain import MergeRef
from mr_review.git import GitRunner
from mr_review.layout import state_path, thread_path
from mr_review.store import dict_to_position, load_state


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


def _run_status(
    mr: str | None,
    repo: str | None,
    as_json: bool,
    unresolved: bool,
    file: str | None,
    thread: int | None,
    full: bool,
) -> None:
    rdir = _context()
    forge = make_forge()
    mr_iid = _resolve_iid(forge, mr, repo)
    report = status_mod.gather_status(
        rdir, mr_iid, unresolved=unresolved, file=file, thread=thread, full=full
    )
    click.echo(
        _json.dumps(status_mod.status_json(report), indent=2)
        if as_json
        else status_mod.format_status(report)
    )


@main.command()
@click.argument("mr", required=False)
@click.option("-R", "--repo", default=None, help="OWNER/REPO override passed to the forge.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.option("--unresolved", is_flag=True, help="Show only unresolved threads.")
@click.option("--file", "file", default=None, help="Show only threads on this source file path.")
@click.option("--thread", "thread", type=int, default=None, help="Show only this thread handle.")
@click.option("--full", is_flag=True, help="Include full note bodies, diff, and current draft.")
def status(
    mr: str | None,
    repo: str | None,
    as_json: bool,
    unresolved: bool,
    file: str | None,
    thread: int | None,
    full: bool,
) -> None:
    """Show drafted replies/edits and what is marked ready."""
    _run_status(mr, repo, as_json, unresolved, file, thread, full)


@main.command()
@click.argument("mr", required=False)
@click.option("-R", "--repo", default=None, help="OWNER/REPO override passed to the forge.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.option("--unresolved", is_flag=True, help="Show only unresolved threads.")
@click.option("--file", "file", default=None, help="Show only threads on this source file path.")
@click.option("--thread", "thread", type=int, default=None, help="Show only this thread handle.")
def show(
    mr: str | None,
    repo: str | None,
    as_json: bool,
    unresolved: bool,
    file: str | None,
    thread: int | None,
) -> None:
    """Print full thread content (bodies, diff, current draft). Alias for `status --full`."""
    _run_status(mr, repo, as_json, unresolved, file, thread, full=True)


def _locate_thread_file(mr: str | None, repo: str | None, thread: int) -> Path:
    rdir = _context()
    forge = make_forge()
    mr_iid = _resolve_iid(forge, mr, repo)
    state = load_state(state_path(rdir, mr_iid))
    if state is None:
        raise click.ClickException(f"MR !{mr_iid} not synced — run 'mr-review sync {mr_iid}' first")
    match = next((t for t in state.threads if t.local_id == thread), None)
    if match is None:
        raise click.ClickException(f"thread {thread} not found in MR !{mr_iid}")
    path = thread_path(rdir, mr_iid, match.local_id, dict_to_position(match.position))
    if not path.exists():
        raise click.ClickException(f"MR !{mr_iid} not synced — run 'mr-review sync {mr_iid}' first")
    return path


@main.command()
@click.argument("mr", required=False)
@click.option("--thread", "thread", type=int, required=True, help="Thread handle to draft on.")
@click.option(
    "--note", "note", type=int, default=None, help="Edit your own note N instead of replying."
)
@click.option("--publish/--no-publish", "publish", default=None, help="Set the publish flag.")
@click.option("--resolve/--no-resolve", "resolve", default=None, help="Set the resolve flag.")
@click.option("-R", "--repo", default=None, help="OWNER/REPO override passed to the forge.")
def draft(
    mr: str | None,
    thread: int,
    note: int | None,
    publish: bool | None,
    resolve: bool | None,
    repo: str | None,
) -> None:
    """Draft a reply (or, with --note, edit your own note). Body is read from stdin."""
    path = _locate_thread_file(mr, repo, thread)
    body = click.get_text_stream("stdin").read()
    if not body.strip():
        raise click.ClickException(
            "no body on stdin — pipe the reply/edit text in, or use 'mark' to change only flags"
        )
    text = path.read_text()
    try:
        if note is None:
            new_text = draftwrite.write_reply(text, body, publish=publish, resolve=resolve)
        else:
            new_text = draftwrite.write_note_edit(
                text, note, body, publish=publish, resolve=resolve
            )
    except draftwrite.DraftError as e:
        raise click.ClickException(str(e)) from e
    path.write_text(new_text)
    what = "reply" if note is None else f"edit to note {note}"
    click.echo(f"Drafted {what} on thread {thread}.")


@main.command()
@click.argument("mr", required=False)
@click.option("--thread", "thread", type=int, required=True, help="Thread handle to mark.")
@click.option("--publish/--no-publish", "publish", default=None, help="Set the publish flag.")
@click.option("--resolve/--no-resolve", "resolve", default=None, help="Set the resolve flag.")
@click.option("-R", "--repo", default=None, help="OWNER/REPO override passed to the forge.")
def mark(
    mr: str | None,
    thread: int,
    publish: bool | None,
    resolve: bool | None,
    repo: str | None,
) -> None:
    """Flip publish/resolve flags on a thread without changing the body."""
    if publish is None and resolve is None:
        raise click.ClickException(
            "nothing to mark — pass --publish/--no-publish or --resolve/--no-resolve"
        )
    path = _locate_thread_file(mr, repo, thread)
    try:
        new_text = draftwrite.set_flags(path.read_text(), publish=publish, resolve=resolve)
    except draftwrite.DraftError as e:
        raise click.ClickException(str(e)) from e
    path.write_text(new_text)
    click.echo(f"Marked thread {thread}.")


main.add_command(draft, name="reply")


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
