# Richer `status` Overview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `mr-review status` a rich, live overview — per-thread reviewer, first-comment excerpt, note count, and draft state (ready/WIP/clean) plus a summary header and `--unresolved`/`--file` filters — without new forge calls or schema changes.

**Architecture:** Enrich the existing read-only `status` path only (`status.py` + the `status` CLI command). All new data is derived at call time from the loaded `StateDoc` threads, the parsed draft files, and `plan_thread` — so it never goes stale. Two renderings: human text and additive `--json`.

**Tech Stack:** Python 3.14, `click`, stdlib `dataclasses`. Existing modules: `store` (`StateDoc`/`StoredThread`/`StoredNote`, `dict_to_position`, `position_is_outdated`, `load_state`), `layout` (`line_label`, `state_path`, `thread_path`), `parse` (`parse_thread`/`ParsedThread`/`ParseError`), `plan` (`plan_thread`).

## Global Constraints

- Python **3.14+**; managed with `uv`. Run tests with `uv run pytest`.
- Runtime deps unchanged (`click`, `pyyaml`). **No new dependencies. No new forge/network calls** — `status` reads only local state + draft files.
- **Lint, format, and types must pass.** This repo has pre-commit hooks (`pyrefly` type check, `ruff check`, `ruff format`, `uv-lock`) that run on `git commit` and must pass. Before committing run `uv run ruff check --fix .`, `uv run ruff format .`, and `uv run pyrefly check` (or `uvx pyrefly check`); annotate new fields/params so pyrefly is clean. Ruff config: `target-version="py314"`, `line-length=100`, `lint.select=["E","F","I","UP","W"]`, `lint.ignore=["E501"]`.
- Tests assert **behaviour through real interfaces** (FakeForge + `sync` into a temp dir, then `gather_status`/renderers on the result), never code shape.
- `status` stays **read-only** (no forge writes, no posting). `--json` output is **additive** — existing `actions`/`warnings` keys keep their meaning; do not remove them.
- Draft-state precedence: `ready` > `wip` > `clean`. Summary counts are **numbers of threads** per category over the (post-filter) set.
- Preserve the existing `outdated` field/behaviour (added since the base design).

---

## File Structure

- `src/mr_review/status.py` — **rewritten display/data layer.** `ThreadStatus` gains `reviewers`/`note_count`/`excerpt`/`draft_state` and `file` becomes the *source* path (None for general); `StatusReport` gains `summary` and `filter`; `gather_status` computes the new fields, classifies draft state, and applies filters; `format_status`/`status_json` render them. (One module, one responsibility — the status overview.)
- `src/mr_review/cli.py` — the `status` command gains `--unresolved` / `--file` options, threaded into `gather_status`.
- `tests/test_status.py` — extend/update (module-level behaviour, incl. filters).
- `tests/test_cli.py` — add a CLI pass-through test for the new options.

---

## Task 1: Rich `status` data + renderers + filters (`status.py`)

**Files:**
- Modify (rewrite): `src/mr_review/status.py`
- Test: `tests/test_status.py` (update one existing test, add new ones)

**Interfaces:**
- Consumes: `load_state`, `state_path`, `thread_path`, `dict_to_position`, `position_is_outdated` (store/layout); `parse_thread`/`ParsedThread`/`ParseError` (parse); `plan_thread` (plan). `StoredThread.notes: list[StoredNote]` where `StoredNote` has `.author: str` and `.body: str`; `StateDoc.current_user: str`, `StateDoc.head_sha: str`.
- Produces:
  - `ThreadStatus(local_id: int, file: str | None, line: str, resolved: bool, reviewers: list[str], note_count: int, excerpt: str, draft_state: str, outdated: bool = False, actions: list = [], warnings: list = [])`
  - `StatusReport(mr: str, summary: dict = {}, filter: dict = {}, threads: list = [])`
  - `gather_status(review_dir: Path, mr: str, *, unresolved: bool = False, file: str | None = None) -> StatusReport`
  - `status_json(report: StatusReport) -> dict` — `{"mr","summary","filter","threads":[asdict(t)...]}`
  - `format_status(report: StatusReport) -> str`
  - `draft_state` ∈ `"clean" | "wip" | "ready"`.

- [ ] **Step 1: Write/﻿update the tests**

Update the existing reply test (status no longer prints the reply *body*; it prints a `[reply ready]` tag — the body lives in `--json` `actions`). Replace `test_status_reports_pending_reply` in `tests/test_status.py` with:

```python
def test_status_reports_pending_reply(tmp_path):
    f = synced(tmp_path)
    text = f.read_text().replace("publish: false", "publish: true").rstrip() + "\nReady reply.\n"
    f.write_text(text)
    report = gather_status(tmp_path, "1")
    data = status_json(report)
    t0 = data["threads"][0]
    assert t0["draft_state"] == "ready"
    assert t0["actions"][0]["type"] == "ReplyAction"
    assert t0["actions"][0]["body"] == "Ready reply."   # body is in --json
    assert "[reply ready]" in format_status(report)      # text shows a tag, not the body
```

Then add these tests (reuse the existing `MR`, `disc`, `synced` helpers at the top of the file):

```python
def mine_only_disc():
    # a general (non-diff) thread whose only note is the current user's
    return Discussion(
        "dm", False, False, None,
        (Note("900", "me", True, False, "t", "t", "my own note", False, False),),
    )


def test_clean_when_no_drafts(tmp_path):
    synced(tmp_path)
    t0 = status_json(gather_status(tmp_path, "1"))["threads"][0]
    assert t0["draft_state"] == "clean"
    assert t0["actions"] == []


def test_wip_when_reply_present_but_not_marked(tmp_path):
    f = synced(tmp_path)
    f.write_text(f.read_text().rstrip() + "\nDraft in progress, not ready.\n")  # publish stays false
    report = gather_status(tmp_path, "1")
    assert status_json(report)["threads"][0]["draft_state"] == "wip"
    assert "[draft: not ready]" in format_status(report)


def test_reviewers_excludes_current_user(tmp_path):
    # disc() has a "reviewer" note and a "me" note; current_user is "me"
    report = gather_status(synced(tmp_path) and tmp_path, "1")
    t0 = status_json(report)["threads"][0]
    assert t0["reviewers"] == ["reviewer"]
    assert "@reviewer" in format_status(report)


def test_reviewers_self_when_all_mine(tmp_path):
    sync(FakeForge(MR, [mine_only_disc()]), tmp_path, MergeRef(ref="1"), fake_git(), now="N")
    report = gather_status(tmp_path, "1")
    assert status_json(report)["threads"][0]["reviewers"] == []
    assert "(self)" in format_status(report)


def test_excerpt_is_first_note_truncated(tmp_path):
    long = "x" * 200
    d = Discussion("dl", True, False,
                   DiffPosition("a.py", "a.py", 1, None, "B", "S", "H", None, "text"),
                   (Note("1", "reviewer", False, False, "t", "t", long, True, False),))
    sync(FakeForge(MR, [d]), tmp_path, MergeRef(ref="1"), fake_git(), now="N")
    excerpt = status_json(gather_status(tmp_path, "1"))["threads"][0]["excerpt"]
    assert excerpt.endswith("…") and len(excerpt) <= 80


def test_note_count(tmp_path):
    synced(tmp_path)
    report = gather_status(tmp_path, "1")
    assert status_json(report)["threads"][0]["note_count"] == 2
    assert "2 notes" in format_status(report)


def test_warning_surfaced_for_unmarked_edit(tmp_path):
    f = synced(tmp_path)
    # edit my own note body (handle 2) WITHOUT listing it in edit_notes -> warning
    f.write_text(f.read_text().replace("canonical", "secretly changed"))
    report = gather_status(tmp_path, "1")
    t0 = status_json(report)["threads"][0]
    assert t0["warnings"]
    assert report.summary["warnings"] == 1


def test_summary_counts(tmp_path):
    f = synced(tmp_path)
    f.write_text(f.read_text().replace("publish: false", "publish: true").rstrip() + "\nyep\n")
    s = status_json(gather_status(tmp_path, "1"))["summary"]
    assert s == {"threads": 1, "unresolved": 1, "ready": 1, "wip": 0, "warnings": 0}


def test_json_is_additive(tmp_path):
    synced(tmp_path)
    data = status_json(gather_status(tmp_path, "1"))
    assert set(data) == {"mr", "summary", "filter", "threads"}
    t0 = data["threads"][0]
    for k in ("reviewers", "note_count", "excerpt", "draft_state", "actions", "warnings", "outdated"):
        assert k in t0
```

Filtering tests (multi-thread setup):

