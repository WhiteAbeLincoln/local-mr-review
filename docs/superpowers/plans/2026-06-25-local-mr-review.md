# local-mr-review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python CLI that mirrors a GitLab merge request's review discussions into locally editable markdown files, lets the author (or an AI agent) draft replies and edits, and publishes them back via `glab` with explicit, marker-gated confirmation.

**Architecture:** Ports & adapters. A forge-neutral core (state, render, parse, plan, sync/status/publish) depends only on domain dataclasses and a `Forge` protocol; a single `GitLabForge` adapter shells out to `glab mr note`/`glab mr view`. Canonical server state is persisted as JSON in a hidden `.state/` dir; markdown thread files are a regenerated projection plus local-only draft regions. Forge-native ids never appear in files — files use stable local handles mapped to native ids in the sidecar.

**Tech Stack:** Python 3.14+, `uv` project, `click` (CLI), `pyyaml` (frontmatter), `pytest` (tests), `ruff` (lint + format). External `glab` and `git` binaries, invoked through injectable runner objects so tests never touch the network or shell.

## Global Constraints

- Python **3.14+**; managed with `uv` (`pyproject.toml`, `uv sync`, `uv run`). Run tests with `uv run pytest`.
- Runtime deps: `click`, `pyyaml`. Dev deps: `pytest`, `ruff`. No others without cause (YAGNI).
- **Linting and formatting must pass after every task.** Before each commit run `uv run ruff check --fix .` and `uv run ruff format .`, then confirm `uv run ruff check .` and `uv run ruff format --check .` are clean. Ruff config (in `pyproject.toml`): `target-version = "py314"`, `line-length = 100`, `lint.select = ["E","F","I","UP","W"]`, `lint.ignore = ["E501"]`. Note `ruff` may rewrite transcribed code (import sorting, `Callable` → `collections.abc`, dropping needless quoted annotations); that is expected — commit the formatted result.
- **No bare `assert` for runtime validation in production code, and no `sys.exit`/`raise SystemExit` deep in library code.** Raise typed exceptions (`ForgeError`, `ParseError`) and let the CLI layer decide. (`assert` is allowed in tests.)
- All external-process access (`glab`, `git`) goes through injectable runner objects (`GlabRunner`, `GitRunner`); production defaults shell out, tests inject fakes. No test hits the network.
- Tests assert **behaviour through real interfaces**, never code shape (no "field exists"/"is exported" tests). Drive the core through a `FakeForge` and temp dirs; assert on rendered files, parsed actions, and recorded forge calls.
- Marker namespace is the literal string `mr-review:` inside HTML comments. All control flags live in YAML frontmatter. The published region is **never parsed back**; canonical JSON is the source of truth for published bodies.
- Every forge-native id is an **opaque `str`** in the domain model (GitLab note ids arrive as JSON integers — convert to `str` at the adapter boundary).
- Frequent commits: one commit per task (the final step of each task).

---

## File Structure

```
local-mr-review/
  pyproject.toml
  src/mr_review/
    __init__.py
    cli.py            # click group + sync/status/publish commands
    config.py         # repo-root discovery, review-dir, forge factory
    domain.py         # frozen dataclasses + derive_resolution()
    markers.py        # marker constants + neutralize()
    git.py            # GitRunner (git show / rev-parse), GitError
    forge/
      __init__.py
      base.py         # Forge Protocol
      glab.py         # GlabRunner + ForgeError
      gitlab.py       # GitLabForge adapter (maps glab JSON <-> domain)
    store.py          # StoredNote/StoredThread/StateDoc, load/save, assign_handles
    layout.py         # thread/state paths, slug, line label, .gitignore bootstrap
    diffcontext.py    # read_blob + format_hunk + build_context
    render.py         # RenderInputs + render_thread (+ frontmatter, link, escape)
    parse.py          # ParsedThread + parse_thread (fail-loud) + ParseError
    plan.py           # action dataclasses + plan_thread
    sync.py           # sync() orchestration (safe-merge, conflict flags)
    status.py         # status() + format_status + status_json
    publish.py        # publish() (execute actions, clear drafts, re-sync)
  tests/
    fakes.py          # FakeForge, fake runners
    fixtures/         # captured glab JSON samples
    test_*.py
```

---

## Task 1: Project scaffold & CLI skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `src/mr_review/__init__.py`
- Create: `src/mr_review/cli.py`
- Test: `tests/test_cli_skeleton.py`

**Interfaces:**
- Produces: `mr_review.cli:main` — a `click.Group` with `sync`, `status`, `publish` subcommands (bodies stubbed). Console script `mr-review` → `mr_review.cli:main`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "mr-review"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = ["click>=8.1", "pyyaml>=6.0"]

[project.scripts]
mr-review = "mr_review.cli:main"

[dependency-groups]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/mr_review"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_cli_skeleton.py
from click.testing import CliRunner
from mr_review.cli import main

def test_help_lists_the_three_commands():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    for cmd in ("sync", "status", "publish"):
        assert cmd in result.output

def test_subcommand_accepts_optional_mr_and_repo():
    # sync with an mr ref and repo override parses without error at the CLI layer
    result = CliRunner().invoke(main, ["sync", "123", "-R", "grp/repo"])
    # stub raises NotImplementedError -> click reports non-zero but parsed args first
    assert "no such option" not in result.output.lower()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_skeleton.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mr_review.cli'`.

- [ ] **Step 4: Write minimal implementation**

```python
# src/mr_review/__init__.py
__version__ = "0.1.0"
```

```python
# src/mr_review/cli.py
import click

@click.group()
def main() -> None:
    """Manage GitLab merge request reviews locally."""

@main.command()
@click.argument("mr", required=False)
@click.option("-R", "--repo", default=None, help="OWNER/REPO override passed to the forge.")
def sync(mr: str | None, repo: str | None) -> None:
    """Pull discussions into local thread files."""
    raise NotImplementedError

@main.command()
@click.argument("mr", required=False)
@click.option("-R", "--repo", default=None)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def status(mr: str | None, repo: str | None, as_json: bool) -> None:
    """Show drafted replies/edits and what is marked ready."""
    raise NotImplementedError

@main.command()
@click.argument("mr", required=False)
@click.option("-R", "--repo", default=None)
@click.option("--dry-run", is_flag=True, help="Show the publish plan without posting.")
def publish(mr: str | None, repo: str | None, dry_run: bool) -> None:
    """Post ready replies/edits/resolves to GitLab."""
    raise NotImplementedError
```

- [ ] **Step 5: Run tests and verify they pass**

Run: `uv run pytest tests/test_cli_skeleton.py -v && uv run mr-review --help`
Expected: PASS; `--help` prints the command list.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/mr_review tests/test_cli_skeleton.py
git commit -m "Scaffold uv project and CLI command surface

Establish the package, console script, and the sync/status/publish
command shells so later tasks can fill in behaviour against a stable CLI."
```

---

## Task 2: glab runner & ForgeError

**Files:**
- Create: `src/mr_review/forge/__init__.py` (empty)
- Create: `src/mr_review/forge/glab.py`
- Test: `tests/test_glab.py`

**Interfaces:**
- Produces:
  - `ForgeError(RuntimeError)` with attributes `args_`, `returncode`, `stderr`.
  - `GlabRunner(exec_runner=None)` where `exec_runner(args: list[str], input: str | None) -> tuple[int, str, str]` returns `(returncode, stdout, stderr)`. Default shells out to `glab`.
  - `GlabRunner.run(args: list[str], stdin: str | None = None) -> str` — returns stdout, raises `ForgeError` on non-zero exit.
  - `GlabRunner.json(args: list[str]) -> object` — `json.loads(self.run(args))`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_glab.py
import pytest
from mr_review.forge.glab import GlabRunner, ForgeError

def make_runner(returncode, stdout="", stderr=""):
    calls = []
    def exec_runner(args, input):
        calls.append((args, input))
        return (returncode, stdout, stderr)
    return GlabRunner(exec_runner=exec_runner), calls

def test_run_returns_stdout_and_forwards_args_and_stdin():
    runner, calls = make_runner(0, stdout="ok\n")
    out = runner.run(["mr", "note", "create", "1", "--reply", "abc"], stdin="hello")
    assert out == "ok\n"
    assert calls == [(["mr", "note", "create", "1", "--reply", "abc"], "hello")]

def test_run_raises_forgeerror_with_stderr_on_failure():
    runner, _ = make_runner(1, stderr="401 Unauthorized")
    with pytest.raises(ForgeError) as ei:
        runner.run(["mr", "view", "1"])
    assert ei.value.returncode == 1
    assert "401 Unauthorized" in ei.value.stderr

def test_json_parses_stdout():
    runner, _ = make_runner(0, stdout='[{"id": 1}]')
    assert runner.json(["mr", "note", "list"]) == [{"id": 1}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_glab.py -v`
Expected: FAIL — module/attributes not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# src/mr_review/forge/glab.py
import json
import subprocess
from typing import Callable

ExecRunner = Callable[[list[str], "str | None"], tuple[int, str, str]]

class ForgeError(RuntimeError):
    def __init__(self, args_: list[str], returncode: int, stderr: str) -> None:
        self.args_ = args_
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"glab {' '.join(args_)} failed ({returncode}): {stderr.strip()}")

def _subprocess_exec(args: list[str], input: str | None) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["glab", *args], input=input, capture_output=True, text=True
    )
    return proc.returncode, proc.stdout, proc.stderr

class GlabRunner:
    def __init__(self, exec_runner: ExecRunner | None = None) -> None:
        self._exec = exec_runner or _subprocess_exec

    def run(self, args: list[str], stdin: str | None = None) -> str:
        rc, out, err = self._exec(args, stdin)
        if rc != 0:
            raise ForgeError(args, rc, err)
        return out

    def json(self, args: list[str]) -> object:
        return json.loads(self.run(args))
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `uv run pytest tests/test_glab.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mr_review/forge tests/test_glab.py
git commit -m "Add injectable glab runner with typed ForgeError

All glab access funnels through one runner so the adapter is testable
without a network or the glab binary, and failures surface stderr."
```

---

## Task 3: Domain models, port, and resolution derivation

**Files:**
- Create: `src/mr_review/domain.py`
- Create: `src/mr_review/forge/base.py`
- Test: `tests/test_domain.py`

**Interfaces:**
- Produces (frozen dataclasses, all ids `str`):
  - `MergeRef(ref: str | None, repo: str | None = None)`
  - `DiffPosition(new_path, old_path, new_line, old_line, base_sha, start_sha, head_sha, line_range, position_type)` — paths `str|None`, lines `int|None`, shas `str`, `line_range: tuple[int,int]|None` (new-side start,end), `position_type: str`.
  - `Note(native_id: str, author: str, mine: bool, system: bool, created_at: str, updated_at: str, body: str, resolvable: bool, resolved: bool)`
  - `Discussion(native_id: str, resolvable: bool, resolved: bool, position: DiffPosition | None, notes: tuple[Note, ...])`
  - `MergeRequest(iid: str, title: str, web_url: str, project: str, base_sha: str, start_sha: str, head_sha: str, current_user: str)`
  - `derive_resolution(notes: Iterable[Note]) -> tuple[bool, bool]` — `(resolvable, resolved)`.
  - `Forge` Protocol with `fetch_mr`, `list_discussions`, `reply`, `edit_note`, `set_resolved`.

- [ ] **Step 1: Write the failing test** (behaviour: resolution derivation rules)

