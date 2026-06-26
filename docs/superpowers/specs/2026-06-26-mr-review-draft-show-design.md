# Draft & Show Commands — Design

**Status:** approved (brainstorming)
**Date:** 2026-06-26
**Builds on:** `2026-06-25-local-mr-review-design.md`, `2026-06-26-richer-status-design.md`

## Overview

Two ergonomic additions to close the gap in the **middle of the review loop**,
between `sync` and `publish`. Both were prompted by watching an AI agent drive
the tool without a skill: it `cat`-ed all 34 thread files by hand to read them
(because `status` only emits an 80-char excerpt), and it wrote an ad-hoc append
script to draft replies (because Read+Edit on every file is slow and the script
risked double-appending).

- **Read path** — a `--full` mode on `status` (plus a discoverable `show` alias)
  that emits each thread's full content in one call.
- **Write path** — a `draft` command (alias `reply`) that stages a reply *or* an
  edit to one of your own notes, taking the body from **stdin** and locating the
  file/region by local handle, so the agent never opens a file by name; plus a
  body-free `mark` command that flips the `publish`/`resolve` flags for the
  skill's explicit approval step.

No new forge/network calls and no sidecar/schema changes: the read path reads
the same local state + draft files `status` already consumes, and the write path
edits the same draft/note regions `parse` already recognizes. The skill document
that will prescribe the end-to-end workflow is a **separate follow-up** (authored
with `writing-skills` once these commands exist) — see Non-goals.

## Goals

- One call returns full thread content (note bodies with handles + author/ts, the
  diff block, any current draft), reusing the existing `--unresolved` / `--file`
  filters and `--json`.
- A `show` alias for discoverability; `--full` remains on `status` for scripting.
- One pipeable `draft` command stages both replies and own-note edits, body via
  stdin (no escaping of multi-line Markdown / code fences).
- Drafting is **idempotent** (replace, never append) and **gating-preserving**
  (`publish`/`resolve` default to leave-as-is; a fresh draft stays `publish:
  false`).
- A body-free `mark` command flips `publish`/`resolve` so the approval step can
  promote drafts to publish without re-sending bodies, keeping the marker gate an
  explicit, separate action from drafting.

## Non-goals

- **No skill document in this spec.** The skill is the next phase; it's authored
  against commands that exist, not designed in the abstract here.
- No new forge calls, no changes to the sidecar/state schema or to
  sync/publish/render/parse beyond what these two surfaces consume and the
  region-rewrite the write path performs.
- No batch/JSON-stdin draft ingestion. Rejected: multi-line Markdown bodies with
  backticks and our own markers are painful and error-prone to embed in JSON;
  per-thread stdin is the ergonomic primitive. (An agent loops over threads; each
  call is one cheap bash invocation with no Read first.)
- No new-discussion creation, no resolve-by-default — unchanged from the base
  tool's author-responds scope.

## Read path: `status --full` and the `show` alias

`status` gains a `--full` flag. In `--full` mode the per-thread **excerpt** is
replaced by the thread's **full content**; everything else about `status` (the
summary header, `--unresolved` / `--file` filters, `--json`, `draft_state`,
warnings) is unchanged and composes with it.

- `mr-review show <mr>` is an **alias** that invokes `status` with `--full`
  forced on, accepting all the same flags/filters. It exists for discoverability:
  an agent (or human) looking to *read* finds `show` faster than guessing a flag.
  `status --full` remains for scripting/explicitness.
- A `--thread N` filter is added to `status` (works in both modes, composes with
  the others), so `show <mr> --thread 2` dumps a single thread.

### Full text rendering

For each shown thread, after the existing one-line header, emit (indented under
the header) the thread's content rather than the excerpt line:

