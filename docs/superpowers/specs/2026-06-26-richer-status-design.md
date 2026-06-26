# Richer `status` Overview — Design

**Status:** approved (brainstorming)
**Date:** 2026-06-26
**Builds on:** `2026-06-25-local-mr-review-design.md`

## Overview

Enrich the existing `mr-review status` command so it serves as the "lay of the
land" overview for an MR — enough to triage without opening each thread file.
It stays a **live, read-only command** (no persistent index file): everything is
computed at call time from local state + the draft files, so it never goes
stale. This is the surface both a human and the AI review-response skill read
first.

No new forge calls, no sidecar/schema changes — all new data comes from the
`StateDoc` threads, the parsed draft files, and `plan_thread`.

## Goals

- Show, per thread: reviewer(s), a first-comment excerpt, note count, resolved
  state, and draft state (ready / WIP / clean) plus any plan warnings — in
  addition to the existing handle, file:line, and ready actions.
- A summary header with counts (threads, unresolved, ready-to-publish, WIP,
  warnings).
- Filtering: `--unresolved` and `--file <path>`, composable.
- Both renderings: human text and `--json` (additive, backward-compatible).

## Non-goals

- No persistent `_index.md` file (rejected to avoid stale draft state between
  syncs; the live command is the source of truth).
- No new forge/network calls; no changes to sync/publish/render/parse beyond
  what `status` consumes.
- No triage tags / `addressed_by` linking (separate future features).

## Draft-state model

The one piece of new logic. Per thread, `status` derives a `draft_state` from
the parsed file + `plan_thread`:

- **`ready`** — at least one item is marked to publish: a `ReplyAction`,
  `EditAction`, or `ResolveAction` from `plan_thread`.
- **`wip`** — a draft exists but is not marked ready: reply text present with
  `publish: false`, and no ready actions. Detected by `status` from the parsed
  thread (`parsed.reply` non-empty and frontmatter `publish` not true). `plan`
  stays focused on actions; `status` owns this classification.
- **`clean`** — neither of the above.

`warnings` are `plan_thread`'s warnings (unmarked-divergent edit, dangling
`edit_notes` handle, empty published reply, etc.) and are shown independently of
the draft state.

Precedence: `ready` > `wip` > `clean`.

## Derived display fields

- **reviewers** — sorted unique authors of the thread's notes excluding the
  current user. If the thread has only the current user's own notes, this is
  empty and renders as `(self)`.
- **excerpt** — the first note's body with newlines collapsed to spaces and
  truncated to ~80 chars (ellipsis `…` appended when truncated). Sourced from
  the canonical `StoredThread.notes[0].body`.
- **note_count** — number of notes in the thread (`len(thread.notes)`).
- **resolved**, **file**, **line** — as today (from `StoredThread` /
  `dict_to_position` + `line_label`).

## Text format

Extends the current `· `-separated style. Header line per thread, then an
indented excerpt line, then any indented `⚠` warning lines:

```
MR !1 — 2 threads: 1 unresolved, 1 ready to publish, 0 WIP, 0 warnings
  thread 1 · @krkroening · general · unresolved · 3 notes · [reply ready]
      "Why not use the helper here?…"
  thread 2 · (self) · .vscode/launch.json:6 · resolved · 2 notes
      "a diff comment"
      ⚠ note 2 edited but not in edit_notes
```

Header line order: `thread <handle> · <reviewer> · <file:line | "general"> ·
<resolved|unresolved> · <N> notes · <draft tag>`.

Draft tag:
- ready: `[reply ready]`, `[edit ready]`, `[resolve ready]` — joined with `, `
  when several apply (e.g. `[reply ready, resolve ready]`).
- wip: `[draft: not ready]`.
- clean: no tag.

When the filtered set is empty, print the summary header with `0 threads` and
a note of the active filter. When nothing is ready across the shown set, the
existing `(nothing marked ready)` line is retained under the summary.

## JSON shape (`--json`, additive)

```json
{
  "mr": "1",
  "summary": {"threads": 2, "unresolved": 1, "ready": 1, "wip": 0, "warnings": 0},
  "filter": {"unresolved": false, "file": null},
  "threads": [
    {
      "local_id": 1,
      "file": null,
      "line": "general",
      "resolved": false,
      "reviewers": ["krkroening"],
      "note_count": 3,
      "excerpt": "Why not use the helper here?",
      "draft_state": "ready",
      "actions": [{"type": "ReplyAction", "thread_local_id": 1, "discussion_id": "…", "body": "…"}],
      "warnings": []
    }
  ]
}
```

`draft_state` ∈ `clean | wip | ready`. The existing `actions` and `warnings`
keys are unchanged in meaning; `summary`, `filter`, and the new per-thread
fields (`reviewers`, `note_count`, `excerpt`, `draft_state`) are additive — an
agent already reading `actions`/`warnings` keeps working.

Summary counts are **numbers of threads** (not actions) in each category over
the filtered set: `threads` = shown threads; `unresolved` = threads not
resolved; `ready` = threads with ≥1 ready action (a thread with both a ready
reply and a ready resolve counts once); `wip` = threads with `draft_state ==
"wip"`; `warnings` = threads with ≥1 warning.

## Filtering

- `--unresolved` — keep only threads where `resolved` is false.
- `--file <path>` — keep only threads whose diff position path
  (`new_path` or `old_path`) equals `<path>`. General (non-diff, position-less)
  threads are excluded by `--file`.
- Both compose (logical AND). Filtering is applied in `gather_status` before
  rendering; the `summary` counts and `filter` object reflect the **filtered**
  set. Filters read only local state — no forge calls.

## Module & test changes

- **`status.py`**
  - Extend `ThreadStatus` with `reviewers: list[str]`, `note_count: int`,
    `excerpt: str`, `draft_state: str`.
  - Add a `summary` (counts) to `StatusReport` and a `filter` record.
  - `gather_status(review_dir, mr, *, unresolved=False, file=None)` computes the
    new fields, classifies `draft_state` (incl. WIP detection), and applies
    filters.
  - `format_status` / `status_json` render the new fields and summary per the
    formats above.
- **`cli.py`**: add `--unresolved` (flag) and `--file <path>` options to the
  `status` command; thread them into `gather_status`. The `_resolve_iid`
  read-only path is unchanged.
- **Tests** (behaviour-driven, via the existing `FakeForge` + `sync` setup and
  temp dirs):
  - reviewer derivation (non-self author shown; all-self → `(self)`);
  - excerpt truncation/newline-collapse;
  - note_count;
  - the three draft states: `clean`, `wip` (reply text but `publish: false`),
    `ready` (marked);
  - a warning surfaced (e.g. unmarked-divergent edit);
  - `--unresolved` narrows to unresolved threads;
  - `--file` narrows to a path and excludes general threads;
  - the two filters compose;
  - `summary` counts match the filtered set;
  - `status_json` carries the additive fields without dropping `actions`/`warnings`.

## Error handling

Unchanged from current `status`: a thread file that fails to parse is reported
as a per-thread warning (and contributes to the warnings count) rather than
crashing the command; a thread with no file on disk is treated as `clean` with
no actions. No new exceptions.
