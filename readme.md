# Atelier

The real CI for Nix now on GitHub Actions!

The rule file `atelier.toml` at the repo root selects what to build with dotted
glob patterns similar to garnix (rip) matched against the full flake attribute
path.

```toml
# systems to evaluate and build for, omitted defaults to ["x86_64-linux"]
systems = ["x86_64-linux", "aarch64-linux", "aarch64-darwin"]

# include selects, exclude removes, exclude wins
# matching is dot segmented with equal segment count and fnmatch per segment
# a bare * is exactly one segment so a nested scope needs its own segment
include = [
  "legacyPackages.*.*",               # top level packages
  "legacyPackages.*.ocamlPackages.*", # a nested scope
  "devShells.*.default",
  "nixosConfigurations.*",            # built via config.system.build.toplevel
  "darwinConfigurations.*",           # built via config.system.build.toplevel
]

exclude = [
  "legacyPackages.*.spotify", # unfree
]
```

`packages`, `legacyPackages`, `checks` and `devShells` are addressed per system
as `<set>.<system>.<rest>`. `nixosConfigurations` and `darwinConfigurations` are
addressed by host as `<set>.<host>` and built through their
`config.system.build.toplevel`.

Manual excludes drop an attribute entirely. Broken and unsupported platform
attributes are detected from their eval error and reported as a skipped check.

## GitHub Actions

Add `atelier.toml` to repository root, then a workflow that calls the reusable
build:

```yaml
on:
  push:
    branches: [master]
  pull_request:
  workflow_dispatch:

jobs:
  atelier:
    uses: stepbrobd/atelier/.github/workflows/discover.yaml@master
    secrets: inherit
```
