import json
import os
from importlib.metadata import version as _pkg_version
from pathlib import Path

import click

from atelier import discover as _discover
from atelier.rules import load

_PROG = "atelier"
_CTX = {"help_option_names": ["-h", "--help"]}

# nix-eval-jobs caps each worker at 4 GiB by default (--max-memory-size), so the
# aggregate eval memory is workers x 4 GiB. Size the default off RAM, not the CPU
# count, since the core count says nothing about that OOM ceiling.
_WORKER_GIB = 4
# used only when the host's RAM is unreadable; matches the workflow's safe default
_FALLBACK_WORKERS = 2


def _workers_for_memory(total_bytes: int) -> int:
    """Workers whose 4 GiB budgets fit in RAM, less one for OS and driver headroom.

    Always returns at least 1, so a small host still evaluates (without
    parallelism) rather than getting a nonsensical zero or negative count.
    """
    gib = total_bytes // 1024**3
    return max(1, gib // _WORKER_GIB - 1)


def _default_workers() -> int:
    """Memory-aware default for ``--workers``; falls back if RAM is undetectable."""
    try:
        total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except AttributeError, ValueError, OSError:
        return _FALLBACK_WORKERS
    return _workers_for_memory(total)


@click.group(name=_PROG, context_settings=_CTX)
@click.version_option(_pkg_version("atelier"), "-v", "--version", prog_name=_PROG)
def cli() -> None:
    """
    Rule driven multi platform Nix flake build discovery.
    """


@cli.command()
@click.option(
    "--rules",
    "rules_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default="atelier.toml",
    envvar="ATELIER_RULES",
    show_default=True,
    help="Rule file path.",
)
@click.option(
    "--flake",
    default=".",
    envvar="ATELIER_FLAKE",
    show_default=True,
    help="Flake directory or reference to evaluate.",
)
@click.option(
    "--systems",
    default="",
    envvar="ATELIER_SYSTEMS",
    help="Comma separated systems to keep (empty means all in the rule file).",
)
@click.option(
    "--attr",
    "only",
    default="",
    envvar="ATELIER_ATTR",
    help="Restrict to attributes matching this glob.",
)
@click.option(
    "--workers",
    type=click.IntRange(1),
    default=_default_workers(),
    show_default=True,
    help="Number of nix-eval-jobs workers (defaults to one per 4 GiB of RAM, "
    "minus one for headroom, since each worker may use up to 4 GiB).",
)
def discover(
    rules_path: Path, flake: str, systems: str, only: str, workers: int
) -> None:
    """
    Evaluate the flake and emit the build matrix and skipped attributes.

    Outputs are written to $GITHUB_OUTPUT when set (as `chunks` and `skipped`),
    otherwise printed to stdout.
    """
    rules = load(rules_path)
    enabled = [part.strip() for part in systems.split(",") if part.strip()]
    chunks, skipped = _discover.discover(rules, enabled, only or None, workers, flake)

    cells = sum(len(json.loads(chunk.cells)["include"]) for chunk in chunks)
    click.echo(
        f"::notice::Discovered {cells} build cells in {len(chunks)} chunk(s), "
        f"{len(skipped)} skipped",
        err=True,
    )

    _emit("chunks", [{"name": c.name, "cells": c.cells} for c in chunks])
    _emit(
        "skipped",
        [{"system": s.system, "label": s.label, "reason": s.reason} for s in skipped],
    )


def _emit(name: str, value: object) -> None:
    """Append a workflow output under Actions, otherwise print to stdout."""
    payload = json.dumps(value)
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={payload}\n")
    else:
        click.echo(f"{name}={payload}")