```python
# tests/test_domain.py
from mr_review.domain import Note, derive_resolution

def note(resolvable, resolved):
    return Note(native_id="n", author="a", mine=False, system=False,
                created_at="t", updated_at="t", body="b",
                resolvable=resolvable, resolved=resolved)

def test_thread_resolvable_when_any_note_is_resolvable():
    assert derive_resolution([note(True, False), note(False, False)]) == (True, False)

def test_thread_resolved_only_when_all_resolvable_notes_resolved():
    assert derive_resolution([note(True, True), note(True, True)]) == (True, True)
    assert derive_resolution([note(True, True), note(True, False)]) == (True, False)

def test_non_resolvable_thread_is_unresolvable_and_not_resolved():
    assert derive_resolution([note(False, False)]) == (False, False)
    assert derive_resolution([]) == (False, False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_domain.py -v`
Expected: FAIL — `derive_resolution` not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# src/mr_review/domain.py
from dataclasses import dataclass
from typing import Iterable, Protocol

@dataclass(frozen=True)
class MergeRef:
    ref: str | None
    repo: str | None = None

@dataclass(frozen=True)
class DiffPosition:
    new_path: str | None
    old_path: str | None
    new_line: int | None
    old_line: int | None
    base_sha: str
    start_sha: str
    head_sha: str
    line_range: tuple[int, int] | None
    position_type: str

@dataclass(frozen=True)
class Note:
    native_id: str
    author: str
    mine: bool
    system: bool
    created_at: str
    updated_at: str
    body: str
    resolvable: bool
    resolved: bool

@dataclass(frozen=True)
class Discussion:
    native_id: str
    resolvable: bool
    resolved: bool
    position: DiffPosition | None
    notes: tuple[Note, ...]

@dataclass(frozen=True)
class MergeRequest:
    iid: str
    title: str
    web_url: str
    project: str
    base_sha: str
    start_sha: str
    head_sha: str
    current_user: str

def derive_resolution(notes: Iterable[Note]) -> tuple[bool, bool]:
    resolvable_notes = [n for n in notes if n.resolvable]
    if not resolvable_notes:
        return (False, False)
    return (True, all(n.resolved for n in resolvable_notes))
```

```python
# src/mr_review/forge/base.py
from typing import Protocol
from mr_review.domain import Discussion, MergeRef, MergeRequest

class Forge(Protocol):
    def fetch_mr(self, mr: MergeRef) -> MergeRequest: ...
    def list_discussions(self, mr: MergeRef) -> list[Discussion]: ...
    def reply(self, mr: MergeRef, discussion_id: str, body: str) -> None: ...
    def edit_note(self, mr: MergeRef, discussion_id: str, note_id: str, body: str) -> None: ...
    def set_resolved(self, mr: MergeRef, discussion_id: str, resolved: bool) -> None: ...
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `uv run pytest tests/test_domain.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mr_review/domain.py src/mr_review/forge/base.py tests/test_domain.py
git commit -m "Add forge-neutral domain model, port, and resolution rule

GitLab tracks resolution per note; derive_resolution centralises the
thread-level rule (resolvable if any note is, resolved if all are)."
```

---

## Task 4: GitLab adapter — reads (`fetch_mr`, `list_discussions`)

**Files:**
- Create: `tests/fixtures/mr_notes.json`
- Create: `tests/fixtures/mr_view.json`
- Create: `src/mr_review/forge/gitlab.py`
- Test: `tests/test_gitlab_reads.py`

**Interfaces:**
- Consumes: `GlabRunner` (Task 2); domain types + `derive_resolution` (Task 3).
- Produces: `GitLabForge(glab: GlabRunner)` implementing `fetch_mr` and `list_discussions`.
  - `_mr_args(mr: MergeRef) -> list[str]` → `["<ref>"]` (or `[]`) plus `["-R", repo]` when set.
  - `_current_user() -> str` (cached) via `glab api user` → `.username`.

**Adapter rules (from live MR):**
- Note `id` is a JSON int → store as `str`.
- `system: true` notes are dropped; a discussion with no remaining notes is skipped.
- A note's `position` may be present-but-all-null → treat as no position. A discussion's `position` is the first note's *populated* position (`new_path`/`old_path`/`new_line`/`old_line` not all null), else `None`.
- `mine = (note.author.username == current_user)`.
- `line_range`: if present and its `end.new_line` differs from `start.new_line`, store `(start.new_line, end.new_line)`; else `None`.
- `project` = path of `web_url` before `/-/merge_requests/`.

- [ ] **Step 1: Add fixtures**

```json
// tests/fixtures/mr_notes.json
[
  {
    "id": "aaaa1111",
    "individual_note": false,
    "notes": [
      {
        "id": 501, "author": {"username": "reviewer"},
        "body": "Why not use the helper here?",
        "created_at": "2026-06-24T10:00:00Z", "updated_at": "2026-06-24T10:00:00Z",
        "system": false, "resolvable": true, "resolved": false, "type": "DiffNote",
        "position": {"new_path": "src/foo.py", "new_line": 42, "old_path": "src/foo.py",
          "old_line": null, "base_sha": "BASE", "start_sha": "START", "head_sha": "HEAD",
          "position_type": "text", "line_range": null}
      },
      {
        "id": 502, "author": {"username": "me"},
        "body": "Good point, but the helper doesn't handle null.",
        "created_at": "2026-06-24T11:00:00Z", "updated_at": "2026-06-24T11:00:00Z",
        "system": false, "resolvable": true, "resolved": false, "type": "DiffNote",
        "position": {"new_path": null, "new_line": null, "old_path": null, "old_line": null,
          "base_sha": null, "start_sha": null, "head_sha": null,
          "position_type": null, "line_range": null}
      }
    ]
  },
  {
    "id": "bbbb2222",
    "individual_note": true,
    "notes": [
      {
        "id": 600, "author": {"username": "reviewer"},
        "body": "General comment about the MR.",
        "created_at": "2026-06-24T09:00:00Z", "updated_at": "2026-06-24T09:00:00Z",
        "system": false, "resolvable": false, "resolved": false, "type": "",
        "position": null
      }
    ]
  },
  {
    "id": "cccc3333",
    "individual_note": true,
    "notes": [
      {
        "id": 700, "author": {"username": "reviewer"},
        "body": "marked this merge request as **draft**",
        "created_at": "2026-06-24T08:00:00Z", "updated_at": "2026-06-24T08:00:00Z",
        "system": true, "resolvable": false, "resolved": false, "type": "",
        "position": null
      }
    ]
  }
]
```

```json
// tests/fixtures/mr_view.json
{
  "iid": 1294,
  "title": "Add runbook",
  "web_url": "https://gitlab.com/grp/sub/repo/-/merge_requests/1294",
  "source_branch": "feat", "target_branch": "main",
  "diff_refs": {"base_sha": "BASE", "head_sha": "HEAD", "start_sha": "START"}
}
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_gitlab_reads.py
import json
from pathlib import Path
from mr_review.domain import MergeRef
from mr_review.forge.glab import GlabRunner
from mr_review.forge.gitlab import GitLabForge

FIX = Path(__file__).parent / "fixtures"

def fake_glab(responses):
    # responses: dict mapping a tuple-of-args-prefix -> stdout string
    def exec_runner(args, input):
        for prefix, out in responses.items():
            if tuple(args[: len(prefix)]) == prefix:
                return (0, out, "")
        raise AssertionError(f"unexpected glab args: {args}")
    return GlabRunner(exec_runner=exec_runner)

def make_forge():
    glab = fake_glab({
        ("api", "user"): '{"username": "me"}',
        ("mr", "view"): (FIX / "mr_view.json").read_text(),
        ("mr", "note", "list"): (FIX / "mr_notes.json").read_text(),
    })
    return GitLabForge(glab)

def test_fetch_mr_maps_metadata_and_project():
    mr = make_forge().fetch_mr(MergeRef(ref="1294"))
    assert mr.iid == "1294"
    assert mr.project == "grp/sub/repo"
    assert mr.head_sha == "HEAD"
    assert mr.current_user == "me"

def test_list_discussions_filters_system_and_skips_empty():
    discussions = make_forge().list_discussions(MergeRef(ref="1294"))
    ids = [d.native_id for d in discussions]
    assert "cccc3333" not in ids          # system-only discussion dropped
    assert ids == ["aaaa1111", "bbbb2222"]

def test_diff_position_taken_from_populated_note():
    d = make_forge().list_discussions(MergeRef(ref="1294"))[0]
    assert d.position is not None and d.position.new_line == 42
    assert d.position.new_path == "src/foo.py"

def test_note_ids_are_strings_and_mine_is_detected():
    d = make_forge().list_discussions(MergeRef(ref="1294"))[0]
    assert [n.native_id for n in d.notes] == ["501", "502"]
    assert [n.mine for n in d.notes] == [False, True]
    assert d.resolvable is True and d.resolved is False

def test_general_discussion_has_no_position():
    d = make_forge().list_discussions(MergeRef(ref="1294"))[1]
    assert d.position is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_gitlab_reads.py -v`
Expected: FAIL — `GitLabForge` not defined.

- [ ] **Step 4: Write minimal implementation**

```python
# src/mr_review/forge/gitlab.py
import re
from mr_review.domain import (
    Discussion, DiffPosition, MergeRef, MergeRequest, Note, derive_resolution,
)
from mr_review.forge.glab import GlabRunner

_MR_PATH = re.compile(r"^(.*?)/-/merge_requests/")

def _project_from_url(web_url: str) -> str:
    m = _MR_PATH.search(web_url)
    path = m.group(1) if m else web_url
    return path.split("gitlab.com/", 1)[-1].strip("/")

def _populated(pos: dict | None) -> bool:
    if not pos:
        return False
    return any(pos.get(k) is not None for k in ("new_path", "old_path", "new_line", "old_line"))

def _line_range(pos: dict) -> tuple[int, int] | None:
    lr = pos.get("line_range")
    if not lr:
        return None
    start = (lr.get("start") or {}).get("new_line")
    end = (lr.get("end") or {}).get("new_line")
    if start is None or end is None or start == end:
        return None
    return (start, end)

def _to_position(pos: dict) -> DiffPosition:
    return DiffPosition(
        new_path=pos.get("new_path"), old_path=pos.get("old_path"),
        new_line=pos.get("new_line"), old_line=pos.get("old_line"),
        base_sha=pos.get("base_sha") or "", start_sha=pos.get("start_sha") or "",
        head_sha=pos.get("head_sha") or "", line_range=_line_range(pos),
        position_type=pos.get("position_type") or "text",
    )

class GitLabForge:
    def __init__(self, glab: GlabRunner) -> None:
        self._glab = glab
        self._user: str | None = None

    def _mr_args(self, mr: MergeRef) -> list[str]:
        args: list[str] = [mr.ref] if mr.ref else []
        if mr.repo:
            args += ["-R", mr.repo]
        return args

    def _current_user(self) -> str:
        if self._user is None:
            self._user = self._glab.json(["api", "user"])["username"]
        return self._user

    def fetch_mr(self, mr: MergeRef) -> MergeRequest:
        v = self._glab.json(["mr", "view", *self._mr_args(mr), "-F", "json"])
        refs = v.get("diff_refs") or {}
        return MergeRequest(
            iid=str(v["iid"]), title=v.get("title", ""), web_url=v.get("web_url", ""),
            project=_project_from_url(v.get("web_url", "")),
            base_sha=refs.get("base_sha", ""), start_sha=refs.get("start_sha", ""),
            head_sha=refs.get("head_sha", ""), current_user=self._current_user(),
        )

    def list_discussions(self, mr: MergeRef) -> list[Discussion]:
        raw = self._glab.json(["mr", "note", "list", *self._mr_args(mr), "-F", "json"])
        user = self._current_user()
        out: list[Discussion] = []
        for d in raw:
            notes: list[Note] = []
            position: DiffPosition | None = None
            for n in d["notes"]:
                if n.get("system"):
                    continue
                if position is None and _populated(n.get("position")):
                    position = _to_position(n["position"])
                notes.append(Note(
                    native_id=str(n["id"]), author=n["author"]["username"],
                    mine=n["author"]["username"] == user, system=False,
                    created_at=n.get("created_at", ""), updated_at=n.get("updated_at", ""),
                    body=n.get("body", ""), resolvable=bool(n.get("resolvable")),
                    resolved=bool(n.get("resolved")),
                ))
            if not notes:
                continue
            resolvable, resolved = derive_resolution(notes)
            out.append(Discussion(native_id=str(d["id"]), resolvable=resolvable,
                                   resolved=resolved, position=position, notes=tuple(notes)))
        return out
```

