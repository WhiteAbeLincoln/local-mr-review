{
  description = "mr-review — GitLab merge-request review CLI";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
      ...
    }:
    let
      inherit (nixpkgs) lib;
      forAllSystems = lib.genAttrs lib.systems.flakeExposed;

      # uv2nix parses pyproject.toml + uv.lock in pure Nix (no import-from-derivation)
      # and produces an overlay of the locked dependency set.
      workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };

      # Prefer wheels. The uv_build backend used by this project is only available
      # as a wheel (build-system-pkgs marks uv-build as no-build because its sdist
      # needs Rust), so this preference must be paired with overlays.wheel below.
      overlay = workspace.mkPyprojectOverlay { sourcePreference = "wheel"; };

      # Per-system Python package set. The project requires Python >=3.14 and
      # nixpkgs' default python3 is still 3.13, so pin python314 explicitly.
      pythonSets = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          python = pkgs.python314;
        in
        (pkgs.callPackage pyproject-nix.build.packages { inherit python; }).overrideScope (
          lib.composeManyExtensions [
            pyproject-build-systems.overlays.wheel
            overlay
          ]
        )
      );
    in
    {
      # Derivation: a virtualenv in the Nix store holding mr-review plus its locked
      # runtime dependencies, exposing bin/mr-review.
      packages = forAllSystems (system: {
        default = pythonSets.${system}.mkVirtualEnv "mr-review-env" workspace.deps.default;
      });

      # Flake program: `nix run` launches the CLI.
      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/mr-review";
        };
      });

      # Impure dev shell: provides the pinned interpreter + uv and lets uv manage
      # the .venv (uv sync), matching the existing workflow. CI is responsible for
      # asserting uv.lock is current so the locked derivation above stays in sync
      # with what development happens against.
      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.mkShell {
            packages = [
              pkgs.python314
              pkgs.uv
            ];
            env = {
              UV_PYTHON_DOWNLOADS = "never";
              UV_PYTHON = pkgs.python314.interpreter;
            };
            shellHook = ''
              unset PYTHONPATH
            '';
          };
        }
      );
    };
}
