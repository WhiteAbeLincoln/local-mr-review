# Draft & Show Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-call read surface (`status --full` + `show` alias) and pipeable write commands (`draft`/`reply` and `mark`) so an agent stops `cat`-ing files and hand-writing append scripts in the middle of the review loop.

**Architecture:** A new pure-text helper module (`draftwrite.py`) does all thread-file mutation — replacing the reply region, replacing a note block, and flipping frontmatter flags — reusing the existing render-layer frontmatter serialization and `markers.neutralize`. `status.py` gains an optional `full` mode that reconstructs full thread content (clean note bodies from canonical state, the diff fence from the rendered file, the parsed draft). `cli.py` wires four thin commands on top; all file location is by local handle via existing `layout`/`store` helpers.

**Tech Stack:** Python 3.14+, `click` (CLI), `pyyaml` (frontmatter), `pytest`. No new dependencies.

## Global Constraints

- **Python ≥ 3.14**; dependencies limited to `click>=8.1` and `pyyaml>=6.0` — **do not add new runtime deps.**
- **No `panic`-equivalent in production code.** CLI usage/validation failures raise `click.ClickException` (exits non-zero, prints the message, writes nothing). `t.Fatal`-style hard failures are for tests only.
- **Tests assert behaviour, not shape.** Drive the real interface (CLI via `CliRunner`, or the public function) and assert observable outcomes (file content re-parses to X, JSON has value Y, exit code non-zero). Do not assert struct field layout or that a constant exists.
- **Ruff**: `line-length = 100`, target `py314`. Run `uv run ruff check .` and `uv run ruff format .` before each commit.
- **Run tests with** `uv run pytest`.
- **Commit messages document the *why***, not a file-by-file list. End each with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- **Default branch is `trunk`.**
- Use the **Edit tool** (not `sed`) for file edits.

## File Structure

- `src/mr_review/markers.py` — *modify*: add a single `DRAFT_LINE` constant (the full draft marker line) so render and the write helper share one literal.
- `src/mr_review/render.py` — *modify*: extract `dump_frontmatter(data)` from `_frontmatter`; use `DRAFT_LINE` for the marker.
- `src/mr_review/draftwrite.py` — *create*: pure functions that take a thread file's full text and return new text — `write_reply`, `write_note_edit`, `set_flags`, plus `DraftError`. The only place thread files are mutated.
- `src/mr_review/status.py` — *modify*: `gather_status(..., thread=None, full=False)`; `ThreadStatus` gains optional `diff`/`notes`/`draft`; `format_status`/`status_json` render full content when `full`.
- `src/mr_review/cli.py` — *modify*: `status` gains `--full`/`--thread`; add `show`, `draft` (alias `reply`), `mark`; shared `_run_status` + `_locate_thread_file` helpers.
- `tests/test_draftwrite.py` — *create*: unit tests for the write helper.
- `tests/test_status.py` — *modify*: full-mode gather/format/json tests.
- `tests/test_cli.py` — *modify*: CLI tests for the new commands + fail-loud cases; update the existing filter-passing test for the new kwargs.
- `tests/test_integration.py` — *modify*: draft-then-sync stability test.
- `README.md` — *modify*: document `show`, `draft`/`reply`, `mark`.

---

### Task 1: `draftwrite` core + shared frontmatter/marker literals

**Files:**
- Modify: `src/mr_review/markers.py`
- Modify: `src/mr_review/render.py:108` (marker line), `src/mr_review/render.py:41-55` (`_frontmatter`)
- Create: `src/mr_review/draftwrite.py`
- Test: `tests/test_draftwrite.py`

**Interfaces:**
- Consumes: `markers.neutralize`, `markers.note_open`, `markers.note_close`, `markers.DRAFT_LINE` (new); `render.dump_frontmatter` (new).
- Produces (relied on by Task 3):
  - `markers.DRAFT_LINE: str` — the exact full draft marker line.
  - `render.dump_frontmatter(data: dict) -> str` — frontmatter YAML body (no `---` fences), key order preserved, trailing whitespace stripped.
  - `draftwrite.DraftError(Exception)`.
  - `draftwrite.write_reply(text: str, body: str, *, publish: bool | None = None, resolve: bool | None = None) -> str`
  - `draftwrite.write_note_edit(text: str, handle: int, body: str, *, publish: bool | None = None, resolve: bool | None = None) -> str`
  - `draftwrite.set_flags(text: str, *, publish: bool | None = None, resolve: bool | None = None) -> str`
  - All three take a thread file's full text and return the new full text; `publish`/`resolve` left untouched when `None`.

- [ ] **Step 1: Add the shared marker constant**

In `src/mr_review/markers.py`, after the existing `DRAFT_PREFIX` line, add:

```python
DRAFT_LINE = f"{DRAFT_PREFIX} — write your reply below this line -->"
```

