import json
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from atelier.types import (
    CONFIG_SETS,
    LEAF_SETS,
    MAX_RECURSE_DEPTH,
    PER_SYSTEM_SETS,
    RUNNERS,
    SCOPE_DENYLIST,
    SKIP_PATTERN,
    Job,
)

_SKIP_RE = re.compile(SKIP_PATTERN, re.IGNORECASE)

# embedded nix that roots the requested output sets into one attrset for
# nix-eval-jobs to recurse
#   per system sets become   "<set>.<system>" = sanitize flake.<set>.<system>
#   config sets become       "<set>"          = mapAttrs toplevel flake.<set>
#   leaf sets become         "<set>.<system>" = flake.<set>.<system> (a drv)
# per system sets are sanitized first: a re-exported nixpkgs package set carries
# scope plumbing (the whole `lib`, callPackage/newScope functions, a self
# referential alias) that force-recurse would otherwise dive into, burning the
# runner's memory until it is OOM killed. sanitize prunes that plumbing and bounds
# the recursion to the include globs' depth, leaving only buildable leaves.
# the @TOKENS@ are replaced with allowlisted nix string lists, never raw input
_SELECT_TEMPLATE = r"""flake:
let
  o = flake.outputs;
  systems = [ @SYSTEMS@ ];
  perSystemSets = [ @PER_SYSTEM@ ];
  configSets = [ @CONFIG@ ];
  leafSets = [ @LEAF@ ];
  # exact leaf names per set to drop before recursing, so nix-eval-jobs never
  # forces (and never fetches or builds) a manually excluded attribute
  excludes = { @EXCLUDES@ };
  # the deepest attribute path the include globs can match; recursion below it can
  # never be selected, so it stops there (a `**` glob raises this to a hard cap).
  # a per system set roots at "<set>.<sys>" (two path segments), so its children
  # are at depth three and the remaining attrset recursion budget is maxDepth - 3
  maxDepth = @MAXDEPTH@;
  startDepth = if maxDepth > 3 then maxDepth - 3 else 0;
  # scope-internal attrset names that are never buildable; function valued plumbing
  # is dropped structurally below, so this only names the attrset valued plumbing
  denylist = [ @DENYLIST@ ];
  # prune scope plumbing before nix-eval-jobs force-recurses: keep derivations as
  # leaves, drop functions (callPackage, newScope, ...) and self referential
  # aliases (recurseForDerivations = false), recurse plain attrsets only while the
  # include depth can still match, and keep an attr that throws on classification
  # so nix-eval-jobs reports it as that attribute's own eval error rather than
  # dropping it silently. forcing a child to classify it stays inside tryEval, so
  # a broken attribute cannot abort the whole evaluation
  sanitize = remaining: set:
    let cleaned = builtins.removeAttrs set denylist;
    in builtins.listToAttrs (builtins.concatMap (name:
      let
        raw = cleaned.${name};
        probe = builtins.tryEval (
          if builtins.isFunction raw then "fn"
          else if (raw.type or null) == "derivation" then "drv"
          else if builtins.isAttrs raw then
            (if (raw.recurseForDerivations or true) == false then "norec" else "attrs")
          else "other");
        kind = if probe.success then probe.value else "throws";
      in
        if kind == "drv" || kind == "throws"
        then [ { inherit name; value = raw; } ]
        else if kind == "attrs" && remaining > 0
        then [ { inherit name; value = sanitize (remaining - 1) raw; } ]
        else [ ]
    ) (builtins.attrNames cleaned));
  ps = builtins.foldl' (acc: set:
        builtins.foldl' (a: sys:
          if (o ? ${set}) && (o.${set} ? ${sys})
          then a // { "${set}.${sys}" = sanitize startDepth (builtins.removeAttrs o.${set}.${sys} ((excludes.${set}.${sys} or [ ]) ++ (excludes.${set}."*" or [ ]))); }
          else a
        ) acc systems
      ) { } perSystemSets;
  cs = builtins.foldl' (acc: set:
        if o ? ${set}
        then acc // { "${set}" = builtins.mapAttrs (_: c: c.config.system.build.toplevel) o.${set}; }
        else acc
      ) { } configSets;
  # a leaf set's system attribute is the derivation itself, so it roots
  # directly with nothing below it to recurse into or prune. a non derivation
  # value (a schema violation) throws lazily so it surfaces as that attribute's
  # eval error instead of being recursed into and silently dropped
  ls = builtins.foldl' (acc: set:
        builtins.foldl' (a: sys:
          if (o ? ${set}) && (o.${set} ? ${sys})
          then a // { "${set}.${sys}" =
            let v = o.${set}.${sys}; in
            if (v.type or null) == "derivation" then v
            else throw "flake output ${set}.${sys} is not a derivation"; }
          else a
        ) acc systems
      ) { } leafSets;
in ps // cs // ls
"""