- the **diff context block** (the ```diff fence as rendered in the file),
- each note in order as `@author · <ts> · note N` followed by its full body,
- the current **draft** (reply text and/or pending note edits) if any, labelled
  so it's distinguishable from published content.

This is sourced from the canonical `StoredThread` (note bodies, authors,
timestamps, position) and the parsed draft file (current reply / note edits) —
the same inputs `gather_status` already loads. The summary header and `(nothing
marked ready)` / empty-filter behaviour are unchanged.

### `--full --json`

`--full` flows through the existing `--json` path: each thread object replaces
the `excerpt` string with structured full content —

```json
{
  "local_id": 2,
  "file": "docs/.../README.md",
  "line": "155",
  "resolved": false,
  "reviewers": ["kim"],
  "note_count": 2,
  "diff": "  154  ...\n> 155  ...\n  156  ...",
  "notes": [
    {"handle": 1, "author": "kim", "created_at": "2026-06-24T10:00:00Z", "body": "Why not …", "mine": false},
    {"handle": 2, "author": "you", "created_at": "2026-06-24T11:00:00Z", "body": "…", "mine": true}
  ],
  "draft": {"reply": "", "note_edits": {}},
  "draft_state": "clean",
  "actions": [],
  "warnings": []
}
```

Per-note keys map to `StoredNote`: `handle` = `local_id`, plus `author`,
`created_at`, `body`, and `mine`. `mine` is the flag the write path needs to
know whether a note is editable via `--note` (only own notes are wrapped with
markers); `handle` is what `--thread`/`--note` target. In non-`--full` JSON the
output is exactly today's shape (`excerpt`, no `diff`/`notes`/`draft`), so
existing consumers are unaffected; `--full` is purely additive.

## Write path: `draft` (alias `reply`) and `mark`

Two commands, split by *what they touch*: `draft` writes a body region; `mark`
flips only the frontmatter flags. The split is deliberate — it avoids guessing
"was a body piped?" from `isatty` (unreliable in an agent shell), and it mirrors
the planned skill flow: the agent **drafts** everything (`publish: false`), the
user reviews, then a single explicit **mark** step flips the approved threads to
publish.

### `draft` — write a reply or note edit

One command stages both a reply and an edit to one of your own prior notes. The
body always comes from **stdin**. The tool resolves the thread file from local
state by handle — the agent never names a file.

```
mr-review draft <mr> --thread N [--note M] \
    [--publish/--no-publish] [--resolve/--no-resolve] [-R <repo>]
```

`reply` is registered as an alias of `draft`.

#### Modes

- **Reply (no `--note`)** — replace the **reply draft region** (everything below
  the single `mr-review:draft` marker line) with the stdin body. The frontmatter
  and the published region above the marker are left intact.
- **Edit (`--note M`)** — replace the body **between** that note's
  `<!-- mr-review:note M -->` and `<!-- mr-review:/note M -->` markers with the
  stdin body, and ensure `M` is present in the `edit_notes` frontmatter list.

Only the current user's own notes are wrapped with note markers (per the base
design), so `--note M` is valid only when those markers exist in the file.

#### Flags

- `--publish/--no-publish`, `--resolve/--no-resolve` set the corresponding
  frontmatter flags. **Omitted = leave the existing value untouched** — so
  re-drafting a body never silently clobbers a human-set flag, and a freshly
  synced thread (rendered `publish: false`) stays unpublished until explicitly
  flipped. The marker-gated `publish` confirmation step is preserved: the agent
  drafts; a human (or an explicit `--publish`, or a later `mark`) decides.
- `-R/--repo` matches the other commands (used to resolve a branch/current-branch
  `<mr>` to an iid; a numeric `<mr>` needs no forge call, same as `status`).

#### Semantics & invariants

- **Idempotent** — both modes *replace* their region; re-running `draft` for the
  same thread overwrites rather than appends. This directly removes the
  double-append failure mode of the ad-hoc script.
- **Body neutralization** — the stdin body is run through `markers.neutralize`
  before being written, so a body that itself contains `<!-- mr-review:… -->`
  text cannot introduce a second draft marker or a stray note marker and break
  `parse_thread` on the next read. (Same protection already applied to rendered
  reviewer bodies.)
- **Frontmatter stability** — `publish`/`resolve`/`edit_notes` are updated by
  reusing the render layer's frontmatter serialization (not an ad-hoc YAML dump),
  so a drafted file round-trips through the next `sync` without spurious diffs or
  field reordering.
- **Published region untouched** in reply mode; in edit mode only the targeted
  note's inner body changes. The publish path's "published region is never parsed
  back" guarantee is unaffected (note edits are already the one parsed-back part,
  and we write into exactly those blocks).

#### Fail-loud errors (exit non-zero, write nothing)

- `<mr>` not synced / thread file missing → tell the user to run `sync` first.
- `--thread N` not found in local state.
- `--note M` given but no editable (own-note) markers for `M` in the file →
  reported, not guessed (consistent with publish's fail-loud philosophy).
- Empty stdin (no piped content) → error rather than writing an empty
  reply/edit. To change *only* flags without touching the body, use `mark`.

### `mark` — flip publish/resolve flags

A body-free companion to `draft` for the skill's explicit approval step: after
the user reviews the drafted replies/edits, this flips the approved threads to
publish without re-sending any body.

```
mr-review mark <mr> --thread N \
    [--publish/--no-publish] [--resolve/--no-resolve] [-R <repo>]
```

- Reads no stdin. Edits **only** the `publish`/`resolve` frontmatter flags of
  thread `N`, reusing the same render-layer frontmatter serialization as `draft`
  (so files stay stable across `sync`). The reply/note regions are untouched.
- At least one of the flags is required (a `mark` with no flag is a no-op and
  errors). Omitted flags are left as-is, exactly like `draft`.
- Same fail-loud cases as `draft` for an unsynced MR or a missing `--thread N`.
- v1 marks one thread per call (the agent loops over an approved set). A
  repeatable `--thread` / `--all` batch form is an easy, additive follow-up if
  the per-call overhead ever matters — explicitly out of scope here.

## Module & test changes

- **`status.py`**
  - `gather_status(..., full: bool = False)` additionally collects, per thread:
    the diff block, the ordered notes (handle/`local_id`, author, created_at,
    body, mine), and the
    parsed `draft` (reply + note_edits). `ThreadStatus` carries these optional
    fields; the existing `excerpt`/`draft_state`/`actions`/`warnings` are
    unchanged.
  - `format_status` renders full content beneath each header when `full`;
    `status_json` emits the structured `diff`/`notes`/`draft` block when `full`
    and the unchanged `excerpt` shape otherwise.
- **`cli.py`**
  - `status` gains `--full` and `--thread N`.
  - Register `show` as a command that calls the same implementation with
    `full=True` and the shared filters.
  - Add the `draft` command (and `reply` alias) and the `mark` command. Both
    resolve iid → load state → locate the thread file by handle, then delegate
    the rewrite to the shared write helper below; the CLI layer stays thin.
- **New write helper** (e.g. `draftwrite.py`) — the one place that mutates a
  thread file: replace the reply region or a note block (`draft`), and/or set
  `publish`/`resolve` frontmatter flags (`draft` and `mark`), reusing
  `render.py`'s frontmatter serialization for stable round-tripping and
  `markers.neutralize` for bodies. Keeping this out of `cli.py` lets it be
  unit-tested directly and shared by both commands.
- **`render.py`** — expose/reuse the frontmatter serializer the write helper
  needs (refactor only if it isn't already callable in isolation).
- **Tests** (behaviour-driven, via the existing `FakeForge` + `sync` setup and
  temp dirs — assert observable file/CLI outcomes, not structure):
  - `show`/`--full` text includes a note's full body and the diff (not just the
    truncated excerpt); `--unresolved`/`--file`/`--thread` filters narrow it; the
    summary header is retained.
  - `--full --json` carries `diff`, `notes` (with `handle`/`mine`), and `draft`;
    non-`--full` JSON is byte-for-byte the current shape (no `diff`/`notes`).
  - `draft --thread N` writes the body below the marker and the file re-parses;
    re-running replaces (does not duplicate) the reply.
  - `draft --thread N --note M` rewrites note M's body and adds `M` to
    `edit_notes`; `parse_thread.note_edits[M]` reflects it.
  - `draft --publish` sets the flag; omitting it leaves a prior value untouched;
    `--no-publish` clears it.
  - `mark --thread N --publish` flips only the flag (reply/note regions and other
    frontmatter unchanged); `mark` with no flag errors; `mark --no-publish`
    clears a previously set flag.
  - a body containing a literal `<!-- mr-review:draft -->` / `note` marker is
    neutralized and the file still parses (single draft marker preserved).
  - fail-loud: missing thread, missing sync, non-own `--note`, empty `draft`
    stdin — each exits non-zero and leaves the file unchanged.
  - a drafted file is stable across a subsequent `sync` (no spurious frontmatter
    diff).

## Error handling

Consistent with the existing tool: read-path parse failures continue to surface
as per-thread warnings with `draft_state: "error"` (now under `--full` the
broken file's raw content is still shown where possible). The write path validates
before mutating and writes atomically per file, so a rejected `draft` leaves the
target file exactly as it was. No new exception types beyond the click usage
errors above.