(Note the em-dash `—`; it must match what `render` currently writes byte-for-byte.)

- [ ] **Step 2: Extract `dump_frontmatter` and use `DRAFT_LINE` in render**

In `src/mr_review/render.py`:

Swap `DRAFT_PREFIX` for `DRAFT_LINE` in the import (render no longer uses
`DRAFT_PREFIX` after this task — leaving it would be an unused import and fail
`ruff`):

```python
from mr_review.markers import (
    DRAFT_LINE,
    PUBLISHED_PREFIX,
    neutralize,
    note_close,
    note_open,
)
```

Add the helper (place it directly above `_frontmatter`):

```python
def dump_frontmatter(data: dict) -> str:
    """Serialize frontmatter exactly as thread files store it: insertion order
    preserved (no key sorting), trailing whitespace stripped. Shared with the
    write path so drafted files round-trip through sync without reformatting."""
    return yaml.safe_dump(data, sort_keys=False).rstrip()
```

Change the end of `_frontmatter` from:

```python
    return yaml.safe_dump(data, sort_keys=False).rstrip()
```

to:

```python
    return dump_frontmatter(data)
```

Change the draft marker line in `render_thread` from:

```python
    parts.append(f"{DRAFT_PREFIX} — write your reply below this line -->")
```

to:

```python
    parts.append(DRAFT_LINE)
```

(`markers.DRAFT_PREFIX` itself stays defined in `markers.py` — other modules
and `markers.DRAFT_LINE` still reference it; only render's now-unused import of
it is dropped.)

- [ ] **Step 3: Write the failing tests for the write helper**

Create `tests/test_draftwrite.py`:

```python
import pytest

from mr_review import draftwrite
from mr_review.parse import parse_thread
from mr_review.render import RenderInputs, render_thread
from mr_review.store import StoredNote, StoredThread

POSITION = {
    "new_path": "src/foo.py",
    "old_path": "src/foo.py",
    "new_line": 42,
    "old_line": None,
    "base_sha": "B",
    "start_sha": "S",
    "head_sha": "H",
    "line_range": None,
    "position_type": "text",
}


def sample(*, reply="", publish=False, resolve=False, edit_notes=()):
    """A realistic thread file: reviewer note (handle 1) + own note (handle 2)."""
    thread = StoredThread(
        local_id=2,
        native_id="d1",
        resolvable=True,
        resolved=False,
        position=POSITION,
        notes=[
            StoredNote(1, "501", "reviewer", False, "t", "t", "Why not the helper?", True, False),
            StoredNote(2, "502", "me", True, "t", "t", "canonical", True, False),
        ],
    )
    return render_thread(
        RenderInputs(
            thread=thread,
            diff_block=None,
            reply_draft=reply,
            publish=publish,
            resolve=resolve,
            edit_notes=list(edit_notes),
            mr_head_sha="H",
        )
    )


def test_write_reply_sets_and_replaces_body():
    out = draftwrite.write_reply(sample(), "Good catch — fixed in abc123.")
    assert parse_thread(out).reply == "Good catch — fixed in abc123."
    # re-drafting replaces rather than appends
    out2 = draftwrite.write_reply(out, "Second take.")
    assert parse_thread(out2).reply == "Second take."
    assert "fixed in abc123" not in out2


def test_write_reply_neutralizes_embedded_markers():
    # a body that itself contains a draft marker must not break parsing
    body = "Compare:\n<!-- mr-review:draft — bogus -->\ndone"
    out = draftwrite.write_reply(sample(), body)
    parsed = parse_thread(out)  # must not raise "expected exactly one draft marker"
    assert "done" in parsed.reply


def test_write_note_edit_updates_body_and_edit_notes():
    out = draftwrite.write_note_edit(sample(), 2, "Revised wording.")
    parsed = parse_thread(out)
    assert parsed.note_edits[2] == "Revised wording."
    assert parsed.frontmatter["edit_notes"] == [2]


def test_write_note_edit_rejects_non_own_note():
    with pytest.raises(draftwrite.DraftError):
        draftwrite.write_note_edit(sample(), 1, "cannot edit reviewer note")


def test_set_flags_flips_publish_and_leaves_rest():
    out = draftwrite.set_flags(sample(reply="kept"), publish=True)
    parsed = parse_thread(out)
    assert parsed.frontmatter["publish"] is True
    assert parsed.frontmatter["resolve"] is False
    assert parsed.reply == "kept"


def test_omitted_flag_preserves_prior_value():
    out = draftwrite.set_flags(sample(publish=True), resolve=True)
    parsed = parse_thread(out)
    assert parsed.frontmatter["publish"] is True  # untouched
    assert parsed.frontmatter["resolve"] is True


def test_write_reply_can_also_set_publish():
    out = draftwrite.write_reply(sample(), "ship it", publish=True)
    assert parse_thread(out).frontmatter["publish"] is True
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/test_draftwrite.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mr_review.draftwrite'` (and `AttributeError` once the module exists but functions don't).

- [ ] **Step 5: Implement `draftwrite.py`**

Create `src/mr_review/draftwrite.py`:

```python
import re

import yaml

from mr_review.markers import DRAFT_LINE, neutralize, note_close, note_open
from mr_review.render import dump_frontmatter

_FM = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


class DraftError(Exception):
    pass


def _split(text: str) -> tuple[dict, str]:
    """Return (frontmatter dict, body-after-frontmatter). The body keeps its
    leading blank line so it can be re-joined verbatim."""
    m = _FM.match(text)
    if not m:
        raise DraftError("missing or malformed frontmatter block")
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise DraftError(f"invalid frontmatter YAML: {e}") from e
    return fm, text[m.end() :]


def _replace_reply(body: str, reply_text: str) -> str:
    i = body.find(DRAFT_LINE)
    if i == -1:
        raise DraftError("draft marker not found in thread file")
    published = body[:i]  # keeps the blank line that precedes the marker
    reply = neutralize(reply_text).strip()
    out = published + DRAFT_LINE
    if reply:
        out += "\n\n" + reply
    return out


def _replace_note(body: str, handle: int, new_body: str) -> str:
    open_marker, close_marker = note_open(handle), note_close(handle)
    oi = body.find(open_marker)
    ci = body.find(close_marker)
    if oi == -1 or ci == -1 or ci < oi:
        raise DraftError(f"note {handle} is not one of your own editable notes")
    edited = neutralize(new_body).strip()
    return body[: oi + len(open_marker)] + "\n\n" + edited + "\n\n" + body[ci:]


def _apply(
    text: str,
    *,
    reply: str | None = None,
    note: tuple[int, str] | None = None,
    publish: bool | None = None,
    resolve: bool | None = None,
) -> str:
    fm, body = _split(text)
    if publish is not None:
        fm["publish"] = bool(publish)
    if resolve is not None:
        fm["resolve"] = bool(resolve)
    if note is not None:
        handle, new_body = note
        body = _replace_note(body, handle, new_body)
        marked = list(fm.get("edit_notes") or [])
        if handle not in marked:
            marked.append(handle)
        fm["edit_notes"] = sorted(marked)
    if reply is not None:
        body = _replace_reply(body, reply)
    doc = f"---\n{dump_frontmatter(fm)}\n---\n{body}"
    return doc.rstrip() + "\n"


def write_reply(
    text: str, body: str, *, publish: bool | None = None, resolve: bool | None = None
) -> str:
    return _apply(text, reply=body, publish=publish, resolve=resolve)


def write_note_edit(
    text: str,
    handle: int,
    body: str,
    *,
    publish: bool | None = None,
    resolve: bool | None = None,
) -> str:
    return _apply(text, note=(handle, body), publish=publish, resolve=resolve)


def set_flags(
    text: str, *, publish: bool | None = None, resolve: bool | None = None
) -> str:
    return _apply(text, publish=publish, resolve=resolve)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_draftwrite.py -v`
Expected: PASS (7 passed). Also run the existing render/sync suites to confirm the refactor is behaviour-preserving:
Run: `uv run pytest tests/test_render.py tests/test_sync.py -v`
Expected: PASS.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add src/mr_review/markers.py src/mr_review/render.py src/mr_review/draftwrite.py tests/test_draftwrite.py
git commit -m "$(cat <<'EOF'
Add draftwrite helper so the agent stops hand-editing thread files

The agent had to Read+Edit each thread file (or script an append) to
draft replies and edits, which is slow and risks double-appending. A
pure-text helper that locates the reply/note region and flips flags —
sharing render's frontmatter serializer so files round-trip through
sync unchanged — gives the CLI a single safe mutation point.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `status --full` content reconstruction

**Files:**
- Modify: `src/mr_review/status.py`
- Test: `tests/test_status.py`

**Interfaces:**
- Consumes: `markers.PUBLISHED_PREFIX`; existing `load_state`, `parse_thread`, `plan_thread`, `dict_to_position`, `position_is_outdated`, `thread_path`, `line_label`.
- Produces (relied on by Task 3):
  - `gather_status(review_dir, mr, *, unresolved=False, file=None, thread=None, full=False) -> StatusReport`
  - `StatusReport.full: bool`
  - `ThreadStatus.diff: str | None`, `ThreadStatus.notes: list | None`, `ThreadStatus.draft: dict | None` (populated only when `full`).
  - In `--full` JSON each thread carries `diff`, `notes` (`[{handle, author, created_at, body, mine}]`), `draft` (`{reply, note_edits}`) and **omits** `excerpt`; non-full JSON is unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_status.py` (the imports of `DiffPosition, Discussion, MergeRef, MergeRequest, Note`, `format_status, gather_status, status_json`, `sync`, `FakeForge, fake_git`, and `MR`/`disc`/`synced` already exist at the top of the file):

```python
def disc_with_diff():
    # new_line=2 over a 3-line blob so the rendered diff fence has real content
    pos = DiffPosition("src/foo.py", "src/foo.py", 2, None, "B", "S", "H", None, "text")
    return Discussion(
        "dd",
        True,
        False,
        pos,
        (Note("601", "reviewer", False, False, "t", "t", "Please rename this.", True, False),),
    )


def test_full_text_shows_body_and_diff(tmp_path):
    forge = FakeForge(MR, [disc_with_diff()])
    sync(forge, tmp_path, MergeRef(ref="1"), fake_git("a\nb\nc\n"), now="N")
    out = format_status(gather_status(tmp_path, "1", full=True))
    assert "Please rename this." in out  # full body, not the 80-char excerpt
    assert "> 2  b" in out  # the rendered diff hunk, highlighted line


def test_full_json_has_notes_diff_draft_and_no_excerpt(tmp_path):
    forge = FakeForge(MR, [disc_with_diff()])
    sync(forge, tmp_path, MergeRef(ref="1"), fake_git("a\nb\nc\n"), now="N")
    t0 = status_json(gather_status(tmp_path, "1", full=True))["threads"][0]
    assert "excerpt" not in t0
    assert t0["notes"][0] == {
        "handle": 1,
        "author": "reviewer",
        "created_at": "t",
        "body": "Please rename this.",
        "mine": False,
    }
    assert "```diff" in t0["diff"]
    assert t0["draft"] == {"reply": "", "note_edits": {}}


def test_non_full_json_unchanged(tmp_path):
    synced(tmp_path)
    t0 = status_json(gather_status(tmp_path, "1"))["threads"][0]
    assert "excerpt" in t0
    for k in ("diff", "notes", "draft"):
        assert k not in t0


def test_thread_filter_selects_one(tmp_path):
    synced_multi(tmp_path)
    report = gather_status(tmp_path, "1", thread=1)
    assert [t.local_id for t in report.threads] == [1]
```

(`synced_multi` already exists in this file.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_status.py -k "full or thread_filter" -v`
Expected: FAIL — `gather_status() got an unexpected keyword argument 'full'`.

- [ ] **Step 3: Extend `ThreadStatus`, `StatusReport`, and add the diff extractor**

In `src/mr_review/status.py`, update the imports to include `PUBLISHED_PREFIX`:

```python
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mr_review.layout import line_label, state_path, thread_path
from mr_review.markers import PUBLISHED_PREFIX
from mr_review.parse import ParsedThread, ParseError, parse_thread
from mr_review.plan import plan_thread
from mr_review.store import dict_to_position, load_state, position_is_outdated
```

Add the diff extractor near the top (after `_EXCERPT_LEN`):

```python
_DIFF_RE = re.compile(r"```diff\n.*?```", re.DOTALL)


def _extract_diff(text: str) -> str | None:
    # The diff fence is rendered above the published marker; a reviewer comment
    # below it could also contain a ```diff fence, so only search the head.
    head = text.split(PUBLISHED_PREFIX, 1)[0]
    m = _DIFF_RE.search(head)
    return m.group(0) if m else None


def _notes_full(notes: list) -> list[dict]:
    return [
        {
            "handle": n.local_id,
            "author": n.author,
            "created_at": n.created_at,
            "body": n.body,
            "mine": n.mine,
        }
        for n in notes
    ]
```

Add the optional fields to `ThreadStatus` (after `warnings`):

```python
    diff: str | None = None
    notes: list | None = None
    draft: dict | None = None
```

Add `full` to `StatusReport` (after `filter` default or alongside the others):

```python
    full: bool = False
```

- [ ] **Step 4: Thread `full`/`thread` through `gather_status`**

Replace the `gather_status` signature and body in `src/mr_review/status.py` with:

```python
def gather_status(
    review_dir: Path,
    mr: str,
    *,
    unresolved: bool = False,
    file: str | None = None,
    thread: int | None = None,
    full: bool = False,
) -> StatusReport:
    state = load_state(state_path(review_dir, mr))
    report = StatusReport(mr=mr, filter={"unresolved": unresolved, "file": file}, full=full)
    if state is None:
        report.summary = _summary([])
        return report
    for thread_obj in state.threads:
        if unresolved and thread_obj.resolved:
            continue
        if thread is not None and thread_obj.local_id != thread:
            continue
        pos = dict_to_position(thread_obj.position)
        if file is not None:
            paths = {p for p in ((pos.new_path, pos.old_path) if pos else ()) if p}
            if file not in paths:
                continue
        source_file = (pos.new_path or pos.old_path) if pos else None
        path = thread_path(review_dir, mr, thread_obj.local_id, pos)
        outdated = position_is_outdated(thread_obj.position, state.head_sha)
        reviewers = _reviewers(thread_obj.notes, state.current_user)
        note_count = len(thread_obj.notes)
        excerpt = _excerpt(thread_obj.notes[0].body) if thread_obj.notes else ""
        file_text = path.read_text() if path.exists() else None
        diff = _extract_diff(file_text) if (full and file_text) else None
        notes = _notes_full(thread_obj.notes) if full else None
        if file_text is not None:
            try:
                parsed = parse_thread(file_text)
            except ParseError as e:
                report.threads.append(
                    ThreadStatus(
                        local_id=thread_obj.local_id,
                        file=source_file,
                        line=line_label(pos),
                        resolved=thread_obj.resolved,
                        reviewers=reviewers,
                        note_count=note_count,
                        excerpt=excerpt,
                        draft_state="error",
                        outdated=outdated,
                        warnings=[f"parse error: {e}"],
                        diff=diff,
                        notes=notes,
                        draft=None,
                    )
                )
                continue
        else:
            parsed = ParsedThread(frontmatter={}, reply="", note_edits={})
        plan = plan_thread(parsed, thread_obj)
        actions = [{"type": type(a).__name__, **asdict(a)} for a in plan.actions]
        if actions:
            draft_state = "ready"
        elif parsed.reply.strip():
            draft_state = "wip"
        else:
            draft_state = "clean"
        report.threads.append(
            ThreadStatus(
                local_id=thread_obj.local_id,
                file=source_file,
                line=line_label(pos),
                resolved=thread_obj.resolved,
                reviewers=reviewers,
                note_count=note_count,
                excerpt=excerpt,
                draft_state=draft_state,
                outdated=outdated,
                actions=actions,
                warnings=[w.message for w in plan.warnings],
                diff=diff,
                notes=notes,
                draft={"reply": parsed.reply, "note_edits": parsed.note_edits} if full else None,
            )
        )
    report.summary = _summary(report.threads)
    return report
```

(The only logic changes vs. the original are: the `thread` filter, reading `file_text` once, and computing `diff`/`notes`/`draft` under `full`. The variable was renamed `thread` → `thread_obj` to free `thread` for the new filter parameter.)

- [ ] **Step 5: Make `status_json` and `format_status` honour `full`**

Replace `status_json` with:

```python
def status_json(report: StatusReport) -> dict:
    return {
        "mr": report.mr,
        "summary": report.summary,
        "filter": report.filter,
        "threads": [_thread_json(t, report.full) for t in report.threads],
    }


def _thread_json(t: ThreadStatus, full: bool) -> dict:
    d = asdict(t)
    if full:
        d.pop("excerpt", None)
    else:
        for k in ("diff", "notes", "draft"):
            d.pop(k, None)
    return d
```

In `format_status`, replace the per-thread excerpt/warning block. The current loop body is:

```python
        if t.excerpt:
            lines.append(f'      "{t.excerpt}"')
        for w in t.warnings:
            lines.append(f"      ⚠ {w}")
```

Replace it with:

```python
        if report.full:
            _append_full(lines, t)
        elif t.excerpt:
            lines.append(f'      "{t.excerpt}"')
        for w in t.warnings:
            lines.append(f"      ⚠ {w}")
```

And add the helper above `format_status`:

```python
def _append_full(lines: list, t: ThreadStatus) -> None:
    if t.diff:
        lines.extend("    " + ln for ln in t.diff.splitlines())
    for n in t.notes or []:
        lines.append(f"    @{n['author']} · {n['created_at']} · note {n['handle']}")
        lines.extend("    " + ln for ln in n["body"].splitlines())
    draft = t.draft or {}
    if draft.get("reply"):
        lines.append("    --- draft reply ---")
        lines.extend("    " + ln for ln in draft["reply"].splitlines())
    for handle, body in (draft.get("note_edits") or {}).items():
        lines.append(f"    --- draft edit to note {handle} ---")
        lines.extend("    " + ln for ln in body.splitlines())
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_status.py -v`
Expected: PASS (existing status tests + the four new ones).

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add src/mr_review/status.py tests/test_status.py
git commit -m "$(cat <<'EOF'
Give status a full mode so reading a thread is one call

The agent never used status to read comments because it only emitted an
80-char excerpt, so it cat-ed every file by hand. A --full mode that
reconstructs the full content — clean note bodies from canonical state,
the diff from the rendered file (keeping the command offline for a
numeric IID), and the parsed draft — makes status the single read
surface. Non-full output is unchanged so existing consumers keep working.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: CLI commands — `status --full`/`--thread`, `show`, `draft`/`reply`, `mark`

**Files:**
- Modify: `src/mr_review/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `status_mod.gather_status`/`status_json`/`format_status` (Task 2); `draftwrite.write_reply`/`write_note_edit`/`set_flags`/`DraftError` (Task 1); `load_state`, `state_path`, `thread_path`, `dict_to_position`.
- Produces: the `show`, `draft`, `reply`, `mark` commands and `status --full`/`--thread` options.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py` (top-of-file imports `from types import SimpleNamespace` and `from mr_review.cli import _resolve_iid` already exist):

```python
from click.testing import CliRunner

from mr_review.domain import DiffPosition, Discussion, MergeRef, MergeRequest, Note
from mr_review.layout import state_path, thread_path
from mr_review.parse import parse_thread
from mr_review.store import dict_to_position, load_state
from mr_review.sync import sync
from tests.fakes import FakeForge, fake_git

MR = MergeRequest("1", "t", "https://gitlab.com/g/r/-/merge_requests/1", "g/r", "B", "S", "H", "me")


def _disc():
    pos = DiffPosition("src/foo.py", "src/foo.py", 42, None, "B", "S", "H", None, "text")
    return Discussion(
        "d1",
        True,
        False,
        pos,
        (
            Note("501", "reviewer", False, False, "t", "t", "Why?", True, False),
            Note("502", "me", True, False, "t", "t", "canonical", True, False),
        ),
    )


def _setup(monkeypatch, tmp_path, *, do_sync=True):
    from mr_review import cli

    if do_sync:
        sync(FakeForge(MR, [_disc()]), tmp_path, MergeRef(ref="1"), fake_git(), now="N")
    monkeypatch.setattr(cli, "_context", lambda: tmp_path)
    monkeypatch.setattr(cli, "make_forge", lambda: object())
    return cli


def _thread_file(tmp_path, local_id):
    st = load_state(state_path(tmp_path, "1"))
    t = next(t for t in st.threads if t.local_id == local_id)
    return thread_path(tmp_path, "1", local_id, dict_to_position(t.position))


def test_draft_cli_writes_reply_and_sets_publish(monkeypatch, tmp_path):
    cli = _setup(monkeypatch, tmp_path)
    res = CliRunner().invoke(
        cli.main, ["draft", "1", "--thread", "1", "--publish"], input="Done, thanks.\n"
    )
    assert res.exit_code == 0, res.output
    parsed = parse_thread(_thread_file(tmp_path, 1).read_text())
    assert parsed.reply == "Done, thanks."
    assert parsed.frontmatter["publish"] is True


def test_reply_alias_works(monkeypatch, tmp_path):
    cli = _setup(monkeypatch, tmp_path)
    res = CliRunner().invoke(cli.main, ["reply", "1", "--thread", "1"], input="via alias\n")
    assert res.exit_code == 0, res.output
    assert parse_thread(_thread_file(tmp_path, 1).read_text()).reply == "via alias"


def test_draft_cli_edits_own_note(monkeypatch, tmp_path):
    cli = _setup(monkeypatch, tmp_path)
    res = CliRunner().invoke(
        cli.main, ["draft", "1", "--thread", "1", "--note", "2"], input="reworded\n"
    )
    assert res.exit_code == 0, res.output
    parsed = parse_thread(_thread_file(tmp_path, 1).read_text())
    assert parsed.note_edits[2] == "reworded"
    assert parsed.frontmatter["edit_notes"] == [2]


def test_mark_cli_flips_publish_only(monkeypatch, tmp_path):
    cli = _setup(monkeypatch, tmp_path)
    res = CliRunner().invoke(cli.main, ["mark", "1", "--thread", "1", "--publish"])
    assert res.exit_code == 0, res.output
    parsed = parse_thread(_thread_file(tmp_path, 1).read_text())
    assert parsed.frontmatter["publish"] is True
    assert parsed.reply == ""  # body untouched


def test_show_cli_dumps_full_content(monkeypatch, tmp_path):
    cli = _setup(monkeypatch, tmp_path)
    res = CliRunner().invoke(cli.main, ["show", "1"])
    assert res.exit_code == 0, res.output
    assert "Why?" in res.output  # full reviewer body, not an excerpt


def test_draft_missing_thread_fails(monkeypatch, tmp_path):
    cli = _setup(monkeypatch, tmp_path)
    res = CliRunner().invoke(cli.main, ["draft", "1", "--thread", "99"], input="x\n")
    assert res.exit_code != 0
    assert "99" in res.output


def test_draft_not_synced_fails(monkeypatch, tmp_path):
    cli = _setup(monkeypatch, tmp_path, do_sync=False)
    res = CliRunner().invoke(cli.main, ["draft", "1", "--thread", "1"], input="x\n")
    assert res.exit_code != 0
    assert "sync" in res.output.lower()


def test_draft_empty_stdin_fails(monkeypatch, tmp_path):
    cli = _setup(monkeypatch, tmp_path)
    res = CliRunner().invoke(cli.main, ["draft", "1", "--thread", "1"], input="")
    assert res.exit_code != 0


def test_draft_non_own_note_fails(monkeypatch, tmp_path):
    cli = _setup(monkeypatch, tmp_path)
    res = CliRunner().invoke(
        cli.main, ["draft", "1", "--thread", "1", "--note", "1"], input="nope\n"
    )
    assert res.exit_code != 0
```

Also update the existing `test_status_cli_passes_filters` in this file: change its `fake_gather` signature and assertion to accept the new kwargs. Replace:

```python
    def fake_gather(review_dir, mr, *, unresolved=False, file=None):
        captured.update(mr=mr, unresolved=unresolved, file=file)
```

with:

```python
    def fake_gather(review_dir, mr, *, unresolved=False, file=None, thread=None, full=False):
        captured.update(mr=mr, unresolved=unresolved, file=file, thread=thread, full=full)
```

and replace the final assertion:

```python
    assert captured == {"mr": "7", "unresolved": True, "file": "src/x.py"}
```

with:

```python
    assert captured == {
        "mr": "7",
        "unresolved": True,
        "file": "src/x.py",
        "thread": None,
        "full": False,
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL — new commands don't exist (`No such command 'draft'`), and the updated filter test fails until `gather_status` is called with `thread`/`full`.

- [ ] **Step 3: Rewrite the `status` command as a shared impl + add the new commands**

In `src/mr_review/cli.py`, update the imports:

```python
from mr_review import draftwrite
from mr_review import publish as publish_mod
from mr_review import status as status_mod
from mr_review import sync as sync_mod
from mr_review.config import make_forge, repo_root, review_dir
from mr_review.domain import MergeRef
from mr_review.git import GitRunner
from mr_review.layout import state_path, thread_path
from mr_review.store import dict_to_position, load_state
```

Replace the entire `status` command function with the shared impl plus `status` and `show`:

```python
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
```

- [ ] **Step 4: Add the `_locate_thread_file` helper and the `draft`/`mark` commands**

Append to `src/mr_review/cli.py`:

```python
def _locate_thread_file(mr: str | None, repo: str | None, thread: int):
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
@click.option("--note", "note", type=int, default=None, help="Edit your own note N instead of replying.")
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
        raise click.ClickException("nothing to mark — pass --publish/--no-publish or --resolve/--no-resolve")
    path = _locate_thread_file(mr, repo, thread)
    try:
        new_text = draftwrite.set_flags(path.read_text(), publish=publish, resolve=resolve)
    except draftwrite.DraftError as e:
        raise click.ClickException(str(e)) from e
    path.write_text(new_text)
    click.echo(f"Marked thread {thread}.")


main.add_command(draft, name="reply")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS (new command tests + the updated filter test).

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add src/mr_review/cli.py tests/test_cli.py
git commit -m "$(cat <<'EOF'
Wire show/draft/reply/mark commands onto the helpers

Expose the read and write paths the agent needs: `show` (and `status
--full`) to read whole threads in one call, `draft`/`reply` to stage a
reply or note edit from stdin without ever naming a file, and `mark` to
flip publish/resolve at the explicit approval step. File location is by
local handle; bad handles, unsynced MRs, empty bodies, and non-own note
edits fail loud and write nothing.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Draft→sync stability test + README

**Files:**
- Modify: `tests/test_integration.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `draftwrite`, `sync`, `FakeForge`, `fake_git` (all existing).

- [ ] **Step 1: Write the failing stability test**

Add to `tests/test_integration.py` (check the top of the file for existing imports of `sync`, `MergeRef`, `FakeForge`, `fake_git`, and an `MR`/`disc` fixture; reuse them. If a `disc`/`MR` helper isn't already importable in this file, add the small local definitions shown below):

```python
from mr_review import draftwrite
from mr_review.domain import DiffPosition, Discussion, MergeRef, MergeRequest, Note
from mr_review.sync import sync
from tests.fakes import FakeForge, fake_git

_MR = MergeRequest("1", "t", "https://gitlab.com/g/r/-/merge_requests/1", "g/r", "B", "S", "H", "me")


def _disc():
    pos = DiffPosition("src/foo.py", "src/foo.py", 42, None, "B", "S", "H", None, "text")
    return Discussion(
        "d1",
        True,
        False,
        pos,
        (
            Note("501", "reviewer", False, False, "t", "t", "Why?", True, False),
            Note("502", "me", True, False, "t", "t", "canonical", True, False),
        ),
    )


def test_draft_then_sync_is_stable(tmp_path):
    # A drafted-and-marked file must be a fixed point under the next sync:
    # the draft is preserved AND the file is not reformatted (frontmatter order,
    # spacing, trailing newline all match what render produces).
    f = sync(FakeForge(_MR, [_disc()]), tmp_path, MergeRef(ref="1"), fake_git(), now="N").written[0]
    f.write_text(draftwrite.write_reply(f.read_text(), "Fixed, thanks.", publish=True))
    before = f.read_text()
    sync(FakeForge(_MR, [_disc()]), tmp_path, MergeRef(ref="1"), fake_git(), now="N")
    assert f.read_text() == before
```

- [ ] **Step 2: Run the test to verify behaviour**

Run: `uv run pytest tests/test_integration.py::test_draft_then_sync_is_stable -v`
Expected: PASS. (If it FAILS, the write helper's output diverges from `render` — diff the two strings; the cause is almost always trailing-newline or frontmatter-list formatting, not a logic bug in sync.)

- [ ] **Step 3: Document the new commands in the README**

In `README.md`, update the commands table (around line 125-129) to add `show`, and add `draft`/`reply` and `mark` rows. Replace the existing table body with:

```markdown
| Command | What it does |
| --- | --- |
| `mr-review sync [<mr>] [-R <repo>]` | Fetch discussions; (re)render thread files, preserving your drafts and flagging upstream changes with `⚠`. |
| `mr-review status [<mr>] [-R <repo>] [--json] [--unresolved] [--file <p>] [--thread <n>] [--full]` | Read-only summary of threads and pending actions. `--full` adds bodies, diff, and current draft. Posts nothing. |
| `mr-review show [<mr>] ...` | Alias for `status --full` (same filters). The discoverable way to read whole threads in one call. |
| `mr-review draft [<mr>] --thread <n> [--note <m>] [--publish] [--resolve]` | Stage a reply (or, with `--note`, edit your own note `m`) from **stdin**. Aliased as `reply`. |
| `mr-review mark [<mr>] --thread <n> [--publish] [--resolve]` | Flip publish/resolve flags without touching the body — for the explicit approval step. |
| `mr-review publish [<mr>] [-R <repo>] [--dry-run]` | Post everything marked ready, then re-sync. Non-interactive. `--dry-run` previews the plan. |
```

Then, in the "Drafting responses" section, after the bullet list of the three things you can stage, add a short paragraph:

```markdown
You can stage these from the CLI instead of editing files by hand — handy for
agents and scripts. Read a whole thread set with `mr-review show <mr>` (or
`status --full`), draft a reply with `echo "…" | mr-review draft <mr> --thread N`,
edit your own note with `… | mr-review draft <mr> --thread N --note M`, and flip
the publish flag at review time with `mr-review mark <mr> --thread N --publish`.
The body is read from stdin so multi-line Markdown needs no escaping; re-running
`draft` replaces the draft rather than appending.
```

- [ ] **Step 4: Run the full suite + lint, then commit**

Run: `uv run pytest` (whole suite) — Expected: PASS.
Run: `uv run ruff check . && uv run ruff format .`

```bash
git add tests/test_integration.py README.md
git commit -m "$(cat <<'EOF'
Pin draft→sync stability and document the new commands

Lock in that a drafted file survives the next sync byte-for-byte (the
guarantee that lets the agent draft freely without churn), and document
show/draft/reply/mark so the workflow is discoverable ahead of the skill.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- `status --full` content (bodies + diff + draft) → Task 2 (gather/format/json). ✓
- `show` alias → Task 3. ✓
- `--full --json` structured `notes`/`diff`/`draft`, non-full unchanged → Task 2 (`_thread_json`), tested. ✓
- `--thread N` filter → Task 2 (gather) + Task 3 (CLI option). ✓
- `draft` reply/edit via stdin, `--note` switch, idempotent, neutralization, body-required → Task 1 (helper) + Task 3 (CLI). ✓
- `--publish/--resolve` leave-as-is when omitted → Task 1 (`_apply`), tested. ✓
- `mark` body-free flag flip, ≥1 flag required → Task 3. ✓
- `reply` alias → Task 3 (`add_command`). ✓
- Frontmatter stability across sync → Task 1 (shared `dump_frontmatter`) + Task 4 (integration test). ✓
- Fail-loud: unsynced, missing thread, non-own note, empty stdin → Task 3, tested. ✓
- New write helper module / render serializer reuse → Task 1. ✓
- Skill doc explicitly out of scope → not a task (correct). ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every run step shows the command and expected result.

**Type consistency:** `gather_status(..., thread=None, full=False)` signature is identical in Task 2 (def), Task 3 (`_run_status` call), and the updated `fake_gather`. `ThreadStatus` full fields (`diff`/`notes`/`draft`) and `StatusReport.full` defined in Task 2 are consumed by `_thread_json`/`_append_full` in the same task. `draftwrite` function names (`write_reply`, `write_note_edit`, `set_flags`, `DraftError`) match between Task 1 (def) and Task 3 (calls). `markers.DRAFT_LINE` and `render.dump_frontmatter` defined in Task 1 are used by Task 1's `draftwrite` and Task 2's status import (`PUBLISHED_PREFIX`) respectively. Note handle/thread handle naming (`local_id` → JSON `handle`) is consistent with the spec's `--full --json` example.