- [ ] **Step 5: Run tests and verify they pass**

Run: `uv run pytest tests/test_gitlab_reads.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/mr_review/forge/gitlab.py tests/test_gitlab_reads.py tests/fixtures
git commit -m "Map glab discussions JSON into the domain model

Handles the live-data quirks: integer note ids, all-null position stubs,
system-note filtering, and per-note resolution derivation."
```

---

## Task 5: GitLab adapter — writes (`reply`, `edit_note`, `set_resolved`)

**Files:**
- Modify: `src/mr_review/forge/gitlab.py`
- Test: `tests/test_gitlab_writes.py`

**Interfaces:**
- Produces: `GitLabForge.reply`, `.edit_note`, `.set_resolved` (all return `None`). Bodies sent via **stdin**; the new canonical state is obtained later by re-running `list_discussions` (writes do not depend on `glab`'s create/update output format).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gitlab_writes.py
from mr_review.domain import MergeRef
from mr_review.forge.glab import GlabRunner
from mr_review.forge.gitlab import GitLabForge

def recording_forge():
    calls = []
    def exec_runner(args, input):
        calls.append((args, input))
        return (0, "{}", "")
    return GitLabForge(GlabRunner(exec_runner=exec_runner)), calls

def test_reply_uses_create_reply_with_stdin_body():
    forge, calls = recording_forge()
    forge.reply(MergeRef(ref="1294", repo="g/r"), "abc12345", "Thanks!")
    args, stdin = calls[0]
    assert args[:4] == ["mr", "note", "create", "1294"]
    assert "--reply" in args and "abc12345" in args
    assert "-R" in args and "g/r" in args
    assert stdin == "Thanks!"

def test_edit_note_uses_update_with_note_id_and_stdin():
    forge, calls = recording_forge()
    forge.edit_note(MergeRef(ref="1294"), "abc", "502", "Revised")
    args, stdin = calls[0]
    assert args[:3] == ["mr", "note", "update"]
    assert "502" in args and "1294" in args
    assert stdin == "Revised"

def test_set_resolved_true_resolves_false_reopens():
    forge, calls = recording_forge()
    forge.set_resolved(MergeRef(ref="1294"), "abc12345", True)
    forge.set_resolved(MergeRef(ref="1294"), "abc12345", False)
    assert calls[0][0][:3] == ["mr", "note", "resolve"]
    assert calls[1][0][:3] == ["mr", "note", "reopen"]
    assert "abc12345" in calls[0][0] and "1294" in calls[0][0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gitlab_writes.py -v`
Expected: FAIL — write methods not defined.

- [ ] **Step 3: Write minimal implementation** (append to `GitLabForge`)

```python
    def reply(self, mr: MergeRef, discussion_id: str, body: str) -> None:
        ref = [mr.ref] if mr.ref else []
        repo = ["-R", mr.repo] if mr.repo else []
        self._glab.run(["mr", "note", "create", *ref, "--reply", discussion_id, *repo], stdin=body)

    def edit_note(self, mr: MergeRef, discussion_id: str, note_id: str, body: str) -> None:
        ref = [mr.ref] if mr.ref else []
        repo = ["-R", mr.repo] if mr.repo else []
        self._glab.run(["mr", "note", "update", note_id, *ref, *repo], stdin=body)

    def set_resolved(self, mr: MergeRef, discussion_id: str, resolved: bool) -> None:
        verb = "resolve" if resolved else "reopen"
        ref = [mr.ref] if mr.ref else []
        repo = ["-R", mr.repo] if mr.repo else []
        self._glab.run(["mr", "note", verb, discussion_id, *ref, *repo])
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `uv run pytest tests/test_gitlab_writes.py -v`
Expected: PASS.

> **Execution note:** `glab mr note update`'s positional order (`<note-id>` vs `<mr>`) and whether `create --reply` emits JSON are EXPERIMENTAL and unverified for writes. Confirm against a throwaway MR during integration; adjust arg order here if needed. The re-sync-after-write design means we never parse the write's stdout.

- [ ] **Step 5: Commit**

```bash
git add src/mr_review/forge/gitlab.py tests/test_gitlab_writes.py
git commit -m "Add glab write operations for reply, edit, and resolve

Bodies go over stdin to avoid shell escaping; writes return None because
canonical state is rebuilt by a follow-up list_discussions, not parsed
from the experimental create/update output."
```

---

## Task 6: Sidecar store & stable handle assignment

**Files:**
- Create: `src/mr_review/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: domain `Discussion`, `DiffPosition` (Task 3).
- Produces:
  - `StoredNote(local_id: int, native_id: str, author: str, mine: bool, created_at: str, updated_at: str, body: str, resolvable: bool, resolved: bool)`
  - `StoredThread(local_id: int, native_id: str, resolvable: bool, resolved: bool, position: dict | None, notes: list[StoredNote], retired_note_handles: list[int])`
  - `StateDoc(forge, project, mr, base_sha, start_sha, head_sha, current_user, synced_at, retired_thread_handles: list[int], threads: list[StoredThread])`
  - `position_to_dict(DiffPosition | None) -> dict | None`, `dict_to_position(dict | None) -> DiffPosition | None`
  - `assign_handles(prev: StateDoc | None, discussions: list[Discussion], *, forge, project, mr, base_sha, start_sha, head_sha, current_user, synced_at) -> StateDoc`
  - `load_state(path: Path) -> StateDoc | None`, `save_state(path: Path, doc: StateDoc) -> None`

- [ ] **Step 1: Write the failing test** (behaviour: handle stability)

```python
# tests/test_store.py
from mr_review.domain import Discussion, Note
from mr_review.store import assign_handles, load_state, save_state

def note(nid, body="b"):
    return Note(native_id=nid, author="me", mine=True, system=False,
                created_at="t", updated_at="t", body=body, resolvable=True, resolved=False)

def disc(did, notes):
    return Discussion(native_id=did, resolvable=True, resolved=False, position=None, notes=tuple(notes))

META = dict(forge="gitlab", project="g/r", mr="1", base_sha="B", start_sha="S",
            head_sha="H", current_user="me", synced_at="2026-06-25T00:00:00Z")

def test_first_sync_assigns_sequential_handles():
    doc = assign_handles(None, [disc("d1", [note("n1"), note("n2")])], **META)
    assert doc.threads[0].local_id == 1
    assert [n.local_id for n in doc.threads[0].notes] == [1, 2]

def test_existing_handles_are_reused_and_new_get_next():
    first = assign_handles(None, [disc("d1", [note("n1")])], **META)
    second = assign_handles(first, [disc("d1", [note("n1"), note("n2")])], **META)
    by_native = {n.native_id: n.local_id for n in second.threads[0].notes}
    assert by_native["n1"] == 1   # unchanged
    assert by_native["n2"] == 2   # next free

def test_deleted_note_handle_is_retired_not_reused():
    first = assign_handles(None, [disc("d1", [note("n1"), note("n2")])], **META)
    # n1 deleted upstream; a brand-new n3 arrives
    second = assign_handles(first, [disc("d1", [note("n2"), note("n3")])], **META)
    th = second.threads[0]
    by_native = {n.native_id: n.local_id for n in th.notes}
    assert by_native["n2"] == 2          # stable
    assert by_native["n3"] == 3          # NOT reusing retired 1
    assert 1 in th.retired_note_handles

def test_deleted_thread_handle_is_retired():
    first = assign_handles(None, [disc("d1", [note("n1")]), disc("d2", [note("n2")])], **META)
    second = assign_handles(first, [disc("d2", [note("n2")])], **META)
    assert [t.local_id for t in second.threads] == [2]
    assert 1 in second.retired_thread_handles

def test_round_trip_save_load(tmp_path):
    doc = assign_handles(None, [disc("d1", [note("n1")])], **META)
    p = tmp_path / "1.json"
    save_state(p, doc)
    loaded = load_state(p)
    assert loaded.threads[0].notes[0].native_id == "n1"
    assert load_state(tmp_path / "missing.json") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL — `store` not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# src/mr_review/store.py
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from mr_review.domain import Discussion, DiffPosition

@dataclass
class StoredNote:
    local_id: int
    native_id: str
    author: str
    mine: bool
    created_at: str
    updated_at: str
    body: str
    resolvable: bool
    resolved: bool

@dataclass
class StoredThread:
    local_id: int
    native_id: str
    resolvable: bool
    resolved: bool
    position: dict | None
    notes: list[StoredNote]
    retired_note_handles: list[int] = field(default_factory=list)

@dataclass
class StateDoc:
    forge: str
    project: str
    mr: str
    base_sha: str
    start_sha: str
    head_sha: str
    current_user: str
    synced_at: str
    retired_thread_handles: list[int] = field(default_factory=list)
    threads: list[StoredThread] = field(default_factory=list)

def position_to_dict(p: DiffPosition | None) -> dict | None:
    return None if p is None else asdict(p)

def dict_to_position(d: dict | None) -> DiffPosition | None:
    if d is None:
        return None
    lr = d.get("line_range")
    return DiffPosition(
        new_path=d.get("new_path"), old_path=d.get("old_path"),
        new_line=d.get("new_line"), old_line=d.get("old_line"),
        base_sha=d.get("base_sha", ""), start_sha=d.get("start_sha", ""),
        head_sha=d.get("head_sha", ""),
        line_range=tuple(lr) if lr else None,
        position_type=d.get("position_type", "text"),
    )

def _next_handle(used: set[int], retired: list[int]) -> int:
    pool = used | set(retired)
    return (max(pool) + 1) if pool else 1

def assign_handles(prev, discussions, *, forge, project, mr, base_sha, start_sha,
                   head_sha, current_user, synced_at):
    prev_threads = {t.native_id: t for t in prev.threads} if prev else {}
    prev_thread_ids = set(prev_threads)
    retired_threads = list(prev.retired_thread_handles) if prev else []
    used_thread_handles = {t.local_id for t in prev.threads} if prev else set()

    new_threads: list[StoredThread] = []
    seen_thread_ids: set[str] = set()
    for d in discussions:
        seen_thread_ids.add(d.native_id)
        prior = prev_threads.get(d.native_id)
        if prior:
            t_local = prior.local_id
            prev_notes = {n.native_id: n for n in prior.notes}
            retired_notes = list(prior.retired_note_handles)
            used_note_handles = {n.local_id for n in prior.notes}
        else:
            t_local = _next_handle(used_thread_handles, retired_threads)
            used_thread_handles.add(t_local)
            prev_notes, retired_notes, used_note_handles = {}, [], set()

        seen_note_ids: set[str] = set()
        stored_notes: list[StoredNote] = []
        for n in d.notes:
            seen_note_ids.add(n.native_id)
            pn = prev_notes.get(n.native_id)
            if pn:
                n_local = pn.local_id
            else:
                n_local = _next_handle(used_note_handles, retired_notes)
                used_note_handles.add(n_local)
            stored_notes.append(StoredNote(
                local_id=n_local, native_id=n.native_id, author=n.author, mine=n.mine,
                created_at=n.created_at, updated_at=n.updated_at, body=n.body,
                resolvable=n.resolvable, resolved=n.resolved))
        # retire note handles whose native id vanished
        for native_id, pn in prev_notes.items():
            if native_id not in seen_note_ids and pn.local_id not in retired_notes:
                retired_notes.append(pn.local_id)

        new_threads.append(StoredThread(
            local_id=t_local, native_id=d.native_id, resolvable=d.resolvable,
            resolved=d.resolved, position=position_to_dict(d.position),
            notes=stored_notes, retired_note_handles=sorted(retired_notes)))

    for native_id in prev_thread_ids - seen_thread_ids:
        h = prev_threads[native_id].local_id
        if h not in retired_threads:
            retired_threads.append(h)

    return StateDoc(forge=forge, project=project, mr=mr, base_sha=base_sha,
                    start_sha=start_sha, head_sha=head_sha, current_user=current_user,
                    synced_at=synced_at, retired_thread_handles=sorted(retired_threads),
                    threads=new_threads)

def save_state(path: Path, doc: StateDoc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(doc), indent=2))

def load_state(path: Path) -> StateDoc | None:
    if not path.exists():
        return None
    raw = json.loads(path.read_text())
    threads = [
        StoredThread(
            local_id=t["local_id"], native_id=t["native_id"], resolvable=t["resolvable"],
            resolved=t["resolved"], position=t["position"],
            notes=[StoredNote(**n) for n in t["notes"]],
            retired_note_handles=t.get("retired_note_handles", []))
        for t in raw["threads"]]
    raw["threads"] = threads
    return StateDoc(**raw)
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `uv run pytest tests/test_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mr_review/store.py tests/test_store.py
git commit -m "Persist canonical state with stable, retire-on-delete handles

Local handles are reused by native id and never recycled, so file
references (thread N, note M, edit_notes) stay valid across syncs even
when upstream notes are deleted or inserted."
```

---

## Task 7: Layout, paths, slugs & .gitignore bootstrap

**Files:**
- Create: `src/mr_review/markers.py`
- Create: `src/mr_review/layout.py`
- Test: `tests/test_layout.py`

**Interfaces:**
- Produces (`markers.py`): `NS = "mr-review"`; `PUBLISHED_PREFIX`, `DRAFT_PREFIX` (the leading text of the marker comments); `note_open(h)`, `note_close(h)`; `neutralize(body: str) -> str`.
- Produces (`layout.py`):
  - `line_label(position: DiffPosition | None) -> str` → `"42"`, `"old:7"`, `"10-15"`, or `"general"`.
  - `slug_for(local_id: int, position: DiffPosition | None) -> str` → e.g. `"001-src-foo.py-L42"`.
  - `thread_path(review_dir: Path, mr: str, local_id: int, position) -> Path`
  - `state_path(review_dir: Path, mr: str) -> Path`
  - `ensure_gitignore(review_dir: Path) -> None` (writes `*` once).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_layout.py
from pathlib import Path
from mr_review.domain import DiffPosition
from mr_review.layout import line_label, slug_for, thread_path, state_path, ensure_gitignore
from mr_review.markers import neutralize, note_open

def pos(new_line=None, old_line=None, line_range=None):
    return DiffPosition(new_path="src/foo.py", old_path="src/foo.py", new_line=new_line,
                        old_line=old_line, base_sha="B", start_sha="S", head_sha="H",
                        line_range=line_range, position_type="text")

def test_line_label_variants():
    assert line_label(pos(new_line=42)) == "42"
    assert line_label(pos(old_line=7)) == "old:7"
    assert line_label(pos(new_line=10, line_range=(10, 15))) == "10-15"
    assert line_label(None) == "general"

def test_slug_includes_padded_handle_and_path():
    assert slug_for(1, pos(new_line=42)) == "001-src-foo.py-L42"
    assert slug_for(12, None) == "012-general"

def test_paths_are_under_review_dir(tmp_path):
    assert thread_path(tmp_path, "1294", 1, pos(new_line=42)) == tmp_path / "1294" / "001-src-foo.py-L42.md"
    assert state_path(tmp_path, "1294") == tmp_path / ".state" / "1294.json"

def test_ensure_gitignore_writes_star_once(tmp_path):
    ensure_gitignore(tmp_path)
    gi = tmp_path / ".gitignore"
    assert gi.read_text() == "*\n"
    gi.write_text("custom\n")
    ensure_gitignore(tmp_path)          # idempotent: does not clobber existing
    assert gi.read_text() == "custom\n"

def test_neutralize_breaks_only_our_marker():
    out = neutralize(f"text {note_open(2)} more")
    assert note_open(2) not in out
    assert "text" in out and "more" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_layout.py -v`
Expected: FAIL — modules not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# src/mr_review/markers.py
NS = "mr-review"
PUBLISHED_PREFIX = f"<!-- {NS}:published"
DRAFT_PREFIX = f"<!-- {NS}:draft"
_NOTE_TOKEN = f"<!-- {NS}:"
_NEUTRAL = f"<!-​- {NS}:"   # zero-width space breaks the literal marker

def note_open(handle: int) -> str:
    return f"<!-- {NS}:note {handle} -->"

def note_close(handle: int) -> str:
    return f"<!-- {NS}:/note {handle} -->"

def neutralize(body: str) -> str:
    return body.replace(_NOTE_TOKEN, _NEUTRAL)
```

```python
# src/mr_review/layout.py
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

def thread_path(review_dir: Path, mr: str, local_id: int, position) -> Path:
    return review_dir / mr / f"{slug_for(local_id, position)}.md"

def state_path(review_dir: Path, mr: str) -> Path:
    return review_dir / ".state" / f"{mr}.json"

def ensure_gitignore(review_dir: Path) -> None:
    review_dir.mkdir(parents=True, exist_ok=True)
    gi = review_dir / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n")
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `uv run pytest tests/test_layout.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mr_review/markers.py src/mr_review/layout.py tests/test_layout.py
git commit -m "Add path/slug layout, marker constants, and gitignore bootstrap

Self-ignore the review dir with a single '*' so the project's own
.gitignore is never touched; markers get a namespace and a neutralizer."
```

---

## Task 8: Diff context from git blobs

**Files:**
- Create: `src/mr_review/git.py`
- Create: `src/mr_review/diffcontext.py`
- Test: `tests/test_diffcontext.py`

**Interfaces:**
- Produces (`git.py`): `GitError(RuntimeError)`; `GitRunner(exec_runner=None)` with `.show(sha: str, path: str) -> str` (raises `GitError`) and `.toplevel() -> str`. `exec_runner(args, input) -> (rc, out, err)` like the glab one.
- Produces (`diffcontext.py`):
  - `format_hunk(file_text: str, highlight_lines: set[int], around: int, radius: int = 3) -> str` — a ```` ```diff ```` block; highlighted lines prefixed `> `, others ` `, with line numbers.
  - `build_context(position: DiffPosition | None, git: GitRunner, radius: int = 3) -> str | None` — picks sha/path/line by side, reads the blob, returns the block; `None` for non-text/non-diff or on `GitError`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_diffcontext.py
from mr_review.domain import DiffPosition
from mr_review.git import GitRunner
from mr_review.diffcontext import format_hunk, build_context

FILE = "line1\nline2\nline3\nline4\nline5\nline6\n"

def test_format_hunk_marks_highlight_and_windows_around():
    block = format_hunk(FILE, highlight_lines={3}, around=3, radius=1)
    assert "```diff" in block
    assert "> " in block and "line3" in block
    assert "line1" not in block          # outside radius
    assert "line2" in block and "line4" in block

def fake_git(text):
    def exec_runner(args, input):
        return (0, text, "")
    return GitRunner(exec_runner=exec_runner)

def test_build_context_new_side_uses_head_sha_blob():
    pos = DiffPosition(new_path="f.py", old_path="f.py", new_line=3, old_line=None,
                       base_sha="B", start_sha="S", head_sha="H", line_range=None,
                       position_type="text")
    block = build_context(pos, fake_git(FILE))
    assert "line3" in block and "> " in block

def test_build_context_returns_none_for_general_or_image():
    assert build_context(None, fake_git(FILE)) is None
    img = DiffPosition("f", "f", 1, None, "B", "S", "H", None, "image")
    assert build_context(img, fake_git(FILE)) is None

def test_build_context_handles_git_failure_gracefully():
    def boom(args, input):
        return (128, "", "fatal: bad object")
    pos = DiffPosition("f.py", "f.py", 3, None, "B", "S", "H", None, "text")
    assert build_context(pos, GitRunner(exec_runner=boom)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_diffcontext.py -v`
Expected: FAIL — modules not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# src/mr_review/git.py
import subprocess
from collections.abc import Callable

ExecRunner = Callable[[list[str], str | None], tuple[int, str, str]]

class GitError(RuntimeError):
    pass

def _subprocess_exec(args: list[str], input: str | None) -> tuple[int, str, str]:
    proc = subprocess.run(["git", *args], input=input, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr

class GitRunner:
    def __init__(self, exec_runner: ExecRunner | None = None) -> None:
        self._exec = exec_runner or _subprocess_exec

    def _run(self, args: list[str]) -> str:
        rc, out, err = self._exec(args, None)
        if rc != 0:
            raise GitError(err.strip())
        return out

    def show(self, sha: str, path: str) -> str:
        return self._run(["show", f"{sha}:{path}"])

    def toplevel(self) -> str:
        return self._run(["rev-parse", "--show-toplevel"]).strip()
```

```python
# src/mr_review/diffcontext.py
from mr_review.domain import DiffPosition
from mr_review.git import GitError, GitRunner

def format_hunk(file_text: str, highlight_lines: set[int], around: int, radius: int = 3) -> str:
    lines = file_text.splitlines()
    lo = max(1, around - radius)
    hi = min(len(lines), around + radius)
    width = len(str(hi))
    rows = ["```diff"]
    for n in range(lo, hi + 1):
        marker = "> " if n in highlight_lines else "  "
        rows.append(f"{marker}{str(n).rjust(width)}  {lines[n - 1]}")
    rows.append("```")
    return "\n".join(rows)

def build_context(position: DiffPosition | None, git: GitRunner, radius: int = 3) -> str | None:
    if position is None or position.position_type != "text":
        return None
    if position.new_line is not None:
        sha, path, around = position.head_sha, position.new_path, position.new_line
    elif position.old_line is not None:
        sha, path, around = position.base_sha, position.old_path, position.old_line
    else:
        return None
    if not sha or not path:
        return None
    highlight = set(range(position.line_range[0], position.line_range[1] + 1)) if position.line_range else {around}
    try:
        text = git.show(sha, path)
    except GitError:
        return None
    return format_hunk(text, highlight, around, radius)
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `uv run pytest tests/test_diffcontext.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mr_review/git.py src/mr_review/diffcontext.py tests/test_diffcontext.py
git commit -m "Reconstruct diff context from git blobs at the comment's SHAs

Reading the blob at the position's own SHA makes context accurate
regardless of working-tree state; missing blobs degrade to no context."
```

---

## Task 9: Render canonical state to a thread file

**Files:**
- Create: `src/mr_review/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `StoredThread`/`StoredNote` (Task 6), `dict_to_position` (Task 6), markers (Task 7), `line_label` (Task 7).
- Produces:
  - `RenderInputs(thread: StoredThread, diff_block: str | None, reply_draft: str, publish: bool, resolve: bool, edit_notes: list[int], note_overrides: dict[int, str], conflicts: set[int])`
  - `render_thread(inputs: RenderInputs) -> str`
  - `link_for(position: DiffPosition | None) -> str | None`

Rendering rules: frontmatter via `yaml.safe_dump` (keys: `mr` omitted here — thread file frontmatter carries `thread`, `file`, `line`, `resolvable`, `resolved`, `publish`, `resolve`, `edit_notes`). Each note becomes `### @<author> · <created_at> · note <handle>`. Only `mine` notes are wrapped in `note_open/note_close`; their body is `note_overrides.get(handle, canonical body)`. All bodies are passed through `neutralize`. A conflicted handle gets a `⚠` line before its block. Reply draft is emitted verbatim after the draft marker.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_render.py
import yaml
from mr_review.store import StoredNote, StoredThread
from mr_review.render import RenderInputs, render_thread
from mr_review.markers import PUBLISHED_PREFIX, DRAFT_PREFIX, note_open

def thread():
    return StoredThread(
        local_id=1, native_id="d1", resolvable=True, resolved=False,
        position={"new_path": "src/foo.py", "new_line": 42, "old_path": "src/foo.py",
                  "old_line": None, "base_sha": "B", "start_sha": "S", "head_sha": "H",
                  "line_range": None, "position_type": "text"},
        notes=[
            StoredNote(1, "501", "reviewer", False, "2026-06-24T10:00:00Z",
                       "2026-06-24T10:00:00Z", "Why not the helper?", True, False),
            StoredNote(2, "502", "me", True, "2026-06-24T11:00:00Z",
                       "2026-06-24T11:00:00Z", "Handles null though.", True, False),
        ],
        retired_note_handles=[])

def base_inputs(**kw):
    defaults = dict(thread=thread(), diff_block="```diff\n> 42  x\n```", reply_draft="",
                    publish=False, resolve=False, edit_notes=[], note_overrides={}, conflicts=set())
    defaults.update(kw)
    return RenderInputs(**defaults)

def split_frontmatter(text):
    _, fm, _ = text.split("---\n", 2)
    return yaml.safe_load(fm)

def test_frontmatter_carries_control_fields():
    fm = split_frontmatter(render_thread(base_inputs(publish=True, edit_notes=[2])))
    assert fm["thread"] == 1 and fm["file"] == "src/foo.py" and fm["line"] == 42
    assert fm["publish"] is True and fm["edit_notes"] == [2]
    assert fm["resolvable"] is True and fm["resolved"] is False

def test_only_mine_notes_are_wrapped_for_editing():
    out = render_thread(base_inputs())
    assert note_open(2) in out          # my note editable
    assert note_open(1) not in out      # reviewer note not wrapped
    assert "Why not the helper?" in out

def test_note_override_replaces_my_body():
    out = render_thread(base_inputs(note_overrides={2: "My revised reply."}))
    assert "My revised reply." in out
    assert "Handles null though." not in out

def test_published_and_draft_markers_and_reply_present():
    out = render_thread(base_inputs(reply_draft="Thanks, fixed."))
    assert PUBLISHED_PREFIX in out and DRAFT_PREFIX in out
    assert out.index(PUBLISHED_PREFIX) < out.index(DRAFT_PREFIX)
    assert out.rstrip().endswith("Thanks, fixed.")

def test_conflict_flag_rendered():
    out = render_thread(base_inputs(conflicts={2}))
    assert "⚠" in out

def test_marker_in_body_is_neutralized():
    t = thread()
    t.notes[0] = StoredNote(1, "501", "reviewer", False, "t", "t",
                            f"sneaky {note_open(2)}", True, False)
    out = render_thread(base_inputs(thread=t))
    # the only live occurrence of note_open(2) wraps my own note; the reviewer
    # body's injected marker is neutralized. note_close(2) is a DISTINCT string,
    # so it does not count toward note_open(2).
    assert out.count(note_open(2)) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_render.py -v`
Expected: FAIL — `render` not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# src/mr_review/render.py
from dataclasses import dataclass, field
import yaml
from mr_review.domain import DiffPosition
from mr_review.layout import line_label
from mr_review.markers import (
    DRAFT_PREFIX, PUBLISHED_PREFIX, neutralize, note_close, note_open,
)
from mr_review.store import StoredThread, dict_to_position

@dataclass
class RenderInputs:
    thread: StoredThread
    diff_block: str | None
    reply_draft: str
    publish: bool
    resolve: bool
    edit_notes: list[int]
    note_overrides: dict[int, str] = field(default_factory=dict)
    conflicts: set[int] = field(default_factory=set)

def link_for(position: DiffPosition | None) -> str | None:
    if position is None:
        return None
    path = position.new_path or position.old_path
    if not path:
        return None
    line = position.new_line or position.old_line
    anchor = f"#L{line}" if line else ""
    return f"[↗ open {path}:{line if line else ''}](../../{path}{anchor})"

def _frontmatter(inp: RenderInputs) -> str:
    pos = dict_to_position(inp.thread.position)
    data = {
        "thread": inp.thread.local_id,
        "file": (pos.new_path or pos.old_path) if pos else None,
        "line": _line_value(pos),
        "resolvable": inp.thread.resolvable,
        "resolved": inp.thread.resolved,
        "publish": inp.publish,
        "resolve": inp.resolve,
        "edit_notes": list(inp.edit_notes),
    }
    return yaml.safe_dump(data, sort_keys=False).rstrip()

def _line_value(pos: DiffPosition | None):
    if pos is None:
        return "general"
    if pos.line_range:
        return f"{pos.line_range[0]}-{pos.line_range[1]}"
    if pos.new_line is not None:
        return pos.new_line
    if pos.old_line is not None:
        return f"old:{pos.old_line}"
    return "general"

def render_thread(inp: RenderInputs) -> str:
    t = inp.thread
    pos = dict_to_position(t.position)
    state = "resolved" if t.resolved else "unresolved"
    title_loc = (pos.new_path or pos.old_path) if pos else "general"
    parts: list[str] = []
    parts.append(f"---\n{_frontmatter(inp)}\n---")
    parts.append(f"# {title_loc} · {line_label(pos)} · {state}" if pos
                 else f"# general discussion · {state}")
    link = link_for(pos)
    if link:
        parts.append(link)
    if inp.diff_block:
        parts.append(inp.diff_block)
    parts.append(f"{PUBLISHED_PREFIX} (display only — regenerated each sync) -->")
    for note in t.notes:
        if note.local_id in inp.conflicts:
            parts.append(f"⚠ note {note.local_id} changed upstream since you started editing — review your edit")
        parts.append(f"### @{note.author} · {note.created_at} · note {note.local_id}")
        if note.mine:
            body = inp.note_overrides.get(note.local_id, note.body)
            parts.append(note_open(note.local_id))
            parts.append(neutralize(body))
            parts.append(note_close(note.local_id))
        else:
            parts.append(neutralize(note.body))
    parts.append(f"{DRAFT_PREFIX} — write your reply below this line -->")
    if inp.reply_draft:
        parts.append(inp.reply_draft)
    return "\n\n".join(parts).rstrip() + "\n"
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `uv run pytest tests/test_render.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mr_review/render.py tests/test_render.py
git commit -m "Render canonical thread state into the markdown editing surface

Control flags live in frontmatter; only the author's own notes are
wrapped for inline editing; all bodies are neutralized so reviewer text
can never inject a live marker."
```

---

## Task 10: Parse the editing surface (fail-loud)

**Files:**
- Create: `src/mr_review/parse.py`
- Test: `tests/test_parse.py`

**Interfaces:**
- Consumes: markers (Task 7).
- Produces:
  - `ParseError(Exception)`
  - `ParsedThread(frontmatter: dict, reply: str, note_edits: dict[int, str])`
  - `parse_thread(text: str) -> ParsedThread`

Parsing rules: frontmatter is the first `---`-delimited YAML block (missing/invalid → `ParseError`). The body splits on the single `mr-review:draft` marker line (zero or ≥2 occurrences → `ParseError`); everything after it (stripped) is `reply`. In the published region, each `note_open(h)`…`note_close(h)` pair yields `note_edits[h] = inner.strip()`; unbalanced/mismatched/duplicate handles → `ParseError`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_parse.py
import pytest
from mr_review.parse import parse_thread, ParseError
from mr_review.markers import note_open, note_close, PUBLISHED_PREFIX, DRAFT_PREFIX

def build(reply="", my_note="my body", extra_draft=False):
    draft = f"{DRAFT_PREFIX} — write below -->"
    text = (
        "---\n"
        "thread: 1\npublish: true\nresolve: false\nedit_notes: [2]\n"
        "---\n\n"
        f"# header\n\n{PUBLISHED_PREFIX} -->\n\n"
        "### @reviewer · t · note 1\n\nWhy not the helper?\n\n"
        "### @me · t · note 2\n\n"
        f"{note_open(2)}\n{my_note}\n{note_close(2)}\n\n"
        f"{draft}\n\n{reply}"
    )
    if extra_draft:
        text += f"\n{draft}\n"
    return text

def test_parses_frontmatter_reply_and_note_edit():
    p = parse_thread(build(reply="Fixed in abc123.", my_note="Edited body."))
    assert p.frontmatter["publish"] is True
    assert p.frontmatter["edit_notes"] == [2]
    assert p.reply == "Fixed in abc123."
    assert p.note_edits == {2: "Edited body."}

def test_empty_reply_is_empty_string():
    assert parse_thread(build(reply="")).reply == ""

def test_missing_frontmatter_fails_loud():
    with pytest.raises(ParseError):
        parse_thread("# no frontmatter\n")

def test_missing_draft_marker_fails_loud():
    text = build().replace(f"{DRAFT_PREFIX} — write below -->", "")
    with pytest.raises(ParseError):
        parse_thread(text)

def test_duplicate_draft_marker_fails_loud():
    with pytest.raises(ParseError):
        parse_thread(build(extra_draft=True))

def test_unbalanced_note_marker_fails_loud():
    text = build().replace(note_close(2), "")
    with pytest.raises(ParseError):
        parse_thread(text)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_parse.py -v`
Expected: FAIL — `parse` not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# src/mr_review/parse.py
import re
from dataclasses import dataclass
import yaml
from mr_review.markers import NS, DRAFT_PREFIX

class ParseError(Exception):
    pass

@dataclass
class ParsedThread:
    frontmatter: dict
    reply: str
    note_edits: dict[int, str]

_FM = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_DRAFT_LINE = re.compile(rf"^<!-- {re.escape(NS)}:draft\b.*?-->\s*$", re.MULTILINE)
_NOTE_OPEN = re.compile(rf"<!-- {re.escape(NS)}:note (\d+) -->")
_NOTE_CLOSE = re.compile(rf"<!-- {re.escape(NS)}:/note (\d+) -->")

def parse_thread(text: str) -> ParsedThread:
    m = _FM.match(text)
    if not m:
        raise ParseError("missing or malformed frontmatter block")
    try:
        frontmatter = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise ParseError(f"invalid frontmatter YAML: {e}") from e
    body = text[m.end():]

    draft_markers = list(_DRAFT_LINE.finditer(body))
    if len(draft_markers) != 1:
        raise ParseError(f"expected exactly one draft marker, found {len(draft_markers)}")
    draft_at = draft_markers[0]
    published, reply = body[: draft_at.start()], body[draft_at.end():].strip()

    note_edits = _extract_note_edits(published)
    return ParsedThread(frontmatter=frontmatter, reply=reply, note_edits=note_edits)

def _extract_note_edits(published: str) -> dict[int, str]:
    opens = list(_NOTE_OPEN.finditer(published))
    closes = list(_NOTE_CLOSE.finditer(published))
    if len(opens) != len(closes):
        raise ParseError("unbalanced note markers")
    edits: dict[int, str] = {}
    for o, c in zip(opens, closes):
        if o.group(1) != c.group(1) or c.start() < o.end():
            raise ParseError("mismatched or out-of-order note markers")
        handle = int(o.group(1))
        if handle in edits:
            raise ParseError(f"duplicate note marker for handle {handle}")
        edits[handle] = published[o.end():c.start()].strip()
    return edits
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `uv run pytest tests/test_parse.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mr_review/parse.py tests/test_parse.py
git commit -m "Parse the draft surface with fail-loud guarantees

Only frontmatter, the reply region, and bracketed note edits are read
back; any ambiguity raises ParseError rather than risking a wrong post."
```

---

## Task 11: Plan actions from drafts vs canonical

**Files:**
- Create: `src/mr_review/plan.py`
- Test: `tests/test_plan.py`

**Interfaces:**
- Consumes: `ParsedThread` (Task 10), `StoredThread` (Task 6).
- Produces:
  - `ReplyAction(thread_local_id, discussion_id, body)`
  - `EditAction(thread_local_id, discussion_id, note_id, note_local_id, body)`
  - `ResolveAction(thread_local_id, discussion_id)` (resolve only; reopen is out of scope for v1)
  - `PlanWarning(thread_local_id, message)`
  - `ThreadPlan(actions: list, warnings: list)`
  - `plan_thread(parsed: ParsedThread, thread: StoredThread) -> ThreadPlan`

Planning rules:
- `publish: true` + non-empty reply → `ReplyAction`. `publish: true` + empty reply → warning.
- For each handle in `edit_notes`: must map to a `mine` note in `thread` (else warning: not yours / unknown/retired), must appear in `note_edits`, and its body must differ from canonical → `EditAction`; unchanged → warning (nothing to publish).
- A note whose `note_edits` body differs from canonical but whose handle is **not** in `edit_notes` → warning (unmarked edit).
- `resolve: true` and thread not already resolved → `ResolveAction`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan.py
from mr_review.parse import ParsedThread
from mr_review.store import StoredNote, StoredThread
from mr_review.plan import (
    plan_thread, ReplyAction, EditAction, ResolveAction, PlanWarning,
)

def thread(resolved=False):
    return StoredThread(
        local_id=1, native_id="d1", resolvable=True, resolved=resolved, position=None,
        notes=[
            StoredNote(1, "501", "reviewer", False, "t", "t", "review", True, False),
            StoredNote(2, "502", "me", True, "t", "t", "canonical body", True, False),
        ],
        retired_note_handles=[])

def parsed(publish=False, reply="", resolve=False, edit_notes=None, note_edits=None):
    return ParsedThread(
        frontmatter={"publish": publish, "reply": reply, "resolve": resolve,
                     "edit_notes": edit_notes or []},
        reply=reply, note_edits=note_edits or {})

def types(plan):
    return [type(a).__name__ for a in plan.actions]

def test_ready_reply_becomes_reply_action():
    plan = plan_thread(parsed(publish=True, reply="Thanks!"), thread())
    assert types(plan) == ["ReplyAction"]
    assert plan.actions[0].body == "Thanks!" and plan.actions[0].discussion_id == "d1"

def test_publish_true_empty_reply_warns():
    plan = plan_thread(parsed(publish=True, reply=""), thread())
    assert not plan.actions and plan.warnings

def test_marked_changed_edit_becomes_edit_action():
    plan = plan_thread(parsed(edit_notes=[2], note_edits={2: "new body"}), thread())
    assert types(plan) == ["EditAction"]
    a = plan.actions[0]
    assert a.note_id == "502" and a.note_local_id == 2 and a.body == "new body"

def test_marked_but_unchanged_edit_warns_no_action():
    plan = plan_thread(parsed(edit_notes=[2], note_edits={2: "canonical body"}), thread())
    assert not plan.actions and plan.warnings

def test_unmarked_divergent_edit_warns():
    plan = plan_thread(parsed(edit_notes=[], note_edits={2: "secretly changed"}), thread())
    assert not plan.actions
    assert any("note 2" in w.message for w in plan.warnings)

def test_edit_notes_referencing_non_mine_or_unknown_warns():
    plan = plan_thread(parsed(edit_notes=[1], note_edits={1: "x"}), thread())   # note 1 not mine
    assert not plan.actions and plan.warnings
    plan2 = plan_thread(parsed(edit_notes=[9], note_edits={}), thread())          # unknown handle
    assert not plan2.actions and plan2.warnings

def test_resolve_true_when_unresolved_adds_resolve_action():
    plan = plan_thread(parsed(resolve=True), thread(resolved=False))
    assert "ResolveAction" in types(plan)

def test_resolve_true_when_already_resolved_noop():
    plan = plan_thread(parsed(resolve=True), thread(resolved=True))
    assert "ResolveAction" not in types(plan)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_plan.py -v`
Expected: FAIL — `plan` not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# src/mr_review/plan.py
from dataclasses import dataclass, field
from mr_review.parse import ParsedThread
from mr_review.store import StoredThread

@dataclass(frozen=True)
class ReplyAction:
    thread_local_id: int
    discussion_id: str
    body: str

@dataclass(frozen=True)
class EditAction:
    thread_local_id: int
    discussion_id: str
    note_id: str
    note_local_id: int
    body: str

@dataclass(frozen=True)
class ResolveAction:
    thread_local_id: int
    discussion_id: str

@dataclass(frozen=True)
class PlanWarning:
    thread_local_id: int
    message: str

@dataclass
class ThreadPlan:
    actions: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

def plan_thread(parsed: ParsedThread, thread: StoredThread) -> ThreadPlan:
    plan = ThreadPlan()
    fm = parsed.frontmatter
    tid = thread.local_id
    by_handle = {n.local_id: n for n in thread.notes}
    edit_notes = set(fm.get("edit_notes") or [])

    if fm.get("publish"):
        if parsed.reply.strip():
            plan.actions.append(ReplyAction(tid, thread.native_id, parsed.reply.strip()))
        else:
            plan.warnings.append(PlanWarning(tid, "publish: true but the reply is empty"))

    for handle in sorted(edit_notes):
        note = by_handle.get(handle)
        if note is None:
            plan.warnings.append(PlanWarning(tid, f"edit_notes references note {handle}, which does not exist"))
            continue
        if not note.mine:
            plan.warnings.append(PlanWarning(tid, f"note {handle} is not yours and cannot be edited"))
            continue
        if handle not in parsed.note_edits:
            plan.warnings.append(PlanWarning(tid, f"note {handle} marked for edit but its block is missing"))
            continue
        new_body = parsed.note_edits[handle]
        if new_body == note.body:
            plan.warnings.append(PlanWarning(tid, f"note {handle} marked for edit but unchanged"))
            continue
        plan.actions.append(EditAction(tid, thread.native_id, note.native_id, handle, new_body))

    for handle, new_body in parsed.note_edits.items():
        note = by_handle.get(handle)
        if note and note.mine and handle not in edit_notes and new_body != note.body:
            plan.warnings.append(PlanWarning(tid, f"note {handle} was edited but not listed in edit_notes — not published"))

    if fm.get("resolve") and not thread.resolved:
        plan.actions.append(ResolveAction(tid, thread.native_id))

    return plan
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `uv run pytest tests/test_plan.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mr_review/plan.py tests/test_plan.py
git commit -m "Derive publish actions and warnings from drafts vs canonical

Ready replies/edits/resolves become actions; unmarked divergences and
no-op markers surface as warnings so nothing is posted by surprise."
```

---

## Task 12: `sync` orchestration (safe-merge + conflict flags)

**Files:**
- Create: `tests/fakes.py`
- Create: `src/mr_review/sync.py`
- Test: `tests/test_sync.py`

**Interfaces:**
- Consumes: `Forge` port, `fetch_mr`/`list_discussions`, `store`, `layout`, `diffcontext`, `render`, `parse`.
- Produces:
  - `SyncResult(written: list[Path], conflicts: list[tuple[int, int]])`
  - `sync(forge: Forge, review_dir: Path, mr_ref: MergeRef, git: GitRunner, now: str) -> SyncResult`
- `tests/fakes.py`: `FakeForge(mr: MergeRequest, discussions: list[Discussion])` recording `reply`/`edit_note`/`set_resolved` calls in `.calls`; `fake_git(text)` returning a `GitRunner`.

Sync algorithm: `fetch_mr` → `list_discussions` → `load_state(prev)` → `assign_handles` → for each thread: if a file already exists, `parse_thread` it to recover `reply_draft`, frontmatter `publish`/`resolve`/`edit_notes`, and `note_edits`; compute `note_overrides` (preserve a `mine` note's body where the file body differs from the **previous** canonical body) and `conflicts` (handle where the file diverged AND the new canonical body differs from the previous one) → `build_context` → `render_thread` → write. Then `save_state`, `ensure_gitignore`.

- [ ] **Step 1: Write `tests/fakes.py`**

```python
# tests/fakes.py
from mr_review.git import GitRunner

class FakeForge:
    def __init__(self, mr, discussions):
        self._mr = mr
        self._discussions = discussions
        self.calls = []

    def fetch_mr(self, mr):
        return self._mr

    def list_discussions(self, mr):
        return list(self._discussions)

    def reply(self, mr, discussion_id, body):
        self.calls.append(("reply", discussion_id, body))

    def edit_note(self, mr, discussion_id, note_id, body):
        self.calls.append(("edit", discussion_id, note_id, body))

    def set_resolved(self, mr, discussion_id, resolved):
        self.calls.append(("resolve", discussion_id, resolved))

def fake_git(text=""):
    def exec_runner(args, input):
        return (0, text, "")
    return GitRunner(exec_runner=exec_runner)
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_sync.py
from mr_review.domain import Discussion, DiffPosition, MergeRef, MergeRequest, Note
from mr_review.parse import parse_thread
from mr_review.sync import sync
from tests.fakes import FakeForge, fake_git

MR = MergeRequest(iid="1", title="t", web_url="https://gitlab.com/g/r/-/merge_requests/1",
                  project="g/r", base_sha="B", start_sha="S", head_sha="H", current_user="me")

def disc():
    pos = DiffPosition("src/foo.py", "src/foo.py", 42, None, "B", "S", "H", None, "text")
    return Discussion("d1", True, False, pos, (
        Note("501", "reviewer", False, False, "t", "t", "Why not helper?", True, False),
        Note("502", "me", True, False, "t", "t", "canonical body", True, False),
    ))

def test_sync_writes_thread_file_and_state(tmp_path):
    forge = FakeForge(MR, [disc()])
    result = sync(forge, tmp_path, MergeRef(ref="1"), fake_git("a\nb\nc\n"*20), now="NOW")
    assert len(result.written) == 1
    f = result.written[0]
    assert f.exists() and f.suffix == ".md"
    assert (tmp_path / ".state" / "1.json").exists()
    assert (tmp_path / ".gitignore").read_text() == "*\n"

def test_resync_preserves_reply_draft(tmp_path):
    forge = FakeForge(MR, [disc()])
    f = sync(forge, tmp_path, MergeRef(ref="1"), fake_git(), now="NOW").written[0]
    text = f.read_text().rstrip() + "\nMy drafted reply.\n"
    f.write_text(text)
    sync(forge, tmp_path, MergeRef(ref="1"), fake_git(), now="NOW2")   # re-sync
    assert "My drafted reply." in f.read_text()

def test_resync_preserves_inline_edit_and_flags_upstream_conflict(tmp_path):
    forge = FakeForge(MR, [disc()])
    f = sync(forge, tmp_path, MergeRef(ref="1"), fake_git(), now="NOW").written[0]
    # locally edit my note (handle 2)
    edited = f.read_text().replace("canonical body", "my local edit")
    f.write_text(edited)
    # upstream also changes that note's body
    changed = disc()
    new_notes = list(changed.notes)
    new_notes[1] = Note("502", "me", True, False, "t", "t2", "UPSTREAM CHANGED", True, False)
    forge2 = FakeForge(MR, [Discussion("d1", True, False, changed.position, tuple(new_notes))])
    sync(forge2, tmp_path, MergeRef(ref="1"), fake_git(), now="NOW2")
    out = f.read_text()
    assert "my local edit" in out      # local edit preserved, not clobbered
    assert "⚠" in out                  # conflict flagged
    assert parse_thread(out).note_edits[2] == "my local edit"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_sync.py -v`
Expected: FAIL — `sync` not defined.

- [ ] **Step 4: Write minimal implementation**

```python
# src/mr_review/sync.py
from dataclasses import dataclass, field
from pathlib import Path
from mr_review.domain import MergeRef
from mr_review.diffcontext import build_context
from mr_review.git import GitRunner
from mr_review.layout import ensure_gitignore, state_path, thread_path
from mr_review.parse import ParseError, parse_thread
from mr_review.render import RenderInputs, render_thread
from mr_review.store import (
    assign_handles, dict_to_position, load_state, save_state,
)

@dataclass
class SyncResult:
    written: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)

def sync(forge, review_dir: Path, mr_ref: MergeRef, git: GitRunner, now: str) -> SyncResult:
    mr = forge.fetch_mr(mr_ref)
    discussions = forge.list_discussions(mr_ref)
    prev = load_state(state_path(review_dir, mr.iid))
    prev_threads = {t.native_id: t for t in prev.threads} if prev else {}

    new_state = assign_handles(
        prev, discussions, forge="gitlab", project=mr.project, mr=mr.iid,
        base_sha=mr.base_sha, start_sha=mr.start_sha, head_sha=mr.head_sha,
        current_user=mr.current_user, synced_at=now)

    result = SyncResult()
    for thread in new_state.threads:
        prior = prev_threads.get(thread.native_id)
        path = thread_path(review_dir, mr.iid, thread.local_id, dict_to_position(thread.position))
        reply_draft, publish, resolve, edit_notes, overrides, conflicts = _merge_local(
            path, thread, prior)
        diff_block = build_context(dict_to_position(thread.position), git)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_thread(RenderInputs(
            thread=thread, diff_block=diff_block, reply_draft=reply_draft,
            publish=publish, resolve=resolve, edit_notes=edit_notes,
            note_overrides=overrides, conflicts=conflicts)))
        result.written.append(path)
        for h in conflicts:
            result.conflicts.append((thread.local_id, h))

    save_state(state_path(review_dir, mr.iid), new_state)
    ensure_gitignore(review_dir)
    return result

