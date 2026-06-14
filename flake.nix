{
  outputs = inputs: inputs.parts.lib.mkFlake { inherit inputs; } {
    systems = import inputs.systems;

    perSystem = { lib, pkgs, system, ... }: {
      _module.args.pkgs = import inputs.nixpkgs {
        inherit system;
        overlays = [
          (
            let pythonSelector = "python314"; in _: prev: {
              python = prev.${pythonSelector};
              pythonPackages = prev."${pythonSelector}Packages";
            }
          )
        ];
      };

      packages.default = pkgs.pythonPackages.buildPythonPackage (finalAttrs: {
        pyproject = true;

        pname = (lib.importTOML ./pyproject.toml).project.name;
        inherit ((lib.importTOML ./pyproject.toml).project) version;

        src = with lib.fileset; toSource {
          root = ./.;
          fileset = unions [
            # code
            ./src
            ./tests
            # meta
            ./license.txt
            ./pyproject.toml
            ./readme.md
          ];
        };

        build-system = [ pkgs.pythonPackages.setuptools ];

        dependencies = lib.map (n: pkgs.pythonPackages.${n}) (lib.importTOML ./pyproject.toml).project.dependencies;

        nativeCheckInputs = [ pkgs.pythonPackages.pytestCheckHook ];

        pythonImportsCheck = [ finalAttrs.pname ];
      });

      devShells.default = pkgs.mkShell {
        packages = with pkgs; [
          nixpkgs-fmt
          python
          python.pkgs.venvShellHook
          ruff
          ty
          uv
        ];

        venvDir = "./.venv";
        preShellHook = "uv venv $venvDir";
        postShellHook = "uv sync";

        UV_PYTHON = pkgs.python.interpreter;
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
        ${lib.getExe pkgs.actionlint} -color
        ${lib.getExe pkgs.deno} fmt **/*.md **/*.yaml
        ${lib.getExe pkgs.gitleaks} git --no-banner --pre-commit --staged
        ${lib.getExe pkgs.nixpkgs-fmt} .
        ${lib.getExe pkgs.ruff} check --fix --unsafe-fixes --preview .
        ${lib.getExe pkgs.taplo} format pyproject.toml
        ${lib.getExe pkgs.ty} check --fix --error all .
        ${lib.getExe pkgs.uv} run pytest
        ${lib.getExe pkgs.zizmor} --fix=all .
        popd
      '';
    };
  };

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixpkgs-unstable";
    parts.url = "github:hercules-ci/flake-parts";
    parts.inputs.nixpkgs-lib.follows = "nixpkgs";
    systems.url = "github:nix-systems/triplet";
  };
}