```python
def multi_forge():
    foo = Discussion("a", True, False,
                     DiffPosition("src/foo.py", "src/foo.py", 1, None, "B", "S", "H", None, "text"),
                     (Note("1", "reviewer", False, False, "t", "t", "on foo", True, False),))
    bar = Discussion("b", True, True,   # resolved
                     DiffPosition("src/bar.py", "src/bar.py", 2, None, "B", "S", "H", None, "text"),
                     (Note("2", "reviewer", False, False, "t", "t", "on bar", True, True),))
    gen = Discussion("c", False, False, None,
                     (Note("3", "reviewer", False, False, "t", "t", "general", False, False),))
    return FakeForge(MR, [foo, bar, gen])


def synced_multi(tmp_path):
    sync(multi_forge(), tmp_path, MergeRef(ref="1"), fake_git(), now="N")


def test_filter_unresolved(tmp_path):
    synced_multi(tmp_path)
    report = gather_status(tmp_path, "1", unresolved=True)
    assert all(not t.resolved for t in report.threads)
    assert {t.local_id for t in report.threads} == {1, 3}   # foo + general (bar resolved)
    assert report.summary["threads"] == 2


def test_filter_file_excludes_general_and_other_files(tmp_path):
    synced_multi(tmp_path)
    report = gather_status(tmp_path, "1", file="src/foo.py")
    assert [t.file for t in report.threads] == ["src/foo.py"]
    assert report.filter == {"unresolved": False, "file": "src/foo.py"}


def test_filters_compose(tmp_path):
    synced_multi(tmp_path)
    # unresolved + file=bar -> bar is resolved, so empty
    report = gather_status(tmp_path, "1", unresolved=True, file="src/bar.py")
    assert report.threads == []
    assert report.summary["threads"] == 0
```

- [ ] **Step 2: Run the tests — verify they fail**

Run: `uv run pytest tests/test_status.py -v`
Expected: FAIL (new fields/params/behaviour not implemented; e.g. `TypeError: gather_status() got an unexpected keyword argument 'unresolved'`, `KeyError: 'summary'`, missing `[reply ready]`).

- [ ] **Step 3: Rewrite `src/mr_review/status.py`**

