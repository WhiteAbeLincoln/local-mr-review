# CI & pre-commit setup — design

**Date:** 2026-06-25
**Status:** Approved (pending spec review)

## Goal

Set up continuous integration for `mr-review` (a uv + Nix-flake Python 3.14
project hosted on GitHub) plus a local pre-commit safety net. CI must:

1. Assert `uv.lock` is in sync with `pyproject.toml`.
2. Enforce `ruff format` and `ruff check`.
3. Type-check the project — introducing **pyrefly** (Meta's Rust type checker),
   which the project does not currently use.
4. Run the existing pytest suite.
5. Verify the Nix flake derivation still builds.

A local **prek** pre-commit (Nix-generated, cairn-style) shares one definition
with CI so the same checks run before code is pushed and again on the server.

## Key design decision: one source of truth, Nix-centric

The check definitions live once in `nix/hooks.nix` and are consumed in two
places:

- **Locally** — `cachix/git-hooks.nix` generates `.pre-commit-config.yaml`
  (a symlink into the Nix store) and installs a git hook via the dev shell's
  `shellHook`. Running `prek` / `validate-changes` executes the hooks.
- **In CI** — the workflow runs *inside `nix develop`* and invokes the same
  `validate-changes --all` wrapper, so CI cannot drift from local hooks.

Because the generated config only materializes inside a Nix environment, CI is
deliberately Nix-centric rather than uv-native. This avoids duplicating the
lint/format/type/lock commands in workflow YAML.

Tools are invoked via `uv run …` (not nixpkgs-provided ruff/pyrefly) so the
versions exactly match `uv.lock`. `ruff` formatting is version-sensitive, so
"the version CI uses" must equal "the version the lockfile pins."

## Components

### 1. `pyproject.toml` changes

- Add `pyrefly` to `[dependency-groups] dev` (alongside `pytest`, `ruff`).
- Add `prek` to `[dependency-groups] dev` so `uv run prek` is available even
  outside the Nix shell (the Nix dev shell also provides `pkgs.prek`).
- Add a `[tool.pyrefly]` section. Start minimal — `project-includes = ["src",
  "tests"]` and `python-version = "3.14"` — generated/validated with
  `uv run pyrefly init` during implementation, then trimmed to what we need.
- `uv lock` to record the new dev deps; commit the updated `uv.lock`.

### 2. `nix/hooks.nix` (new, adapted from `../cairn/nix/hooks.nix`)

Calls `git-hooks.lib.${system}.run` with `package = pkgs.prek`. Hooks, each a
`writeShellScript` entry, `pass_filenames = false`, `require_serial = true`:

| Hook          | Command (normal)            | Under `VALIDATE_FIX=1`        | Files            | Stage       |
|---------------|-----------------------------|-------------------------------|------------------|-------------|
| `ruff-format` | `uv run ruff format --check`| `uv run ruff format`          | `\.py$`          | pre-commit  |
| `ruff-check`  | `uv run ruff check`         | `uv run ruff check --fix`     | `\.py$`          | pre-commit  |
| `pyrefly`     | `uv run pyrefly check`      | (same)                        | `\.py$`          | pre-commit  |
| `uv-lock`     | `uv lock --check`           | (same)                        | `pyproject\.toml\|uv\.lock` | pre-commit |
| `pytest`      | `uv run pytest`             | (same)                        | `\.py$`          | **pre-push**|

`pytest` runs at the **pre-push** stage (`stages = ["pre-push"]`) so it does not
slow every commit, but still gates pushes locally and runs in CI.

### 3. `nix/validate-changes.sh` (new, adapted from cairn)

The same wrapper cairn uses, with `FORMATTER_HOOKS=(ruff-format ruff-check)`
(both support `--fix`). Supports `--all`, `--fix`, `--log[=FILE]`, `--tee`,
`--hooks`, and `-- file …`. Default behaviour runs hooks against files changed
since `HEAD`. CI uses `validate-changes --all`.

### 4. `flake.nix` changes

- Add input `git-hooks.url = "github:cachix/git-hooks.nix"` with
  `inputs.nixpkgs.follows = "nixpkgs"`.
- Import `nix/hooks.nix` per-system (passing `pkgs`, `git-hooks`, `system`).
- Build `validate-changes` via `pkgs.writeShellApplication` with
  `runtimeInputs = pre-commit.enabledPackages ++ [ pkgs.uv ]` (hooks shell out
  to `uv run`).
- Dev shell additions: `pkgs.prek`, `validate-changes`, and
  `pre-commit.enabledPackages`; prepend `pre-commit.shellHook` to the existing
  `shellHook` (keep the `unset PYTHONPATH` line and the UV env pins).
- **Not** added to `flake.checks`: the hooks call `uv run`, which needs network
  and a synced `.venv` unavailable in the `nix flake check` sandbox. Pre-commit
  parity is enforced by CI running the hooks in `nix develop`, not by a
  sandboxed check derivation. `packages.default` remains the build that
  `nix flake check` / `nix build` exercises.

### 5. `.github/workflows/ci.yml` (new)

```yaml
name: CI
on:
  push: { branches: [main] }
  pull_request:
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: DeterminateSystems/nix-installer-action@main   # flakes enabled
      - uses: nix-community/cache-nix-action@v6              # /nix/store in GH cache
        with: { primary-key: nix-${{ runner.os }}-${{ hashFiles('flake.lock','uv.lock') }} }
      - run: nix develop -c uv sync --locked
      - run: nix develop -c validate-changes --all          # ruff-format, ruff-check, pyrefly, uv-lock
      - run: nix develop -c uv run pytest                   # pytest (the pre-push hook's CI counterpart)
  nix-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: DeterminateSystems/nix-installer-action@main
      - uses: nix-community/cache-nix-action@v6
        with: { primary-key: nix-${{ runner.os }}-${{ hashFiles('flake.lock','uv.lock') }} }
      - run: nix build .#default                            # uv2nix derivation still builds
```

Exact action pins/versions resolved during implementation. `validate-changes
--all` runs every commit-stage hook against all files; `uv run pytest` is run
explicitly (pytest is pre-push locally, so it is not part of `--all`).

### 6. `.github/dependabot.yml` (new)

```yaml
version: 2
updates:
  - package-ecosystem: "uv"            # GA since 2025-03; bumps uv.lock + pyproject.toml
    directory: "/"
    schedule: { interval: "weekly" }
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule: { interval: "weekly" }
```

Nix flake inputs are intentionally **not** auto-updated by Dependabot (no native
support); left to manual `nix flake update`.

## Data flow

```
developer edits .py
   │  git commit  ─▶ prek (git hook) ─▶ ruff-format, ruff-check, pyrefly, uv-lock
   │  git push    ─▶ prek pre-push   ─▶ pytest
   ▼
GitHub  ─▶  CI: check job   (nix develop ─▶ uv sync --locked ─▶ validate-changes --all ─▶ pytest)
        └▶  CI: nix-build job (nix build .#default)
```

The hook list in `nix/hooks.nix` is the single source; both the local git hook
and the CI `validate-changes --all` invocation read it.

## Error handling

- Each hook exits non-zero on failure; `prek` / CI step fails the run.
- `uv lock --check` fails (non-zero) when `uv.lock` is stale → surfaces the same
  signal the flake comment (`flake.nix:80–82`) wanted CI to provide.
- `--fix` / `VALIDATE_FIX=1` is opt-in only; CI never runs fix mode, so CI is
  read-only and never mutates the tree.
- Per user conventions: no `panic`/`unwrap` equivalents — shell hooks return
  exit codes, never `set -e` traps that mask which hook failed.

## Testing / verification

This change is configuration, not application code, so verification is by
running the real tools (no unit tests of YAML):

1. `uv sync` → `uv run pyrefly check` passes (fix any real type errors it finds;
   if numerous, scope the initial `[tool.pyrefly]` and note follow-ups).
2. `nix develop -c validate-changes --all` passes locally.
3. `nix build .#default` succeeds.
4. Make a trivial formatting violation, confirm the commit hook blocks it and
   `validate-changes --fix` repairs it.
5. Confirm the pre-push hook runs pytest on `git push` (dry-run / test branch).
6. After push, confirm both CI jobs pass on the PR.

## Out of scope

- Coverage reporting / thresholds.
- Multi-version Python matrix (project pins 3.14 only).
- Release/publish automation, container builds.
- Auto-updating Nix flake inputs.

## Risks / open items (resolve in implementation)

- **pyrefly on a fresh codebase** may report pre-existing errors. Plan: run it,
  fix quick wins, and if a class of errors is large, narrow the initial config
  and record follow-ups rather than blanket-ignoring.
- **First CI run is slow** (builds the py3.14 venv derivation) until the store
  cache is warm; `cache-nix-action` keyed on `flake.lock` + `uv.lock` mitigates
  subsequent runs.
- **`pkgs.prek` availability** in the pinned nixpkgs — verify at implementation;
  fall back to `uv run prek` if absent.
