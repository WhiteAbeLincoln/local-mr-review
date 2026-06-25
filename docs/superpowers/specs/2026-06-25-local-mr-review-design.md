# local-mr-review — Design

**Status:** approved (brainstorming)
**Date:** 2026-06-25

## Overview

A CLI tool to manage GitLab merge request reviews **locally** as a set of
editable files. It pulls the discussions on a merge request, writes each
discussion thread to a file in a gitignored directory, and lets the user (or an
AI agent) draft replies and edits to prior comments in those same files, then
publish them back to GitLab with explicit confirmation.

The tool targets the **MR author** use case: responding to reviewer
comments/discussions, not creating new ones. It is designed to be the core of a
future AI agent skill — read review comments, triage by nuance/difficulty, fix
the code, draft responses, and push changes plus comments when ready.

## Goals

- Pull discussions for a merge request via the `glab` CLI (`glab api`).
- Save each discussion thread as one markdown file in a gitignored directory.
- For diff comments, include code context and a link to the real local
  file/line (assume the same repo, checked out at the correct commit).
- Provide a manual `sync` step to pull in new reviews, comments, and edits.
- Allow drafting replies in the thread file.
- Allow drafting edits to one's own prior comments in the thread file.
- Publish replies and edits, gated by explicit in-file "ready" markers, with a
  separate read-only command for an agent/human to confirm before posting.
- Architect so the merge-request backend (forge) is pluggable — GitLab now,
  GitHub or others later.

## Non-goals (for v1)