def _merge_local(path: Path, thread, prior):
    """Recover drafts/edits from an existing file; preserve and flag conflicts."""
    if not path.exists():
        return ("", False, False, [], {}, set())
    try:
        parsed = parse_thread(path.read_text())
    except ParseError:
        return ("", False, False, [], {}, set())   # malformed file: regenerate clean

    fm = parsed.frontmatter or {}
    prior_bodies = {n.local_id: n.body for n in prior.notes} if prior else {}
    new_bodies = {n.local_id: n.body for n in thread.notes}

    overrides: dict[int, str] = {}
    conflicts: set[int] = set()
    for handle, file_body in parsed.note_edits.items():
        prev_body = prior_bodies.get(handle)
        if prev_body is not None and file_body != prev_body:   # locally edited
            overrides[handle] = file_body
            if new_bodies.get(handle) != prev_body:            # upstream also changed
                conflicts.add(handle)
    return (
        parsed.reply, bool(fm.get("publish")), bool(fm.get("resolve")),
        list(fm.get("edit_notes") or []), overrides, conflicts,
    )
```

- [ ] **Step 5: Run tests and verify they pass**

Run: `uv run pytest tests/test_sync.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/mr_review/sync.py tests/test_sync.py tests/fakes.py
git commit -m "Implement sync with draft-preserving safe-merge

