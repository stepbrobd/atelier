# Atelier

The real CI for Nix, now on GitHub Actions.

Atelier evaluates a flake and fans out one native build per derivation across
GitHub-hosted runners, each surfaced as its own check run with live logs. A rule
file `atelier.toml` at the repo root selects what to build with dotted glob
patterns (similar to garnix, rip) matched against the full flake attribute path.

## Rule file

`atelier.toml` has three keys, all optional. An omitted key falls back to its
default, so an empty file builds the defaults below.

| key       | type            | default                                   | meaning                                    |
| --------- | --------------- | ----------------------------------------- | ------------------------------------------ |
| `systems` | list of strings | `["x86_64-linux"]`                        | systems to evaluate and build for          |
| `include` | list of globs   | `["packages.*.*", "devShells.*.default"]` | attributes to build                        |
| `exclude` | list of globs   | `[]`                                      | attributes to drop (exclude beats include) |

### Supported systems

Only three systems are supported, each mapped to a GitHub-hosted runner. A
system listed in `systems` that is not one of these is skipped with a warning.

| system           | runner             |
| ---------------- | ------------------ |
| `x86_64-linux`   | `ubuntu-latest`    |
| `aarch64-linux`  | `ubuntu-24.04-arm` |
| `aarch64-darwin` | `macos-latest`     |

### Matching

Matching is dot-segmented with an equal segment count and fnmatch per segment,
so a bare `*` spans exactly one segment and a nested scope needs its own
segment. Thus `legacyPackages.*.*` matches `legacyPackages.x86_64-linux.caddy`
but not `legacyPackages.x86_64-linux.ocamlPackages.dune`, which needs the
explicit `legacyPackages.*.ocamlPackages.*`.

`packages`, `legacyPackages`, `checks` and `devShells` are addressed per system
as `<set>.<system>.<rest>`. `nixosConfigurations` and `darwinConfigurations` are
addressed by host as `<set>.<host>` and built through their
`config.system.build.toplevel`.

Manual excludes drop an attribute entirely. Broken and unsupported-platform
attributes are detected from their eval error and reported as a skipped check
rather than a build failure.

### Example

```toml
# systems to evaluate and build for; omit to default to ["x86_64-linux"]
systems = ["x86_64-linux", "aarch64-linux", "aarch64-darwin"]

# include selects, exclude removes, exclude wins
# omit include to default to ["packages.*.*", "devShells.*.default"]
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

## Binary cache

Builds optionally push their results to a binary cache so later runs (and your
machines) pull instead of rebuild. Configure one under **Settings -> Secrets and
variables -> Actions** with repository **variables** and **secrets**. Atelier
supports Attic and Cachix; if both are configured, Attic wins.

Attic:

| name           | kind     | value                 |
| -------------- | -------- | --------------------- |
| `ATTIC_SERVER` | variable | attic server endpoint |
| `ATTIC_CACHE`  | variable | cache name            |
| `ATTIC_TOKEN`  | secret   | push token            |

Cachix:

| name                 | kind     | value                  |
| -------------------- | -------- | ---------------------- |
| `CACHIX_CACHE`       | variable | cache name             |
| `CACHIX_AUTH_TOKEN`  | secret   | auth token             |
| `CACHIX_SIGNING_KEY` | secret   | signing key (optional) |

Pushes happen on a push to your repository's default branch (or `master`) and on
a run with `push: true`. Forked-PR runs never push.

## Use it in your repo

Atelier runs against whatever repository calls it. `actions/checkout` inside the
reusable workflow checks out the **caller**, so `--flake .` evaluates your flake
and every check run lands on your commit. The atelier tool itself is fetched
from the published flake, so your flake stays entirely your own.

### Call the reusable workflow (recommended)

Add an `atelier.toml` to your repository root, then a thin workflow that calls
atelier:

```yaml
# .github/workflows/atelier.yaml
name: Atelier
on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:

permissions:
  contents: read
  checks: write # so skipped-attribute checks can be posted

jobs:
  atelier:
    uses: stepbrobd/atelier/.github/workflows/discover.yaml@master
    secrets:
      ATTIC_TOKEN: ${{ secrets.ATTIC_TOKEN }}
      CACHIX_AUTH_TOKEN: ${{ secrets.CACHIX_AUTH_TOKEN }}
      CACHIX_SIGNING_KEY: ${{ secrets.CACHIX_SIGNING_KEY }}
```

Map only the cache secrets you use. `secrets: inherit` is a tempting shortcut,
but GitHub forwards inherited secrets only when the caller is in the **same
organization or enterprise** as atelier - across accounts it silently passes
nothing, so an explicit map is the portable choice. Configuration **variables**
(`vars.ATTIC_CACHE` and friends) need no passing: GitHub resolves `vars` against
_your_ repository automatically, so your cache name, token, and the pushes all
stay yours. Pin `@master` to track the latest, or a tag/SHA to pin a version.
Make `Gate` the single required status in branch protection: it stays green
whether the matrix is empty, every build passes, or attributes are skipped.

### Fork it (alternative)

Prefer a fork if you want to hack on atelier itself or keep a vendored copy.
Fork the repo, enable Actions on the fork, add your cache secrets and variables,
edit `atelier.toml`, and pull upstream improvements with **Sync fork**.