- Creating new discussions / starting reviews (author responds only).
- Resolving is supported but de-emphasized (normally the reviewer's job).
- Interactive TTY prompts during publish (an agent can't drive them).
- A plugin registry / entry-point system for forges (just a factory + seam).
- A `list` command for browsing MRs (possible later).

## Workflow

1. `mr-review sync` — pull the MR's discussions into thread files.
2. The author/agent reads threads, fixes code as needed, and drafts replies
   (and optionally edits to their own prior comments) directly in the files,
   flipping per-thread "ready" markers in the frontmatter.
3. `mr-review status` — read-only summary of what is drafted and marked ready.
   This is the surface an agent shows the user to get confirmation in
   conversation (an agent cannot drive an interactive CLI).
4. After confirmation, `mr-review publish` posts only the ready items,
   non-interactively, and re-syncs the affected threads.

## Architecture — ports & adapters (hexagonal)

The core (sync / render / parse / plan / publish) depends only on a
forge-neutral **domain model** and a **`Forge` port**. A `GitLabForge` adapter
is the *only* code that knows about `glab`, GitLab's JSON shapes, and GitLab's
native id formats. A future `GitHubForge` implements the same port (PR review
*threads* ≈ discussions; `resolveReviewThread` GraphQL for resolve) and nothing
in the core changes.

Forge selection is a small factory keyed on the `forge` field stored in the
sidecar (default `gitlab`). No plugin registry yet — just the seam.

### Domain model (`domain.py`)

Frozen dataclasses, forge-neutral. **Every id is an opaque `str`** — never
assumed numeric, never parsed by the core.

- `MergeRef` — how to address an MR for the forge (e.g. project + iid/number,
  or a branch/ref to resolve).
- `MergeRequest` — `title`, `web_url`, `base_sha`, `start_sha`, `head_sha`,
  `current_user`.
- `Discussion` — `native_id`, `resolvable`, `resolved` (both derived from the
  notes — GitLab tracks resolution per-note), `position` (`DiffPosition | None`),
  `notes: list[Note]`.
- `Note` — `native_id`, `author`, `mine: bool`, `system: bool`, `created_at`,
  `updated_at`, `body`.
- `DiffPosition` — `old_path`, `new_path`, `old_line`, `new_line`, `line_range`
  (multi-line), plus the diff SHAs.

### Forge port (`forge/base.py`)

```python
class Forge(Protocol):
    def resolve_mr(self, ref: str | None) -> MergeRef        # ref or current branch
    def fetch_mr(self, mr: MergeRef) -> MergeRequest          # title, shas, web_url, current_user
    def list_discussions(self, mr: MergeRef) -> list[Discussion]
    def reply(self, mr: MergeRef, discussion_id: str, body: str) -> None
    def edit_note(self, mr: MergeRef, discussion_id: str, note_id: str, body: str) -> None
    def set_resolved(self, mr: MergeRef, discussion_id: str, resolved: bool) -> None
```

Write methods return `None`: `glab mr note create/update`'s output format is
EXPERIMENTAL and unverified, so publish does not parse it. Instead, after
posting, publish re-runs `list_discussions` to rebuild canonical state (the new
reply simply receives the next free local handle). This keeps writes robust
against the experimental output and is the source of the "transactional" /
re-sync behaviour described under Publish semantics.

Because the tool only *responds* (never creates discussions), the adapter never
needs to construct diff positions — replies/edits take only a body, and resolve
takes a boolean. This keeps the adapter small.

### GitLab adapter (`forge/gitlab.py`, `forge/glab.py`)

Shells out to `glab` (authenticated via `GITLAB_TOKEN`). The high-level
`glab mr note` subcommands cover the whole port and are markedly easier than
constructing raw `glab api` POST/PUT calls, so they are the primary path. Port →
`glab` mapping:

| Port method | `glab` invocation |
|---|---|
| `list_discussions` | `glab mr note list <mr> -F json` (`--type`, `--state`, `--file` filters available) |
| `reply` | `glab mr note create <mr> --reply <discussion-id> -m <body>` |
| `edit_note` | `glab mr note update <mr> <note-id> -m <body>` |
| `set_resolved(true)` | `glab mr note resolve <discussion-id> <mr>` |
| `set_resolved(false)` | `glab mr note reopen <discussion-id> <mr>` |
| `fetch_mr` | `glab mr view <ref> -F json` → title, web_url, `diff_refs` (base/start/head sha), author |

Comment bodies are passed via **stdin** (which `glab mr note create/update`
accept) to avoid shell-escaping and multiline issues. The one genuinely raw
call is the current user for `mine` detection: `glab api user` → `.username`,
compared to each note's `author.username` (no clean `glab mr note` equivalent).

**Verified against MR !1294 (2026-06-25).** `glab mr note list -F json` returns
the **complete raw GitLab discussions payload** and paginates internally (36
discussions / 39 notes in one array). Confirmed present: discussion `id` (hex),
per-note `id`, `author.username`, `created_at`/`updated_at`, `system`,
`resolvable`/`resolved`, and the full `position`
(`base_sha`/`start_sha`/`head_sha`, `new_path`/`new_line`, `old_path`/`old_line`,
`position_type`, `line_range`). `glab mr view <ref> -F json` returns `title`,
`web_url`, `sha`, branches, and `diff_refs`. So **reads need no raw `glab api`**
beyond the current-user call.

Findings folded into the design:

- **Thread resolved/resolvable is derived from notes, not the discussion.** The
  discussion object has only `id`, `individual_note`, `notes`. The adapter
  computes `resolvable = any(note.resolvable)` and
  `resolved = all(note.resolved for resolvable notes)`.
- Note `type` is `"DiffNote"` or `""`; `position` is `null` for non-diff notes;
  `position_type` is `"text"` or `null` (the adapter must also tolerate
  `"image"`, which we render as a non-diff/general thread — no code context).
- `author.username` on the MR view is the *MR author*, not the viewer, so `mine`
  detection still uses `glab api user`.

**Write path verified against a live test MR (2026-06-26).** A full
draft→publish cycle on a personal test MR confirmed all three writes work:
`reply` (`glab mr note create <mr> --reply <discussion-id>`), `edit_note`, and
`set_resolved`. Two corrections came out of it:

- **Arg order:** `glab mr note update` and `resolve`/`reopen` take the **MR ref
  before** the id (`update <mr> <note-id>`, `resolve <mr> <discussion-id>`).
  glab's help USAGE line lists the id first, which is misleading — passing the
  id first makes glab read it as the MR and fail. Tests now pin the exact order.
- Transactional publish, per-item failure isolation, and the safe-merge
  preservation of a *failed* edit's local body (no spurious conflict) were all
  exercised live during the partial-failure on the first attempt.

**Residual risk, isolated by the adapter boundary:** `glab mr note` subcommands
are flagged EXPERIMENTAL and could change. If so, each port method can be
re-pointed at the equivalent stable `glab api` endpoint (`.../discussions`,
`.../discussions/:id/notes`, `?resolved=`) without touching the core.

`system: true` notes (e.g. "changed this line", "resolved the thread") are
filtered out of the rendered thread — they are noise for responding. Resolved
state comes from `discussion.resolved`, not from system notes.
`individual_note: true` standalone comments are treated as single-note,
non-resolvable threads.

## Directory layout

Gitignored, with the canonical JSON state tucked into a single hidden directory
so the markdown editing surface stays clean (no JSON siblings in the editor
file tree):

```
mr-review/                         # visible root — the editing area
  .gitignore                       # contains a single "*" — self-ignores the whole dir
  123/                             # per MR, by iid/number
    001-src-foo.py-L42.md          # one file per discussion thread
    002-README.md-general.md
  .state/                          # the single hidden dir — canonical JSON
    123.json                       # MR meta + sync time + all thread canonical state
```

On first `sync`, the tool writes `mr-review/.gitignore` containing `*`. This
self-ignores the entire tool directory (git still reads the file; nothing inside
is ever tracked) and leaves the project's own `.gitignore` untouched.

## ID handling — local handles in files, native ids in the sidecar

The thread file **never** contains a forge-native id. It uses small, stable
**local handles**; the sidecar maps handle ↔ native id. This keeps the file
format forge-neutral (GitLab hex discussion ids and integer note ids, GitHub
opaque GraphQL node ids, etc. all reduce to `thread: 1` and `note 2`) and
de-clunks `edit_notes` (small integers, not opaque strings).

**Display order vs handle assignment are separate concerns:**

- **Display order:** notes/threads sorted by `created_at`, tiebroken by native
  id. New notes append at the bottom; fully deterministic.
- **Handle assignment:** comes from the persisted sidecar mapping, *not*
  recomputed position. On each sync, for every native id: if already in the
  sidecar, reuse its stored handle; if new, assign `max(seen) + 1`. Deleted
  items keep their handle **retired — never reused**.

This guarantees `note 2` / `edit_notes: [2]` always point at the same
underlying note across syncs, even when upstream notes are deleted or inserted.
If a referenced note disappears upstream, `status` warns rather than
retargeting. Newly published replies receive the next free handle once their
native id returns from the forge.

## Thread file format

The markdown file is a **projection** of canonical state plus local-only draft
regions. The published region is regenerated from the sidecar on every sync and
is **display-only — never parsed back**. Canonical JSON is the source of truth
for every published comment body.

````markdown
---
mr: 123
thread: 1
file: src/foo.py
line: 42                  # human-friendly; precise position lives in the sidecar
resolvable: true
resolved: false
# ---- the only fields you edit ----
publish: false           # post the drafted reply below
resolve: false           # also resolve the thread on publish
edit_notes: []           # local note handles whose inline edit to publish, e.g. [2]
---

# src/foo.py:42 · unresolved
[↗ open src/foo.py:42](../../src/foo.py#L42)

```diff
  40  def foo():
  41      x = 1
> 42      return x + bar()
  43
```

<!-- mr-review:published (display only — regenerated each sync) -->

### @reviewer1 · 2026-06-24 10:00
Why not use the helper here?

### @you · 2026-06-24 11:00 · note 2
<!-- mr-review:note 2 -->
Good point, but the helper doesn't handle the null case.
<!-- mr-review:/note 2 -->

<!-- mr-review:draft — write your reply below this line -->

````

### Authoring rules

- **Reply:** write under the `mr-review:draft` marker; set `publish: true` to
  mark ready. Everything after the (single, unescaped) draft marker is the reply
  body, verbatim.
- **Edit a prior comment:** edit the text inside your note's
  `<!-- mr-review:note N -->` … `<!-- mr-review:/note N -->` block and add `N`
  to `edit_notes`. `status` warns if a note body diverges from canonical but is
  not listed (catches accidental edits).
- **Resolve:** set `resolve: true` (used sparingly by authors).

### Diff context block

Built from **git using the comment's own position SHAs**, so it is accurate
regardless of the working tree's state. Each GitLab diff `position` carries the
`base_sha` / `start_sha` / `head_sha` of the diff version the comment was made
against, plus old/new paths and lines. The context block is reconstructed by
reading the relevant blob at that SHA:

- new-side comment → `git show <head_sha>:<new_path>`, slice around `new_line`;
- old-side comment → `git show <base_sha>:<old_path>`, slice around `old_line`;
- `line_range` (multiline) → show the full range plus a little surrounding
  context.

This reads git blobs (present in the same repo once fetched), not the working
tree, so it shows exactly what the reviewer commented on even if the branch has
since moved on. If a required blob isn't available locally, the adapter may fetch
the diff via the forge as a fallback.

The only working-tree-dependent piece is the **clickable file link** —
`[↗ open <path>#L<line>]`, a relative path from the thread file to the real file
(`../../<path>#L<line>`), using `new_path`/`new_line`. It opens the *current*
file and is therefore only accurate when the working tree is on the right
commit. The `#L` anchor is editor-dependent but the file still opens without it.

## In-band marker collision handling

GitLab comments are markdown, so our in-band markers could in principle appear
inside a real comment. The architecture neutralizes almost all of this, and the
small remainder is hardened cheaply.

**Core rule: we never parse the published region.** Canonical JSON is the source
of truth for published bodies; the published region is regenerated and
display-only. Therefore code fences, `##` headings, or even a literal
`<!-- mr-review:draft -->` *inside a reviewer's comment* cannot corrupt anything
— we render those bodies out of JSON and never read them back.

The only text parsed back is what the author/agent writes. That surface is
hardened four ways:

1. **All control flags live in YAML frontmatter** (`publish`, `resolve`,
   `edit_notes`). Frontmatter is structurally un-spoofable — a comment body in
   the document body cannot inject the top-of-file `---` block.
2. **Namespaced, distinctive markers** (`<!-- mr-review:… -->`) make accidental
   collision vanishingly unlikely.
3. **Escape-on-render:** when rendering a comment body into the published
   region, any literal `<!-- mr-review:` sequence is neutralized. Since the tool
   owns rendering, the file contains only the markers it wrote. (HTML comments
   don't render in markdown preview, so this is invisible.)
4. **Fail loud, never guess:** ambiguous parses (unbalanced note markers,
   missing/duplicate draft boundary) cause that thread to be reported and
   skipped — never a wrong post.

Inline editing therefore survives intact; the only way to trip parsing is the
author's *own* edit introducing a marker, which is detected and reported.

## Sidecar schema (`.state/123.json`)

Forge-native, never hand-edited.

```json
{
  "forge": "gitlab",
  "project": "group/sub/repo",
  "mr": "123",
  "head_sha": "…", "base_sha": "…", "start_sha": "…",
  "current_user": "you",
  "synced_at": "2026-06-25T15:30:00Z",
  "retired_thread_handles": [],
  "threads": [
    {
      "local_id": 1,
      "native_id": "9a8b7c6d5e",
      "resolvable": true, "resolved": false,
      "position": { "new_path": "src/foo.py", "new_line": 42, "old_path": "src/foo.py", "old_line": null, "line_range": null, "base_sha": "…", "start_sha": "…", "head_sha": "…" },
      "retired_note_handles": [],
      "notes": [
        { "local_id": 1, "native_id": "555", "author": "reviewer1", "mine": false, "system": false, "created_at": "…", "updated_at": "…", "body": "Why not use the helper here?" },
        { "local_id": 2, "native_id": "556", "author": "you", "mine": true, "system": false, "created_at": "…", "updated_at": "…", "body": "Good point, …" }
      ]
    }
  ]
}
```

## Commands

All default `<mr>` to the current branch's MR; `-R/--repo` overrides and is
passed through to the forge.

- **`mr-review sync [<mr>]`** — fetch discussions → update the sidecar (stable
  handle assignment, safe-merge) → render/update thread files, preserving draft
  regions. If a note the author is editing changed upstream, inject a ⚠ flag in
  the file. Bootstraps `mr-review/.gitignore` on first run.
- **`mr-review status [<mr>] [--json]`** — read-only; posts nothing. Lists each
  thread (resolved state, file:line) and its pending drafts: reply ready/not,
  inline edits (ready vs *unmarked-divergent* warning), resolve flag, and
  retired-handle warnings. `--json` is the agent's machine-readable confirmation
  surface.
- **`mr-review publish [<mr>] [--dry-run]`** — parse → plan → post only ready
  items (reply if `publish: true`, edits for handles in `edit_notes`, resolve if
  `resolve: true`) → update the sidecar → re-render. Non-interactive.
  `--dry-run` prints the exact plan (same data as `status`) without posting.

### Sync semantics (safe-merge)

Draft regions are local-only and never touched by sync. Sync refreshes the
published comments from the freshly fetched canonical state. If a note that is
currently being edited (a member of a thread's effective `edit_notes`, or whose
local body diverges from canonical) changed upstream since the last sync, a ⚠
conflict marker is injected so the author can reconcile. Nothing is silently
overwritten or lost.

### Publish semantics

`publish` is **transactional per item**: each successful post updates the
sidecar immediately, so a mid-batch failure never re-posts an already-sent reply
on retry. Only items marked ready are posted. After posting, affected threads
are re-rendered (new reply becomes a published note with the next free handle;
edited bodies replace canonical; resolve state updated).

## Error handling

Per project conventions (no panics/asserts; return errors, let callers decide):

- `glab` failures (auth 401, network, non-zero exit) surface as a clear
  `ForgeError` carrying the command and stderr — never a raw stack trace.
- Parse ambiguity → fail loud: report and skip that thread; other threads
  proceed.
- Publish item failures are isolated; the sidecar records what already
  succeeded.

## Module structure

```
local-mr-review/
  pyproject.toml                 # uv project; deps: click, pyyaml
  src/mr_review/
    cli.py            # entrypoint, subcommands, dispatch
    config.py         # root-dir discovery, optional config, forge factory
    domain.py         # frozen dataclasses (MergeRef, MergeRequest, Discussion, Note, DiffPosition)
    forge/
      base.py         # Forge Protocol (the port)
      gitlab.py       # GitLabForge adapter — maps GitLab JSON ↔ domain
      glab.py         # thin subprocess wrapper around `glab` (run, parse, errors)
    store.py          # sidecar load/save + stable local-handle assignment (assign/reuse/retire)
    layout.py         # paths, filename slugs, .gitignore bootstrap
    diffcontext.py    # build the ```diff hunk from the local working tree
    render.py         # canonical state → markdown (frontmatter, diff block, escape-on-render)
    parse.py          # markdown draft regions → frontmatter + reply + inline edits (fail-loud)
    plan.py           # diff parsed drafts vs canonical → list[Action] (Reply/Edit/Resolve)
    sync.py / status.py / publish.py   # command orchestration
  tests/
```

Each module is small and single-purpose. The only code touching
`glab` / GitLab JSON / native ids is `forge/gitlab.py` + `forge/glab.py`.

## Testing approach

Per project test discipline — assert behavior through real interfaces, no
shape-only assertions.

- **`FakeForge`** implementing the port, in-memory, drives most tests:
  - sync renders expected thread files from a set of discussions;
  - re-sync preserves draft regions;
  - an upstream edit to a note under edit injects a ⚠ flag;
  - publish calls the right port methods with the right bodies and skips
    non-ready items;
  - local-handle stability across upstream delete/insert (existing handles
    unchanged, new gets next, deleted retired; dangling `edit_notes` warns);
  - escape-on-render round-trips a comment body containing a literal marker
    without corrupting parse;
  - parse fails loud on malformed input (unbalanced markers, missing/duplicate
    draft boundary).
- **GitLab adapter** tested against recorded `glab mr note list -F json`
  fixtures with the subprocess runner stubbed — asserts JSON→domain mapping and
  that reply/edit/resolve build the correct `glab mr note` invocations (args +
  stdin body). No network.
- pytest, run via `uv run pytest`.

## Dependencies

- Runtime: `click` (CLI), `pyyaml` (frontmatter). `glab` external binary.
- Dev: `pytest`, `ruff` (lint + format; both must pass after every change).
- Managed with `uv` (`pyproject.toml`, `uv sync`, `uv run`).

## Implemented enhancements (post-v1)

- **ForgeError context on malformed `glab` output.** `GlabRunner.json` wraps a
  JSON decode failure, and `GitLabForge.fetch_mr`/`list_discussions`/
  `_current_user` wrap their JSON→domain field access, so a `glab` contract
  violation surfaces as a `ForgeError("unexpected glab response for '<op>': …")`
  instead of a bare `KeyError`/`JSONDecodeError`. (`ForgeError` is now
  message-first, still carrying `args_`/`returncode`/`stderr` for command
  failures.)
- **Outdated-position flagging.** A diff thread is *outdated* when its
  `position.head_sha` differs from the MR's current `head_sha` (the comment is
  anchored to a superseded commit, so the `[↗ open …#LN]` link may have drifted —
  the diff-context block itself stays accurate, rebuilt from the comment's own
  SHA). Detected by the shared `store.position_is_outdated(position, head_sha)`;
  surfaced as a frontmatter `outdated` field, a `⚠ Outdated: …` body line under
  the link, and a `· outdated` marker / JSON field in `status`. It is a computed,
  read-only field — `parse`/`plan` ignore it. `status` computes it offline from
  the sidecar's `head_sha`.

## Future work

- `GitHubForge` adapter (PR review threads, GraphQL resolve).
- Creating discussions / starting reviews (author currently responds only).
- `mr-review list` to browse one's open MRs.
- Smoother `edit_notes` ergonomics if maintaining the handle list by hand proves
  painful (e.g. inferring intent from a per-note marker).
