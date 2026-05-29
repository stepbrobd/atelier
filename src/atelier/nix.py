import json
import re
import subprocess
from collections.abc import Sequence
from typing import Any

from atelier.types import CONFIG_SETS, PER_SYSTEM_SETS, RUNNERS, SKIP_PATTERN, Job

_SKIP_RE = re.compile(SKIP_PATTERN, re.IGNORECASE)

# embedded nix that roots the requested output sets into one attrset for
# nix-eval-jobs to recurse
#   per system sets become   "<set>.<system>" = flake.<set>.<system>
#   config sets become       "<set>"          = mapAttrs toplevel flake.<set>
# the @TOKENS@ are replaced with allowlisted nix string lists, never raw input
_SELECT_TEMPLATE = r"""flake:
let
  o = flake.outputs;
  systems = [ @SYSTEMS@ ];
  perSystemSets = [ @PER_SYSTEM@ ];
  configSets = [ @CONFIG@ ];
  ps = builtins.foldl' (acc: set:
        builtins.foldl' (a: sys:
          if (o ? ${set}) && (o.${set} ? ${sys})
          then a // { "${set}.${sys}" = o.${set}.${sys}; }
          else a
        ) acc systems
      ) { } perSystemSets;
  cs = builtins.foldl' (acc: set:
        if o ? ${set}
        then acc // { "${set}" = builtins.mapAttrs (_: c: c.config.system.build.toplevel) o.${set}; }
        else acc
      ) { } configSets;
in ps // cs
"""


def _nix_list(items: Sequence[str]) -> str:
    return " ".join(f'"{item}"' for item in items)


def _build_select(
    systems: Sequence[str],
    per_system_sets: Sequence[str],
    config_sets: Sequence[str],
) -> str:
    # fail closed if an unallowlisted value ever reaches the embedded nix
    # the discover layer already filters these, this guards against a future
    # refactor dropping that filtering and allowing nix injection
    for system in systems:
        if system not in RUNNERS:
            raise ValueError(f"unknown system {system!r}")
    for output in (*per_system_sets, *config_sets):
        if output not in PER_SYSTEM_SETS and output not in CONFIG_SETS:
            raise ValueError(f"unknown output set {output!r}")
    return (
        _SELECT_TEMPLATE.replace("@SYSTEMS@", _nix_list(systems))
        .replace("@PER_SYSTEM@", _nix_list(per_system_sets))
        .replace("@CONFIG@", _nix_list(config_sets))
    )


def evaluate(
    flake: str,
    systems: Sequence[str],
    per_system_sets: Sequence[str],
    config_sets: Sequence[str],
    workers: int = 4,
) -> list[dict[str, Any]]:
    """Run nix-eval-jobs over the rooted output sets and return one object per attr.

    Per attribute eval errors are reported inline as objects carrying an `error`
    field and never abort the run. A non zero exit is a fatal evaluation failure
    of the whole flake and is raised.
    """
    select = _build_select(systems, per_system_sets, config_sets)
    cmd = [
        "nix", "run", "nixpkgs#nix-eval-jobs", "--",
        "--flake", flake,
        "--force-recurse",
        "--workers", str(workers),
        "--select", select,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"nix-eval-jobs failed for {flake!r}\n{proc.stderr.strip()}")
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def to_job(obj: dict[str, Any]) -> Job:
    """Normalise one nix-eval-jobs object into a `Job`.

    The rooted key carries the set (and system, for per system sets) so the
    full attribute path and the buildable installable reconstruct from attrPath.
    """
    path = ".".join(obj.get("attrPath") or [])
    drv = obj.get("drvPath")
    error = obj.get("error")
    set_name = path.split(".")[0] if path else ""

    if set_name in CONFIG_SETS:
        system = obj.get("system") or ""
        installable = f".#{path}.config.system.build.toplevel" if drv else ""
    else:
        segments = path.split(".")
        system = segments[1] if len(segments) > 1 else (obj.get("system") or "")
        installable = f".#{path}" if drv else ""

    return Job(path=path, system=system, installable=installable, error=error)


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