Re-rendering pulls fresh canonical state but carries forward reply drafts
and in-progress inline edits; an edit that also changed upstream is kept
locally and flagged with a conflict marker rather than overwritten."
```

---

## Task 13: `status` command (read-only)

**Files:**
- Create: `src/mr_review/status.py`
- Modify: `src/mr_review/cli.py` (wire `status` + add a shared `_resolve` helper)
- Test: `tests/test_status.py`

**Interfaces:**
- Consumes: `store.load_state`, `layout`, `parse`, `plan`.
- Produces:
  - `ThreadStatus(local_id, file, line, resolved, actions, warnings)`
  - `StatusReport(mr, threads: list[ThreadStatus])`
  - `gather_status(review_dir: Path, mr: str) -> StatusReport` — for each thread in state, read its file (if present) and `plan_thread`.
  - `format_status(report) -> str`, `status_json(report) -> dict`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_status.py
from mr_review.domain import Discussion, DiffPosition, MergeRef, MergeRequest, Note
from mr_review.sync import sync
from mr_review.status import gather_status, status_json, format_status
from tests.fakes import FakeForge, fake_git

MR = MergeRequest("1", "t", "https://gitlab.com/g/r/-/merge_requests/1", "g/r", "B", "S", "H", "me")

def disc():
    pos = DiffPosition("src/foo.py", "src/foo.py", 42, None, "B", "S", "H", None, "text")
    return Discussion("d1", True, False, pos, (
        Note("501", "reviewer", False, False, "t", "t", "Why?", True, False),
        Note("502", "me", True, False, "t", "t", "canonical", True, False),
    ))

def synced(tmp_path):
    f = sync(FakeForge(MR, [disc()]), tmp_path, MergeRef(ref="1"), fake_git(), now="N").written[0]
    return f

def test_status_reports_pending_reply(tmp_path):
    f = synced(tmp_path)
    text = f.read_text().replace("publish: false", "publish: true").rstrip() + "\nReady reply.\n"
    f.write_text(text)
    report = gather_status(tmp_path, "1")
    data = status_json(report)
    assert data["threads"][0]["actions"][0]["type"] == "ReplyAction"
    assert "Ready reply" in format_status(report)

def test_status_reports_nothing_when_no_drafts(tmp_path):
    synced(tmp_path)
    report = gather_status(tmp_path, "1")
    assert status_json(report)["threads"][0]["actions"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_status.py -v`
