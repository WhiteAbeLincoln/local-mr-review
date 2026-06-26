# Pre-commit hook definitions, the single source of truth shared by the local
# git hook (installed via the dev shell's shellHook) and CI (which runs
# `validate-changes --all` inside `nix develop`). prek is the runner.
#
# Hooks shell out to `uv run …` rather than nixpkgs-provided ruff/pyrefly so the
# tool versions exactly match uv.lock — `ruff format` output is version
# sensitive, so "the version CI uses" must equal "the version the lockfile
# pins". The dev shell sets UV_PYTHON/UV_PYTHON_DOWNLOADS so `uv run` resolves
# the pinned interpreter without a network download.
{
  pkgs,
  git-hooks,
  system,
}:
git-hooks.lib.${system}.run {
  src = ../.;
  package = pkgs.prek;
  hooks = {
    ruff-format = {
      enable = true;
      name = "ruff-format";
      description = "Check Python formatting with ruff.";
      package = pkgs.uv;
      entry = builtins.toString (pkgs.writeShellScript "ruff-format-hook" ''
        check_flag="--check"
        if [ "''${VALIDATE_FIX:-}" = "1" ]; then check_flag=""; fi
        # shellcheck disable=SC2086
        ${pkgs.uv}/bin/uv run ruff format $check_flag
      '');
      files = "\\.py$";
      pass_filenames = false;
      require_serial = true;
    };

    ruff-check = {
      enable = true;
      name = "ruff-check";
      description = "Lint Python with ruff.";
      package = pkgs.uv;
      entry = builtins.toString (pkgs.writeShellScript "ruff-check-hook" ''
        fix_flag=""
        if [ "''${VALIDATE_FIX:-}" = "1" ]; then fix_flag="--fix"; fi
        # shellcheck disable=SC2086
        ${pkgs.uv}/bin/uv run ruff check $fix_flag
      '');
      files = "\\.py$";
      pass_filenames = false;
      require_serial = true;
    };

    pyrefly = {
      enable = true;
      name = "pyrefly";
      description = "Type-check Python with pyrefly.";
      package = pkgs.uv;
      entry = builtins.toString (pkgs.writeShellScript "pyrefly-hook" ''
        ${pkgs.uv}/bin/uv run pyrefly check
      '');
      files = "\\.py$";
      pass_filenames = false;
      require_serial = true;
    };

    uv-lock = {
      enable = true;
      name = "uv-lock";
      description = "Assert uv.lock is in sync with pyproject.toml.";
      package = pkgs.uv;
      entry = builtins.toString (pkgs.writeShellScript "uv-lock-hook" ''
        ${pkgs.uv}/bin/uv lock --check
      '');
      files = "^(pyproject\\.toml|uv\\.lock)$";
      pass_filenames = false;
      require_serial = true;
    };

    # pre-push only: keep commits fast, but gate pushes (and CI runs this too,
    # via `uv run pytest` — `validate-changes --all` runs commit-stage hooks).
    pytest = {
      enable = true;
      name = "pytest";
      description = "Run the test suite.";
      package = pkgs.uv;
      entry = builtins.toString (pkgs.writeShellScript "pytest-hook" ''
        ${pkgs.uv}/bin/uv run pytest
      '');
      files = "\\.py$";
      pass_filenames = false;
      require_serial = true;
      stages = [ "pre-push" ];
    };
  };
}
