{
  outputs = inputs: inputs.parts.lib.mkFlake { inherit inputs; } {
    systems = import inputs.systems;

    perSystem = { lib, pkgs, ... }:
      let
        python = pkgs.python314;
        workspace = inputs.pypuv.lib.workspace.loadWorkspace { workspaceRoot = ./.; };
        pythonPackages = (pkgs.callPackage inputs.pyp.build.packages { inherit python; }).overrideScope (
          lib.composeManyExtensions [
            inputs.pypbs.overlays.wheel
            (workspace.mkPyprojectOverlay { sourcePreference = "wheel"; })
          ]
        );
      in
      {
        packages.default = pythonPackages.mkVirtualEnv
          (with (lib.importTOML ./pyproject.toml).project; "${name}-${version}")
          workspace.deps.default;

        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            mypy
            nixpkgs-fmt
            python
            python.pkgs.venvShellHook
            ruff
            uv
          ];

          venvDir = "./.venv";
          preShellHook = "uv venv $venvDir";
          postShellHook = "uv sync";

          UV_PYTHON = python.interpreter;
          UV_PYTHON_DOWNLOADS = "never";
          UV_VENV_CLEAR = true;

          LD_LIBRARY_PATH = lib.makeLibraryPath (with pkgs; [ stdenv.cc.cc ]);
        };

        formatter = pkgs.writeShellScriptBin "formatter" ''
          set -eoux pipefail
          shopt -s globstar
          root="$PWD"
          while [[ ! -f "$root/.git/index" ]]; do
            if [[ "$root" == "/" ]]; then
              exit 1
            fi
            root="$(dirname "$root")"
          done
          pushd "$root" > /dev/null
          ${lib.getExe pkgs.deno} fmt **/*.md **/*.yaml
          ${lib.getExe pkgs.mypy} --disable-error-code=import .
          ${lib.getExe pkgs.nixpkgs-fmt} .
          ${lib.getExe pkgs.ruff} check --fix --unsafe-fixes --preview .
          ${lib.getExe pkgs.taplo} format pyproject.toml
          popd
        '';
      };
  };

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixpkgs-unstable";
    parts.url = "github:hercules-ci/flake-parts";
    parts.inputs.nixpkgs-lib.follows = "nixpkgs";
    systems.url = "github:nix-systems/triplet";
    pyp.url = "github:pyproject-nix/pyproject.nix";
    pyp.inputs.nixpkgs.follows = "nixpkgs";
    pypbs.url = "github:pyproject-nix/build-system-pkgs";
    pypbs.inputs.pyproject-nix.follows = "pyp";
    pypbs.inputs.uv2nix.follows = "pypuv";
    pypbs.inputs.nixpkgs.follows = "nixpkgs";
    pypuv.url = "github:pyproject-nix/uv2nix";
    pypuv.inputs.nixpkgs.follows = "nixpkgs";
    pypuv.inputs.pyproject-nix.follows = "pyp";
  };
}