Expected: FAIL — `status` not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# src/mr_review/status.py
from dataclasses import asdict, dataclass, field
from pathlib import Path
from mr_review.layout import line_label, thread_path, state_path
from mr_review.parse import ParseError, ParsedThread, parse_thread
from mr_review.plan import plan_thread
from mr_review.store import dict_to_position, load_state

@dataclass
class ThreadStatus:
    local_id: int
    file: str
    line: str
    resolved: bool
    actions: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

@dataclass
class StatusReport:
    mr: str
    threads: list = field(default_factory=list)

def gather_status(review_dir: Path, mr: str) -> StatusReport:
    state = load_state(state_path(review_dir, mr))
    report = StatusReport(mr=mr)
    if state is None:
        return report
    for thread in state.threads:
        pos = dict_to_position(thread.position)
        path = thread_path(review_dir, mr, thread.local_id, pos)
        if path.exists():
            try:
                parsed = parse_thread(path.read_text())
            except ParseError as e:
                report.threads.append(ThreadStatus(
                    thread.local_id, str(path.name), line_label(pos), thread.resolved,
                    warnings=[f"parse error: {e}"]))
                continue
        else:
            parsed = ParsedThread(frontmatter={}, reply="", note_edits={})
        plan = plan_thread(parsed, thread)
        report.threads.append(ThreadStatus(
            local_id=thread.local_id, file=path.name, line=line_label(pos),
            resolved=thread.resolved,
            actions=[{"type": type(a).__name__, **asdict(a)} for a in plan.actions],
            warnings=[w.message for w in plan.warnings]))
    return report