```python
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mr_review.layout import line_label, state_path, thread_path
from mr_review.parse import ParsedThread, ParseError, parse_thread
from mr_review.plan import plan_thread
from mr_review.store import dict_to_position, load_state, position_is_outdated

_EXCERPT_LEN = 80


@dataclass
class ThreadStatus:
    local_id: int
    file: str | None
    line: str
    resolved: bool
    reviewers: list[str]
    note_count: int
    excerpt: str
    draft_state: str
    outdated: bool = False
    actions: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


@dataclass
class StatusReport:
    mr: str
    summary: dict = field(default_factory=dict)
    filter: dict = field(default_factory=dict)
    threads: list = field(default_factory=list)


def _excerpt(body: str) -> str:
    text = " ".join(body.split())
    return text[: _EXCERPT_LEN - 1] + "…" if len(text) > _EXCERPT_LEN else text


def _reviewers(notes: list, current_user: str) -> list[str]:
    return sorted({n.author for n in notes if n.author != current_user})


def _summary(threads: list) -> dict:
    return {
        "threads": len(threads),
        "unresolved": sum(1 for t in threads if not t.resolved),
        "ready": sum(1 for t in threads if t.draft_state == "ready"),
        "wip": sum(1 for t in threads if t.draft_state == "wip"),
        "warnings": sum(1 for t in threads if t.warnings),
    }


def gather_status(
    review_dir: Path, mr: str, *, unresolved: bool = False, file: str | None = None
) -> StatusReport:
    state = load_state(state_path(review_dir, mr))
    report = StatusReport(mr=mr, filter={"unresolved": unresolved, "file": file})
    if state is None:
        report.summary = _summary([])
        return report
    for thread in state.threads:
        if unresolved and thread.resolved:
            continue
        pos = dict_to_position(thread.position)
        if file is not None:
            paths = {p for p in ((pos.new_path, pos.old_path) if pos else ()) if p}
            if file not in paths:
                continue
        source_file = (pos.new_path or pos.old_path) if pos else None
        path = thread_path(review_dir, mr, thread.local_id, pos)
        outdated = position_is_outdated(thread.position, state.head_sha)
        reviewers = _reviewers(thread.notes, state.current_user)
        note_count = len(thread.notes)
        excerpt = _excerpt(thread.notes[0].body) if thread.notes else ""
        if path.exists():
            try:
                parsed = parse_thread(path.read_text())
            except ParseError as e:
                report.threads.append(
                    ThreadStatus(
                        local_id=thread.local_id,
                        file=source_file,
                        line=line_label(pos),
                        resolved=thread.resolved,
                        reviewers=reviewers,
                        note_count=note_count,
                        excerpt=excerpt,
                        draft_state="clean",
                        outdated=outdated,
                        warnings=[f"parse error: {e}"],
                    )
                )
                continue
        else:
            parsed = ParsedThread(frontmatter={}, reply="", note_edits={})
        plan = plan_thread(parsed, thread)
        actions = [{"type": type(a).__name__, **asdict(a)} for a in plan.actions]
        if actions:
            draft_state = "ready"
        elif parsed.reply.strip():
            draft_state = "wip"
        else:
            draft_state = "clean"
        report.threads.append(
            ThreadStatus(
                local_id=thread.local_id,
                file=source_file,
                line=line_label(pos),
                resolved=thread.resolved,
                reviewers=reviewers,
                note_count=note_count,
                excerpt=excerpt,
                draft_state=draft_state,
                outdated=outdated,
                actions=actions,
                warnings=[w.message for w in plan.warnings],
            )
        )
    report.summary = _summary(report.threads)
    return report


def status_json(report: StatusReport) -> dict:
    return {
        "mr": report.mr,
        "summary": report.summary,
        "filter": report.filter,
        "threads": [asdict(t) for t in report.threads],
    }


def _location(t: ThreadStatus) -> str:
    return f"{t.file}:{t.line}" if t.file else "general"


def _notes_label(n: int) -> str:
    return f"{n} note" if n == 1 else f"{n} notes"


def _draft_tag(t: ThreadStatus) -> str:
    if t.draft_state == "ready":
        present = {a["type"] for a in t.actions}
        kinds = [
            label
            for name, label in (
                ("ReplyAction", "reply ready"),
                ("EditAction", "edit ready"),
                ("ResolveAction", "resolve ready"),
            )
            if name in present
        ]
        return f" · [{', '.join(kinds)}]"
    if t.draft_state == "wip":
        return " · [draft: not ready]"
    return ""


def format_status(report: StatusReport) -> str:
    s = report.summary
    lines = [
        f"MR !{report.mr} — {s['threads']} thread(s): {s['unresolved']} unresolved, "
        f"{s['ready']} ready to publish, {s['wip']} WIP, {s['warnings']} warnings"
    ]
    active = []
    if report.filter.get("unresolved"):
        active.append("unresolved")
    if report.filter.get("file"):
        active.append(f"file={report.filter['file']}")
    if active:
        lines.append(f"  (filtered: {', '.join(active)})")
    for t in report.threads:
        state = "resolved" if t.resolved else "unresolved"
        reviewer = ", ".join(f"@{r}" for r in t.reviewers) if t.reviewers else "(self)"
        outdated = " · outdated" if t.outdated else ""
        lines.append(
            f"  thread {t.local_id} · {reviewer} · {_location(t)} · {state}{outdated} · "
            f"{_notes_label(t.note_count)}{_draft_tag(t)}"
        )
        if t.excerpt:
            lines.append(f'      "{t.excerpt}"')
        for w in t.warnings:
            lines.append(f"      ⚠ {w}")
    if s.get("ready", 0) == 0:
        lines.append("  (nothing marked ready)")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests + lint + types — verify pass**

Run: `uv run pytest tests/test_status.py -v && uv run ruff check src tests && uv run ruff format --check . && uv run pyrefly check`
Expected: all status tests PASS; ruff clean; pyrefly reports no errors. (If `pyrefly` isn't on PATH, use `uvx pyrefly check`.) Then run the full suite: `uv run pytest -q` — all green (the only intentionally changed existing test is `test_status_reports_pending_reply`, updated in Step 1; `test_status_marks_outdated` and `test_status_reports_nothing_when_no_drafts` still pass).

- [ ] **Step 5: Commit**

```bash
git add src/mr_review/status.py tests/test_status.py
git commit -m "Enrich status: reviewer, excerpt, note count, draft state, summary, filters

