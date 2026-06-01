# Atelier

<img width="282" height="272" alt="Image" src="https://github.com/user-attachments/assets/f73ea161-e210-4b5e-9f37-12c03885be39" />

The real CI for Nix, now on GitHub Actions!

Inspired by [nixpkgs-review-gha](https://github.com/Defelo/nixpkgs-review-gha)
and [garnix](https://github.com/garnix-io/garnix-ci) (RIP).

The `atelier` name is stolen from
[とんがり帽子のアトリエ](https://tongari-anime.com)'s English localization
(great manga/anime btw, I caught up with the manga in a little less than a week,
that's how good it is).

Atelier evaluates a flake and fans out one native build per derivation across
GitHub-hosted runners, each surfaced as its own check run with live logs. An
optional rule file `atelier.toml` at the repo root selects what to build with
dotted glob patterns (similar to garnix, rip) matched against the full flake
attribute path; with no rule file, the built-in defaults apply.

See check status in [my config repo](https://github.com/stepbrobd/inc) (push
target is secretless [niks3](https://github.com/Mic92/niks3) with GHA OIDC),
click on the green/yellow/red dot/cross associated with commits.

<img width="625" height="444" alt="Image" src="https://github.com/user-attachments/assets/c516818a-68ad-4b7c-9322-553a5585e6ba" />

Known limitations:

- It is recommended that all users to setup a cache endpoint or all builds will
  be lost
- Matrix jobs are independent, duplicate builds are expected. See more
  [here](https://github.com/stepbrobd/atelier/issues/1)
- GitHub app created PRs will not trigger build. See example
  [here](https://github.com/stepbrobd/inc/pull/200/checks). Do note that you can
  invoke the action with in automated jobs like
  [this](https://github.com/stepbrobd/inc/blob/e4e29f450f9614820aa1ee4cff9e18d1f13e9232/.github/workflows/bump.yaml#L146-L151)
  but the check status will only be associated with the commit, not the PR.
  However dependabot created PRs
  [will work](https://github.com/stepbrobd/inc/pull/201/checks)
- If you have niks3 as cache push target, consider adding
  `https://cache.ysun.co` to the substituters list, see reasonings
  [here](https://github.com/stepbrobd/atelier/issues/3#issuecomment-4591554271)

## Rule file

`atelier.toml` is itself optional, as are its four keys. A missing rule file (or
an omitted key) falls back to the defaults below, so a repository with no
`atelier.toml` at all builds the defaults.

| key            | type            | default                                   | meaning                                              |
| -------------- | --------------- | ----------------------------------------- | ---------------------------------------------------- |
| `systems`      | list of strings | `["x86_64-linux"]`                        | systems to evaluate and build for                    |
| `include`      | list of globs   | `["packages.*.*", "devShells.*.default"]` | attributes to build                                  |
| `exclude`      | list of globs   | `[]`                                      | attributes to drop (exclude beats include)           |
| `substituters` | list of strings | `[]`                                      | extra caches to check; a cached attribute is skipped |

### Skipping cached builds

Before building, atelier checks each attribute's outputs against `substituters`
(the official cache `https://cache.nixos.org` is always added, deduplicated). An
attribute already present in any of them is reported as a skipped check
`Already in the binary cache` rather than built, so no runner is spun up to
rebuild and re-push a path the cache already holds. Only outputs available from
a shared cache are skipped; a path present solely on the eval runner still
builds, since another runner could not substitute it.

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

# caches checked before building; an attr already in one is skipped, not rebuilt
# https://cache.nixos.org is always checked, so listing only your own is enough
substituters = ["https://cache.example.org"]
```

## Binary cache

Builds optionally push their results to a binary cache so later runs (and your
machines) pull instead of rebuild. Configure one under **Settings -> Secrets and
variables -> Actions** with repository **variables** and **secrets**. Atelier
supports Attic, Cachix, and niks3, and pushes to every backend you configure.

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

niks3:

| name           | kind     | value                                       |
| -------------- | -------- | ------------------------------------------- |
| `NIKS3_SERVER` | variable | niks3 server URL                            |
| `NIKS3_TOKEN`  | secret   | bearer token (optional, enables token auth) |

niks3 authenticates with GitHub Actions OIDC by default: set only `NIKS3_SERVER`
and grant the calling workflow `id-token: write` (see the example below). For
OIDC the niks3 server must have a GitHub OIDC provider whose bound claims admit
your repository. Setting the `NIKS3_TOKEN` secret instead switches to that
static token and needs no `id-token` permission. Unlike Attic and Cachix, niks3
has no separate cache name - the server URL identifies the cache.

Pushes happen on a push to your repository's default branch (or `master`) and on
a run with `push: true`. Forked-PR runs never push. Caching is best-effort: a
failed push to any backend is logged as a warning and never fails the build.

## Use it in your repo

Atelier runs against whatever repository calls it. `actions/checkout` inside the
reusable workflow checks out the **caller**, so `--flake .` evaluates your flake
and every check run lands on your commit. The atelier tool itself is fetched
from the published flake, so your flake stays entirely your own.

### Call the reusable workflow (recommended)

Add a thin workflow that calls atelier (optionally with an `atelier.toml` at
your repository root to customize what is built; without one, the built-in
defaults are used):

```yaml
# .github/workflows/ci.yaml
name: CI
on:
  push:
    # what's your branch name?
    branches: [main]
  pull_request:
  workflow_dispatch:

permissions:
  # required:
  contents: read

  # required:
  # so skipped-attribute checks can be posted
  checks: write

  # optional:
  # so niks3 can push via OIDC (omit if you use NIKS3_TOKEN)
  # id-token: write

jobs:
  Atelier:
    uses: stepbrobd/atelier/.github/workflows/discover.yaml@master

    # uncomment the ones you need:
    # without the secrets this job will build everything from scratch
    # on every trigger and will not push to cache
    # set a cache end point (preferable matching the one in `atelier.toml`)
    # so that jobs can be skipped if they already exist in cache

    # secrets:
    #   ATTIC_TOKEN: ${{ secrets.ATTIC_TOKEN }}
    #   CACHIX_AUTH_TOKEN: ${{ secrets.CACHIX_AUTH_TOKEN }}
    #   CACHIX_SIGNING_KEY: ${{ secrets.CACHIX_SIGNING_KEY }}
    #   NIKS3_TOKEN: ${{ secrets.NIKS3_TOKEN }}
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

## Custom Nix installer

By default Atelier installs upstream Nix with `nixos/nix-installer-action`. Two
optional inputs change that without forking:

| input             | type   | default | meaning                                                             |
| ----------------- | ------ | ------- | ------------------------------------------------------------------- |
| `install-command` | string | `""`    | Shell command that installs Nix, when set it replaces the installer |
| `extra-conf`      | string | `""`    | Extra `nix.conf` lines appended after Atelier's required settings   |

Atelier separates installing Nix from configuring it. Whichever installer runs,
Atelier applies its own required `nix.conf` afterwards (the GitHub access token,
`experimental-features = nix-command flakes`, the build directory, the target
`system`, and the sandbox mode), then appends your `extra-conf` last. So a
custom installer still ends up with a correctly configured daemon, and adding
settings is independent of the installer choice. Use Nix's `extra-` prefixes to
add to a list setting rather than replace it.

The inputs apply to every job, so discovery and every build cell use the same
Nix. Install Lix instead of upstream Nix and enable the pipe operator:

```yaml
jobs:
  Atelier:
    uses: stepbrobd/atelier/.github/workflows/discover.yaml@master
    with:
      install-command: curl -sSf -L https://install.lix.systems/lix | sh -s -- install --no-confirm
      extra-conf: |
        extra-experimental-features = pipe-operator
```

Do note that Lix names the pipe-operator feature `pipe-operator` (singular),
whereas upstream Nix names it `pipe-operators` (plural). Match your installer!
See more about the discrepancy
[here](https://discourse.nixos.org/t/lix-mismatch-in-feature-name-compared-to-nix/59879).

A custom `install-command` runs on a fresh runner, so it must be non-interactive
and install a working multi-user daemon. Atelier reloads the daemon after
applying its configuration. If your installer does not set one up, the build
settings will not take effect.

### Fork it (alternative)

Prefer a fork if you want to hack on atelier itself or keep a vendored copy.
Fork the repo, enable Actions on the fork, add your cache secrets and variables,
edit `atelier.toml`, and pull upstream improvements with **Sync fork**.