def status_json(report: StatusReport) -> dict:
    return {"mr": report.mr, "threads": [asdict(t) for t in report.threads]}

def format_status(report: StatusReport) -> str:
    lines = [f"MR !{report.mr}"]
    for t in report.threads:
        state = "resolved" if t.resolved else "unresolved"
        lines.append(f"  thread {t.local_id} · {t.file} · {t.line} · {state}")
        for a in t.actions:
            detail = a.get("body", "") or ("resolve" if a["type"] == "ResolveAction" else "")
            lines.append(f"    READY {a['type']}: {detail[:60]}")
        for w in t.warnings:
            lines.append(f"    ⚠ {w}")
    if all(not t.actions for t in report.threads):
        lines.append("  (nothing marked ready)")
    return "\n".join(lines)
```

- [ ] **Step 4: Wire the CLI** (replace the `status` stub; add a shared resolver used by all commands)

```python
# src/mr_review/cli.py  (add imports + helper + fill status)
from pathlib import Path
from mr_review.config import make_forge, repo_root, review_dir
from mr_review.domain import MergeRef
from mr_review.git import GitRunner
from mr_review.forge.glab import GlabRunner
from mr_review.forge.gitlab import GitLabForge
from mr_review import status as status_mod

def _context():
    root = repo_root(Path.cwd(), GitRunner())
    return review_dir(root)

# inside status():
    rdir = _context()
    forge = GitLabForge(GlabRunner())
    mr_iid = forge.fetch_mr(MergeRef(ref=mr, repo=repo)).iid
    report = status_mod.gather_status(rdir, mr_iid)
    import json as _json
    click.echo(_json.dumps(status_mod.status_json(report), indent=2) if as_json
               else status_mod.format_status(report))
```

> Note: `config.repo_root`/`review_dir`/`make_forge` are introduced in Task 7's module set if not already present — if `config.py` does not yet exist, create it here with: `repo_root(cwd, git) -> Path` (via `git.toplevel()`), `review_dir(root) -> root / "mr-review"`, `make_forge(name="gitlab") -> GitLabForge(GlabRunner())`.

- [ ] **Step 5: Run tests and verify they pass**

Run: `uv run pytest tests/test_status.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/mr_review/status.py src/mr_review/cli.py src/mr_review/config.py tests/test_status.py
git commit -m "Add read-only status command as the agent's confirmation surface

status plans every thread and reports ready actions and warnings in text
or --json, posting nothing — the surface a human/agent reviews before publish."
```

---

## Task 14: `publish` command (execute, clear drafts, re-sync)

**Files:**
- Create: `src/mr_review/publish.py`
- Modify: `src/mr_review/cli.py` (wire `sync` and `publish`)
- Test: `tests/test_publish.py`

**Interfaces:**
- Consumes: `Forge` writes, `store`, `layout`, `parse`, `plan`, `sync.sync`.
- Produces:
  - `PublishResult(posted: list[str], failed: list[tuple[str, str]], dry_run: bool)`
  - `publish(forge, review_dir, mr_ref, git, now, dry_run=False) -> PublishResult`

Algorithm: load state; for each thread file, `parse_thread` + `plan_thread`; collect actions. If `dry_run`, return the plan summary without posting. Otherwise execute each action via the forge; on success, **clear that draft from the file immediately** (`ReplyAction` → set `publish: false` and drop the reply text; `EditAction` → remove the handle from `edit_notes`; `ResolveAction` → set `resolve: false`) so re-runs never double-post; collect failures per action and continue. Finally re-run `sync.sync` to rebuild canonical state and re-render.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_publish.py
from mr_review.domain import Discussion, DiffPosition, MergeRef, MergeRequest, Note
from mr_review.sync import sync
from mr_review.publish import publish
from tests.fakes import FakeForge, fake_git

MR = MergeRequest("1", "t", "https://gitlab.com/g/r/-/merge_requests/1", "g/r", "B", "S", "H", "me")

def disc():
    pos = DiffPosition("src/foo.py", "src/foo.py", 42, None, "B", "S", "H", None, "text")
    return Discussion("d1", True, False, pos, (
        Note("501", "reviewer", False, False, "t", "t", "Why?", True, False),
        Note("502", "me", True, False, "t", "t", "canonical", True, False),
    ))

def setup_ready_reply(tmp_path):
    forge = FakeForge(MR, [disc()])
    f = sync(forge, tmp_path, MergeRef(ref="1"), fake_git(), now="N").written[0]
    text = f.read_text().replace("publish: false", "publish: true").rstrip() + "\nThanks, fixed.\n"
    f.write_text(text)
    return forge, f

def test_dry_run_posts_nothing(tmp_path):
    forge, _ = setup_ready_reply(tmp_path)
    result = publish(forge, tmp_path, MergeRef(ref="1"), fake_git(), now="N2", dry_run=True)
    assert result.dry_run and not any(c[0] == "reply" for c in forge.calls)

def test_publish_posts_reply_and_clears_draft(tmp_path):
    forge, f = setup_ready_reply(tmp_path)
    result = publish(forge, tmp_path, MergeRef(ref="1"), fake_git(), now="N2")
    assert ("reply", "d1", "Thanks, fixed.") in forge.calls
    # draft cleared: publish back to false, reply text gone
    from mr_review.parse import parse_thread
    parsed = parse_thread(f.read_text())
    assert parsed.frontmatter["publish"] is False
    assert parsed.reply == ""

def test_publish_resolve_calls_forge(tmp_path):
    forge = FakeForge(MR, [disc()])
    f = sync(forge, tmp_path, MergeRef(ref="1"), fake_git(), now="N").written[0]
    f.write_text(f.read_text().replace("resolve: false", "resolve: true"))
    publish(forge, tmp_path, MergeRef(ref="1"), fake_git(), now="N2")
    assert ("resolve", "d1", True) in forge.calls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_publish.py -v`