status is the lay-of-the-land overview for triage; compute reviewer(s),
first-comment excerpt, note count, and ready/WIP/clean draft state plus a
summary header and --unresolved/--file filters, all from local state with
no new forge calls. file now reports the source path (None for general)."
```

---

## Task 2: Wire `--unresolved` / `--file` into the `status` CLI command

**Files:**
- Modify: `src/mr_review/cli.py` (the `status` command)
- Test: `tests/test_cli.py` (add a pass-through test)

**Interfaces:**
- Consumes: `gather_status(review_dir, mr, *, unresolved, file)` (Task 1); existing `_context`, `make_forge`, `_resolve_iid`, `status_mod.status_json`, `status_mod.format_status`.
- Produces: `status` command accepts `--unresolved` (flag) and `--file <path>` and forwards them.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
def test_status_cli_passes_filters(monkeypatch, tmp_path):
    from mr_review import cli
    from mr_review.status import StatusReport

    captured = {}

    def fake_gather(review_dir, mr, *, unresolved=False, file=None):
        captured.update(mr=mr, unresolved=unresolved, file=file)
        r = StatusReport(mr=mr)
        r.summary = {"threads": 0, "unresolved": 0, "ready": 0, "wip": 0, "warnings": 0}
        r.filter = {"unresolved": unresolved, "file": file}
        return r

    monkeypatch.setattr(cli, "_context", lambda: tmp_path)
    monkeypatch.setattr(cli, "make_forge", lambda: object())
    monkeypatch.setattr(cli.status_mod, "gather_status", fake_gather)

    from click.testing import CliRunner

    res = CliRunner().invoke(cli.main, ["status", "7", "--unresolved", "--file", "src/x.py"])
    assert res.exit_code == 0, res.output
    assert captured == {"mr": "7", "unresolved": True, "file": "src/x.py"}
```

(A numeric `mr` of `"7"` means `_resolve_iid` returns it directly without touching the dummy forge.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_status_cli_passes_filters -v`
Expected: FAIL — `no such option: --unresolved`.

- [ ] **Step 3: Add the options to the `status` command**

In `src/mr_review/cli.py`, replace the `status` command with:

```python
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
```

- [ ] **Step 4: Run tests + lint + types — verify pass**

Run: `uv run pytest tests/test_cli.py -v && uv run ruff check src tests && uv run ruff format --check . && uv run pyrefly check`
Expected: PASS; clean. Then `uv run pytest -q` — full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/mr_review/cli.py tests/test_cli.py
git commit -m "Add --unresolved and --file filters to the status command

Forward the flags to gather_status so large MRs can be narrowed to
unresolved threads or a single source file."
```

---

## Self-Review

**Spec coverage:**
- Reviewer(s), excerpt, note count, draft state, baseline fields → Task 1 (`ThreadStatus`, `gather_status`). ✓
- Summary header with counts → Task 1 (`_summary`, `format_status`, `status_json`). ✓
- Draft-state model ready/wip/clean (precedence) → Task 1 (`gather_status` classification; tests `test_*_wip/clean/ready`). ✓
- WIP = reply-only (reply text, `publish: false`) → Task 1 (`parsed.reply.strip()` branch; `test_wip_when_reply_present_but_not_marked`). ✓
- Warnings shown independently → Task 1 (`warnings` retained, counted; `test_warning_surfaced_for_unmarked_edit`). ✓
- Reviewers = non-self authors, `(self)` when all yours → Task 1 (`_reviewers`; `test_reviewers_*`). ✓
- Excerpt first note, newline-collapsed, ~80 truncate → Task 1 (`_excerpt`; `test_excerpt_is_first_note_truncated`). ✓
- `--unresolved` / `--file`, composable, exclude general on file → Task 1 (filter logic + tests) & Task 2 (CLI). ✓
- Summary reflects filtered set → Task 1 (`_summary(report.threads)`; `test_filters_compose`/`test_filter_unresolved`). ✓
- `--json` additive (`summary`,`filter`,new per-thread fields; keep `actions`/`warnings`) → Task 1 (`status_json`; `test_json_is_additive`). ✓
- No new forge calls / read-only / no schema change → Task 1 reads only local state. ✓
- Preserve `outdated` → Task 1 keeps the field/segment; `test_status_marks_outdated` stays green. ✓
- Error handling unchanged (ParseError → per-thread warning, missing file → clean) → Task 1 (ParseError branch sets `draft_state="clean"` + warning; no-file branch yields clean). ✓

**Placeholder scan:** none — every step has complete code and exact commands.

**Type consistency:** `gather_status(review_dir, mr, *, unresolved=False, file=None)` identical in Task 1 (def + tests) and Task 2 (CLI call + fake). `ThreadStatus`/`StatusReport` field names match between `status.py`, `status_json` (`asdict`), and the tests. `draft_state` string values (`clean`/`wip`/`ready`) consistent across classifier, `_draft_tag`, `_summary`, and tests. Note: `file` changes meaning from the `.md` filename to the source path (None for general) — the only intentional breaking change, covered by updating `test_status_reports_pending_reply` and asserted by the filter/excerpt/json tests.
