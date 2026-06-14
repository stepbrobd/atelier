import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from urllib.parse import quote

from atelier import nix
from atelier.rules import excluded, included, matches, prunable_excludes
from atelier.types import (
    CONFIG_SETS,
    DEFAULT_RUNNER,
    LEAF_SETS,
    MATRIX_CHUNK,
    PER_SYSTEM_SETS,
    RUNNERS,
    Cell,
    Chunk,
    Job,
    Rules,
    Skipped,
)


def _warn(message: str) -> None:
    print(f"::warning::{message}", file=sys.stderr)


def _effective_systems(rules: Rules, enabled: Sequence[str]) -> list[str]:
    """Rule systems kept by the dispatch toggles and known to have a runner."""
    allowed = set(enabled) if enabled else None
    out: list[str] = []
    for system in rules.systems:
        if system not in RUNNERS:
            _warn(f"No runner mapping for system {system}, skipping")
            continue
        if allowed is None or system in allowed:
            out.append(system)
    return out


def _output_sets(rules: Rules) -> tuple[list[str], list[str], list[str]]:
    """Split the include globs' leading segments into per system, config, and leaf sets."""
    leading = sorted({pattern.split(".")[0] for pattern in rules.include})
    per_system = [s for s in leading if s in PER_SYSTEM_SETS]
    configs = [s for s in leading if s in CONFIG_SETS]
    leaves = [s for s in leading if s in LEAF_SETS]
    for output in leading:
        if (
            output not in PER_SYSTEM_SETS
            and output not in CONFIG_SETS
            and output not in LEAF_SETS
        ):
            _warn(f"Unknown output set {output} in include, skipping")
    return per_system, configs, leaves


def _selected(
    jobs: Sequence[Job], rules: Rules, effective: Sequence[str], only: str | None
) -> list[Job]:
    """Keep jobs on an effective system, included, not excluded, and unique."""
    allowed = set(effective)
    seen: set[tuple[str, str]] = set()
    out: list[Job] = []
    for job in jobs:
        # a config that fails to evaluate carries no system, keep it so it
        # still surfaces as a failure or skip rather than vanishing
        if job.system and job.system not in allowed:
            continue
        if excluded(job.path, rules) or not included(job.path, rules):
            continue
        if only is not None and not matches(only, job.path):
            continue
        key = (job.system, job.path)
        if key in seen:
            continue
        seen.add(key)
        out.append(job)
    return out


def _log_name(label: str) -> str:
    """
    An artifact safe upload name for build cell's log.

    A flake attribute can hold any character: quoted names carry slashes, dots, or
    unicode (e.g. ``checks.<sys>."a/b.c"`` or a freeform ``out.<sys>.a."b.c"``), and
    nested sets like ``legacyPackages`` go arbitrarily deep.

    GitHub artifact name forbids ``/ " : < > | * ? \\`` and newlines.
    """
    return f"log-{quote(label, safe='')}"


def _cell(job: Job) -> Cell:
    return Cell(
        system=job.system,
        runner=RUNNERS.get(job.system, DEFAULT_RUNNER),
        label=job.path,
        installable=job.installable,
        error=nix.clean_error(job.error) if job.error else "",
        log=_log_name(job.path),
    )


def _skip(job: Job) -> Skipped:
    return Skipped(system=job.system, label=job.path, reason=nix.clean_error(job.error or ""))


def _cached_skip(job: Job) -> Skipped:
    return Skipped(
        system=job.system, label=job.path, reason="Already in the binary cache"
    )


def _chunks(cells: Sequence[Cell]) -> list[Chunk]:
    """Slice cells into <=256 groups, one reusable build call each."""
    groups = [cells[i : i + MATRIX_CHUNK] for i in range(0, len(cells), MATRIX_CHUNK)]
    return [
        Chunk(
            name="Build" if len(groups) == 1 else f"Build {index + 1}",
            cells=json.dumps({"include": [asdict(cell) for cell in group]}),
        )
        for index, group in enumerate(groups)
    ]


def discover(
    rules: Rules,
    enabled_systems: Sequence[str],
    only: str | None,
    workers: int,
    flake: str = ".",
) -> tuple[list[Chunk], list[Skipped]]:
    """Evaluate the flake and split discovered attrs into build chunks and skips.

    Successful and genuinely failing attrs become build cells (a failing cell
    reports the eval error). Attrs whose error denotes an expected unbuildable
    state become skipped checks. An attr already in a queried binary cache is
    skipped too, so no runner builds or re-pushes it. Manual excludes are dropped
    before either.
    """
    effective = _effective_systems(rules, enabled_systems)
    per_system, configs, leaves = _output_sets(rules)
    if not effective or (not per_system and not configs and not leaves):
        return [], []

    objects = nix.evaluate(
        f"{flake}#",
        effective,
        per_system,
        configs,
        leaves,
        workers,
        prunable_excludes(rules),
        rules.substituters,
    )
    jobs = [nix.to_job(obj) for obj in objects]
    selected = _selected(jobs, rules, effective, only)

    failed = [job for job in selected if job.error is not None]
    # a cached attr evaluated fine; split it off the buildable ones so its outputs
    # are not rebuilt and re-pushed when a runner could only substitute them
    buildable = [job for job in selected if job.error is None and not job.cached]
    cached = [job for job in selected if job.error is None and job.cached]
    skipped = [job for job in failed if nix.is_skippable(job.error or "")]
    genuine = [job for job in failed if not nix.is_skippable(job.error or "")]

    # surface manual excludes as skipped checks, so the rule file's exclusions
    # are visible rather than silently dropped (one entry per exclude rule)
    excluded_skips = [
        Skipped(system="", label=pattern, reason="Excluded by rule")
        for pattern in rules.exclude
    ]

    cells = [_cell(job) for job in (*buildable, *genuine)]
    return _chunks(cells), [
        *(_skip(job) for job in skipped),
        *(_cached_skip(job) for job in cached),
        *excluded_skips,
    ]