Expected: FAIL — `publish` not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# src/mr_review/publish.py
import re
from dataclasses import dataclass, field
from pathlib import Path
import yaml
from mr_review.domain import MergeRef
from mr_review.layout import state_path, thread_path
from mr_review.parse import ParseError, parse_thread
from mr_review.plan import EditAction, ReplyAction, ResolveAction, plan_thread
from mr_review.store import dict_to_position, load_state
from mr_review.sync import sync

@dataclass
class PublishResult:
    posted: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    dry_run: bool = False

def publish(forge, review_dir: Path, mr_ref: MergeRef, git, now: str, dry_run: bool = False) -> PublishResult:
    mr = forge.fetch_mr(mr_ref)
    state = load_state(state_path(review_dir, mr.iid))
    result = PublishResult(dry_run=dry_run)
    if state is None:
        return result

    for thread in state.threads:
        pos = dict_to_position(thread.position)
        path = thread_path(review_dir, mr.iid, thread.local_id, pos)
        if not path.exists():
            continue
        try:
            parsed = parse_thread(path.read_text())
        except ParseError as e:
            result.failed.append((path.name, f"parse error: {e}"))
            continue
        plan = plan_thread(parsed, thread)
        for action in plan.actions:
            if dry_run:
                result.posted.append(_describe(action))
                continue
            try:
                _execute(forge, mr_ref, action)
                _clear_draft(path, action)
                result.posted.append(_describe(action))
            except Exception as e:  # forge/glab failure: isolate per item
                result.failed.append((path.name, f"{_describe(action)}: {e}"))

    if not dry_run:
        sync(forge, review_dir, mr_ref, git, now)   # rebuild canonical + re-render
    return result

def _execute(forge, mr_ref, action) -> None:
    if isinstance(action, ReplyAction):
        forge.reply(mr_ref, action.discussion_id, action.body)
    elif isinstance(action, EditAction):
        forge.edit_note(mr_ref, action.discussion_id, action.note_id, action.body)
    elif isinstance(action, ResolveAction):
        forge.set_resolved(mr_ref, action.discussion_id, True)

def _describe(action) -> str:
    return f"{type(action).__name__}@thread{action.thread_local_id}"

_DRAFT_LINE = re.compile(r"^<!-- mr-review:draft\b.*?-->\s*$", re.MULTILINE)

def _clear_draft(path: Path, action) -> None:
    text = path.read_text()
    if isinstance(action, ReplyAction):
        text = _set_frontmatter(text, "publish", False)
        m = _DRAFT_LINE.search(text)
        if m:
            text = text[: m.end()] + "\n"
    elif isinstance(action, EditAction):
        text = _drop_edit_handle(text, action.note_local_id)
    elif isinstance(action, ResolveAction):
        text = _set_frontmatter(text, "resolve", False)
    path.write_text(text)

def _split_fm(text):
    parts = text.split("---\n", 2)
    return parts[1], parts[2]   # (frontmatter_yaml, body)

def _set_frontmatter(text: str, key: str, value) -> str:
    fm_text, body = _split_fm(text)
    fm = yaml.safe_load(fm_text) or {}
    fm[key] = value
    return f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n{body}"

def _drop_edit_handle(text: str, handle: int) -> str:
    fm_text, body = _split_fm(text)
    fm = yaml.safe_load(fm_text) or {}
    fm["edit_notes"] = [h for h in (fm.get("edit_notes") or []) if h != handle]
    return f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n{body}"
```

- [ ] **Step 4: Wire `sync` and `publish` in the CLI** (replace stubs)

```python
# src/mr_review/cli.py  (fill sync() and publish())
import datetime as _dt
from mr_review import sync as sync_mod
from mr_review import publish as publish_mod

def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()

# inside sync():
    rdir = _context()
    forge = GitLabForge(GlabRunner())
    result = sync_mod.sync(forge, rdir, MergeRef(ref=mr, repo=repo), GitRunner(), _now())
    click.echo(f"Synced {len(result.written)} threads; {len(result.conflicts)} conflict(s).")

# inside publish():
    rdir = _context()
    forge = GitLabForge(GlabRunner())
    result = publish_mod.publish(forge, rdir, MergeRef(ref=mr, repo=repo), GitRunner(), _now(),
                                 dry_run=dry_run)
    verb = "Would post" if dry_run else "Posted"
    click.echo(f"{verb}: {len(result.posted)} item(s); {len(result.failed)} failed.")
    for name, err in result.failed:
        click.echo(f"  ✗ {name}: {err}")
```

- [ ] **Step 5: Run tests and verify they pass**

Run: `uv run pytest tests/test_publish.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/mr_review/publish.py src/mr_review/cli.py tests/test_publish.py
git commit -m "Add publish: execute ready actions, clear drafts, re-sync

Each posted item is cleared from its file immediately so re-runs never
double-post; per-item failures are isolated; a closing sync rebuilds
canonical state instead of trusting the experimental write output."
```

---

## Task 15: End-to-end integration & CLI smoke

**Files:**
- Create: `tests/test_integration.py`

**Interfaces:**
- Consumes: everything. Drives a full `sync → draft → status → publish → re-sync` cycle through `FakeForge` in a temp dir, asserting observable outcomes.

- [ ] **Step 1: Write the integration test**

```python
# tests/test_integration.py
from mr_review.domain import Discussion, DiffPosition, MergeRef, MergeRequest, Note
from mr_review.sync import sync
from mr_review.status import gather_status, status_json
from mr_review.publish import publish
from mr_review.parse import parse_thread
from tests.fakes import FakeForge, fake_git

MR = MergeRequest("1", "t", "https://gitlab.com/g/r/-/merge_requests/1", "g/r", "B", "S", "H", "me")

def disc():
    pos = DiffPosition("src/foo.py", "src/foo.py", 42, None, "B", "S", "H", None, "text")
    return Discussion("d1", True, False, pos, (
        Note("501", "reviewer", False, False, "t", "t", "Why not the helper?", True, False),
    ))

def test_full_round_trip(tmp_path):
    forge = FakeForge(MR, [disc()])
    ref = MergeRef(ref="1")

    # 1. sync creates the thread file
    f = sync(forge, tmp_path, ref, fake_git("x\n"*60), now="N1").written[0]
    assert "Why not the helper?" in f.read_text()

    # 2. draft a reply and mark ready
    f.write_text(f.read_text().replace("publish: false", "publish: true").rstrip() + "\nFixed in def456.\n")

    # 3. status shows it ready
    report = status_json(gather_status(tmp_path, "1"))
    assert report["threads"][0]["actions"][0]["type"] == "ReplyAction"

    # 4. publish posts it and clears the draft
    result = publish(forge, tmp_path, ref, fake_git(), now="N2")
    assert ("reply", "d1", "Fixed in def456.") in forge.calls
    assert parse_thread(f.read_text()).frontmatter["publish"] is False

    # 5. status is now clean
    report2 = status_json(gather_status(tmp_path, "1"))
    assert report2["threads"][0]["actions"] == []
```

- [ ] **Step 2: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS (all tasks' tests green).

- [ ] **Step 3: Manual smoke against the real MR** (read-only first)

```bash
cd ~/Projects/test-repo
direnv exec . uv run --project ~/Projects/local-mr-review mr-review sync 1294
direnv exec . uv run --project ~/Projects/local-mr-review mr-review status 1294
```
Expected: thread files appear under `mr-review/1294/`, `.state/1294.json` written, `status` lists threads with no ready actions. (Do **not** run `publish` against !1294 until write-command arg order is confirmed on a throwaway MR — see Task 5 note.)

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "Add end-to-end round-trip integration test

Exercises sync -> draft -> status -> publish -> clear through FakeForge,
asserting observable file and forge-call outcomes across the whole flow."
```

---

## Self-Review

**Spec coverage:**
- Pull discussions via glab → Tasks 2, 4. ✓
- Save each thread as a file in a gitignored dir → Tasks 7 (`.gitignore`), 9, 12. ✓
- Diff context + real file/line link → Tasks 8, 9. ✓
- Manual sync pulling new comments/edits → Task 12. ✓
- Draft replies in-file → Tasks 9, 10, 12. ✓
- Draft edits to prior comments in-file → Tasks 9 (note wrapping), 10 (note_edits), 11 (EditAction), 12 (preserve). ✓
- Publish with marker-gated confirmation; read-only status surface → Tasks 11, 13, 14. ✓
- Forge abstraction → Tasks 3 (port), 4/5 (adapter); core never imports the adapter. ✓
- Local-handle id scheme + stability/retirement → Task 6. ✓
- In-band marker collision handling (frontmatter control, never-parse-published, escape-on-render, fail-loud) → Tasks 7, 9, 10. ✓
- Resolution derived per-note → Tasks 3, 4. ✓
- Safe-merge + conflict flag → Task 12. ✓
- Transactional publish (clear-on-success, isolated failures, re-sync) → Task 14. ✓
- Error handling via typed exceptions, no panics → Tasks 2 (`ForgeError`), 8 (`GitError`), 10 (`ParseError`); CLI is the only layer that prints/exits. ✓
- Testing via `FakeForge`/fixtures, behaviour-only → Tasks 4, 12–15. ✓

**Placeholder scan:** No TBD/TODO; every code step has complete code. The only deferred item is the Task 5 execution note (write-command arg order / output format), which is an explicit runtime-verification step, not a missing implementation.

**Type consistency:** `MergeRef(ref, repo)`, `DiffPosition` field order, `Note`/`StoredNote` field order, `Discussion`/`StoredThread`, action dataclasses, and `render`/`parse`/`plan`/`sync`/`publish` signatures are consistent across tasks. `forge.reply/edit_note/set_resolved` return `None` everywhere (port in Task 3, adapter in Task 5, FakeForge in Task 12, callers in Task 14). Marker constants (`PUBLISHED_PREFIX`, `DRAFT_PREFIX`, `note_open/close`, `neutralize`) defined once in Task 7 and reused by render/parse/publish.

**Known follow-ups (not blocking, recorded in spec "Future work"):** GitHub adapter; creating discussions; `mr-review list`; smoother `edit_notes` ergonomics. The `publish`'s `_clear_draft`/`_set_frontmatter` round-trips frontmatter via `yaml.safe_dump`, which reorders/normalizes keys — acceptable since the file is regenerated by the trailing `sync`.
