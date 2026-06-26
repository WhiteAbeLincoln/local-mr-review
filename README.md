# local-mr-review

Manage GitLab merge request review discussions **locally**, as editable Markdown files.

`mr-review` pulls the discussions on a merge request, writes each thread to a file
in a gitignored directory, and lets you (or an AI agent) draft replies and edits to
your own prior comments right in those files — then publishes them back to GitLab
with an explicit, marker-gated confirmation step.

It targets the **MR author** loop: responding to reviewer comments (reply / edit /
resolve), not creating new discussions. It's built to be the engine behind an AI
review-response skill — read review comments, triage them, fix the code, draft
responses, and push when ready.

## Why

Reviewing and responding to a busy MR through the web UI is slow and context-poor.
With `local-mr-review` the whole thread set is on disk next to the code:

- diff comments come with real code context (reconstructed from git) and a link to
  the actual file and line,
- you draft responses in your editor (or an agent drafts them) alongside the fix,
- nothing is posted until you flip a marker and confirm.

## Requirements

- **Python 3.14+** and [`uv`](https://docs.astral.sh/uv/)
- **`glab`** (the GitLab CLI), authenticated — `mr-review` shells out to it.
  A `GITLAB_TOKEN` in the environment is the simplest auth.
- **`git`** — diff context is read from git blobs, so run `mr-review` from inside
  the repository the MR belongs to.

## Install

Install as a global tool (provides the `mr-review` command):

```sh
uv tool install /path/to/local-mr-review
```

Or run it without installing, from anywhere inside your target repo:

```sh
uv run --project /path/to/local-mr-review mr-review <command> ...
```

For development in this repo, just `uv run mr-review ...` and `uv run pytest`.

## Quick start

Run these from inside the git repository whose MR you're reviewing:

```sh
# 1. Pull the MR's discussions into ./mr-review/<iid>/
mr-review sync 123          # or a branch name, or omit to use the current branch

# 2. Open the thread files, fix code, and draft responses (see below).

# 3. See what's drafted and marked ready — posts nothing.
mr-review status 123

# 4. Post everything marked ready, then re-sync.
mr-review publish 123       # add --dry-run first to preview the exact plan
```

`mr-review` writes everything under a gitignored `mr-review/` directory in your repo
root, so it never touches your project's own `.gitignore` or git history.

## Drafting responses

Each discussion thread is one Markdown file. The top is YAML frontmatter (the only
fields you edit); below it is a **published** region (regenerated from the server on
every sync — display only) and a **draft** region.

````markdown
---
thread: 2
file: src/foo.py
line: 42
resolvable: true
resolved: false
publish: false        # set true to post the reply drafted below
resolve: false        # set true to also resolve the thread on publish
edit_notes: []         # local note handles whose inline edit to publish, e.g. [1]
---

# src/foo.py · 42 · unresolved
[↗ open src/foo.py:42](../../src/foo.py#L42)

```diff
  41      x = 1
> 42      return x + bar()
  43
```

<!-- mr-review:published (display only — regenerated each sync) -->

### @reviewer · 2026-06-24T10:00:00Z · note 1
Why not use the helper here?

### @you · 2026-06-24T11:00:00Z · note 2
<!-- mr-review:note 2 -->
Good point, but the helper doesn't handle the null case.
<!-- mr-review:/note 2 -->

<!-- mr-review:draft — write your reply below this line -->
````

Three things you can stage, all gated by frontmatter:

- **Reply:** write your response under the `mr-review:draft` marker and set
  `publish: true`.
- **Edit your own prior comment:** edit the text inside its
  `<!-- mr-review:note N -->` … `<!-- mr-review:/note N -->` block and add `N` to
  `edit_notes`. (Only your own notes are wrapped for editing.)
- **Resolve:** set `resolve: true`. (Resolving is normally the reviewer's job, so
  use sparingly.)

Then `mr-review status` lists exactly what's ready, and `mr-review publish` posts it.
After a successful post, the corresponding draft is cleared from the file
automatically, so re-running `publish` never double-posts.

## Commands

| Command | What it does |
| --- | --- |
| `mr-review sync [<mr>] [-R <repo>]` | Fetch discussions; (re)render thread files, preserving your drafts and flagging upstream changes with `⚠`. |
| `mr-review status [<mr>] [-R <repo>] [--json]` | Read-only summary of threads and pending reply/edit/resolve actions. Posts nothing. `--json` for machine use. |
| `mr-review publish [<mr>] [-R <repo>] [--dry-run]` | Post everything marked ready, then re-sync. Non-interactive. `--dry-run` previews the plan. |

`<mr>` is a numeric IID, a branch name, or omitted (uses the current branch). A
numeric IID lets `status` run fully offline. `-R/--repo` overrides the target repo
(passed through to `glab`).

## How it works

- **Two layers.** A hidden `mr-review/.state/<iid>.json` holds the canonical server
  state (the source of truth); the Markdown files are an editable projection plus
  your local-only draft regions. The published region is regenerated each sync and
  **never parsed back** — so a reviewer's comment can contain anything (code fences,
  even our own markers) without ever corrupting a publish.
- **Stable local handles.** Files never contain forge-native ids. Each thread/note
  gets a small local handle (`thread: 2`, `note 1`) that the sidecar maps to the
  real id. Handles are reused across syncs and retired-never-reused when something
  is deleted upstream, so `edit_notes: [1]` always points at the same note.
- **Accurate diff context.** The ```diff block is read from the git blob at the
  comment's own commit SHA, so it shows exactly what the reviewer saw regardless of
  your working tree. (The clickable file link uses your working tree, so it's
  accurate when you're checked out at the MR's commit.)
- **Safe sync.** Your drafts are never clobbered. If a comment you're editing also
  changed upstream, sync keeps your edit and adds a `⚠` flag to reconcile.
- **Fail-loud publish.** Ambiguous edits are reported and skipped rather than
  guessed; per-item failures are isolated; the canonical state is rebuilt from the
  server after posting (writes are never trusted blind).

### Directory layout

```
mr-review/                 # gitignored (self-ignored via mr-review/.gitignore = "*")
  .gitignore
  123/                     # per MR, by IID
    001-src-foo.py-L42.md  # one editable file per discussion thread
    002-README.md-general.md
  .state/
    123.json               # canonical server state (never hand-edited)
```

## Architecture

Ports & adapters. A forge-neutral core (state, render, parse, plan, sync/status/
publish) depends only on a `Forge` protocol and neutral domain types; a single
`GitLabForge` adapter is the only code that knows about `glab`. Adding GitHub later
means implementing the same protocol — the core and file format don't change.

## Notes & caveats

- `mr-review` uses `glab`'s `mr note` subcommands, which GitLab flags as
  **experimental**. The read and write paths have been verified end-to-end against
  live MRs; if those subcommands ever change, each operation can be re-pointed at
  the stable `glab api` endpoints behind the adapter boundary.
- Scope is **author-responds-to-comments**. Creating new discussions, a GitHub
  adapter, an MR list/overview, and richer filtering are planned but not yet here —
  see `docs/superpowers/specs/` for the design and roadmap.

## Development

```sh
uv sync
uv run pytest          # test suite
uv run ruff check .    # lint
uv run ruff format .   # format
```

Design spec and implementation plan live in `docs/superpowers/`.