def _nix_str(value: str) -> str:
    """Quote a value as a nix string literal, escaping injection vectors.

    Exclude leaf names come from the rule file, so escape backslashes, quotes,
    and the ``${`` interpolation opener before embedding them in the expression.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("${", "\\${")
    return f'"{escaped}"'


def _nix_list(items: Sequence[str]) -> str:
    return " ".join(_nix_str(item) for item in items)


def _nix_excludes(exclude_leaves: Mapping[str, Mapping[str, Sequence[str]]]) -> str:
    """Render ``"set" = { "sys" = [ "leaf" ... ]; ... };`` for the ``excludes`` attrset.

    ``sys`` is either ``"*"`` (drop from every system) or a specific system.
    """
    sets = []
    for set_name, by_system in exclude_leaves.items():
        pairs = " ".join(
            f"{_nix_str(system)} = [ {_nix_list(leaves)} ];"
            for system, leaves in by_system.items()
        )
        sets.append(f"{_nix_str(set_name)} = {{ {pairs} }};")
    return " ".join(sets)


def _build_select(
    systems: Sequence[str],
    per_system_sets: Sequence[str],
    config_sets: Sequence[str],
    leaf_sets: Sequence[str] = (),
    exclude_leaves: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
    max_depth: int = MAX_RECURSE_DEPTH,
) -> str:
    # fail closed if an unallowlisted value ever reaches the embedded nix
    # the discover layer already filters these, this guards against a future
    # refactor dropping that filtering and allowing nix injection
    for system in systems:
        if system not in RUNNERS:
            raise ValueError(f"unknown system {system!r}")
    for output in (*per_system_sets, *config_sets, *leaf_sets):
        if (
            output not in PER_SYSTEM_SETS
            and output not in CONFIG_SETS
            and output not in LEAF_SETS
        ):
            raise ValueError(f"unknown output set {output!r}")
    leaves = exclude_leaves or {}
    # set names are allowlisted, leaf names are escaped (they are arbitrary)
    for output in leaves:
        if output not in PER_SYSTEM_SETS:
            raise ValueError(f"unknown output set {output!r}")
    return (
        _SELECT_TEMPLATE.replace("@SYSTEMS@", _nix_list(systems))
        .replace("@PER_SYSTEM@", _nix_list(per_system_sets))
        .replace("@CONFIG@", _nix_list(config_sets))
        .replace("@LEAF@", _nix_list(leaf_sets))
        .replace("@EXCLUDES@", _nix_excludes(leaves))
        # an int, so it cannot carry an injection; clamped to the hard cap
        .replace("@MAXDEPTH@", str(min(int(max_depth), MAX_RECURSE_DEPTH)))
        .replace("@DENYLIST@", _nix_list(SCOPE_DENYLIST))
    )


def _eval_command(
    flake: str, select: str, workers: int, substituters: Iterable[str]
) -> list[str]:
    """The nix-eval-jobs argv, checking cache status against `substituters`.

    `--check-cache-status` tags each attribute with whether its outputs are
    already in a queried cache (a `cacheStatus` field), so discovery can skip
    building cached ones. The caches are sorted for a stable command, and
    `require-sigs` is disabled because an existence check only asks whether the
    path is in the cache, not whether this host trusts the cache's signing key:
    the runner never imports these paths, and an untrusted hit would otherwise be
    ignored (nix-eval-jobs reads no flake `nixConfig`, so the keys are unknown).
    """
    cmd = [
        "nix",
        "run",
        # "nixpkgs#nix-eval-jobs",
        # TODO: drop after new nix-eval-jobs tag
        # ref https://github.com/stepbrobd/atelier/issues/17
        "github:stepbrobd/inc#nix-eval-jobs",
        "--",
        "--flake",
        flake,
        "--force-recurse",
        "--check-cache-status",
        "--workers",
        str(workers),
    ]
    caches = sorted(substituters)
    if caches:
        cmd += [
            "--option",
            "extra-substituters",
            " ".join(caches),
            "--option",
            "require-sigs",
            "false",
        ]
    cmd += ["--select", select]
    return cmd


def evaluate(
    flake: str,
    systems: Sequence[str],
    per_system_sets: Sequence[str],
    config_sets: Sequence[str],
    leaf_sets: Sequence[str] = (),
    workers: int = 4,
    exclude_leaves: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
    substituters: Iterable[str] = (),
    max_depth: int = MAX_RECURSE_DEPTH,
) -> list[dict[str, Any]]:
    """Run nix-eval-jobs over the rooted output sets and return one object per attr.

    Per attribute eval errors are reported inline as objects carrying an `error`
    field and never abort the run. A non zero exit is a fatal evaluation failure
    of the whole flake and is raised. `exclude_leaves` names attributes pruned
    before recursion so they are never evaluated, fetched, or built.
    `substituters` are the caches each attribute's cache status is checked against.
    `max_depth` bounds the per system scope recursion to the include globs' depth,
    so a re-exported package set is not force-recursed into the whole nixpkgs lib.
    """
    select = _build_select(
        systems, per_system_sets, config_sets, leaf_sets, exclude_leaves, max_depth
    )
    cmd = _eval_command(flake, select, workers, substituters)
    # capture stdout (the json results) but let stderr stream to the log live,
    # so fetches, getFlake calls, and per-attr eval progress are visible instead
    # of buffered until the end, where a slow eval looks like a frozen run
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"nix-eval-jobs failed for {flake!r} (see the log above)")
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def to_job(obj: dict[str, Any]) -> Job:
    """Normalise one nix-eval-jobs object into a `Job`.

    The rooted key carries the set (and system, for per system and leaf sets) so
    the full attribute path and the buildable installable reconstruct from attrPath.
    """
    path = ".".join(obj.get("attrPath") or [])
    drv = obj.get("drvPath")
    error = obj.get("error")
    # "cached" (set by --check-cache-status) means every output is in a queried
    # binary cache. "local" (this runner's store only) and "notBuilt" are not
    # cross-runner safe, so only an outright "cached" is treated as cached.
    cached = obj.get("cacheStatus") == "cached"
    set_name = path.split(".")[0] if path else ""

    if set_name in CONFIG_SETS:
        system = obj.get("system") or ""
        installable = f".#{path}.config.system.build.toplevel" if drv else ""
    else:
        segments = path.split(".")
        system = segments[1] if len(segments) > 1 else (obj.get("system") or "")
        installable = f".#{path}" if drv else ""

    return Job(
        path=path, system=system, installable=installable, error=error, cached=cached
    )


def clean_error(error: str) -> str:
    """Collapse a nix eval error to a single readable line.

    Nix wraps the actionable message in assert boilerplate, so keep the text
    after the last `error:` marker where the real reason lives.
    """
    flat = " ".join(error.split())
    parts = flat.split("error:")
    message = f"error: {parts[-1].strip()}" if len(parts) > 1 else flat
    # neutralise github workflow-command markers in attacker controlled text
    # so a crafted eval error cannot spoof annotations when printed in a cell;
    # collapse every run of colons since a lone replace leaves "::" on odd runs
    return re.sub(r":{2,}", ":", message.strip())[:400]


def is_skippable(error: str) -> bool:
    """True when an eval error denotes an expected unbuildable attribute."""
    return _SKIP_RE.search(error) is not None
