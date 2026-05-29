import json

from atelier.discover import (
    _cell,
    _chunks,
    _effective_systems,
    _output_sets,
    _selected,
)
from atelier.types import Cell, Job, Rules

_ALL = Rules(
    systems=("x86_64-linux", "aarch64-linux", "aarch64-darwin"), include=(), exclude=()
)


def test_no_toggle_keeps_all_known() -> None:
    assert _effective_systems(_ALL, []) == [
        "x86_64-linux",
        "aarch64-linux",
        "aarch64-darwin",
    ]


def test_toggle_intersects() -> None:
    assert _effective_systems(_ALL, ["aarch64-darwin"]) == ["aarch64-darwin"]


def test_unknown_system_dropped() -> None:
    rules = Rules(systems=("x86_64-linux", "riscv64-linux"), include=(), exclude=())
    assert _effective_systems(rules, []) == ["x86_64-linux"]


def test_output_sets_split() -> None:
    rules = Rules(
        systems=(),
        include=("legacyPackages.*.*", "nixosConfigurations.*", "devShells.*.default"),
        exclude=(),
    )
    per_system, configs = _output_sets(rules)
    assert per_system == ["devShells", "legacyPackages"]
    assert configs == ["nixosConfigurations"]


def test_selected_filters_excludes_systems_and_dedups() -> None:
    rules = Rules(
        systems=(),
        include=("legacyPackages.*.*",),
        exclude=("legacyPackages.*.spotify",),
    )
    jobs = [
        Job("legacyPackages.x86_64-linux.caddy", "x86_64-linux", ".#a", None),
        Job("legacyPackages.x86_64-linux.spotify", "x86_64-linux", ".#b", None),
        Job("legacyPackages.x86_64-linux.caddy", "x86_64-linux", ".#a", None),
        Job("legacyPackages.aarch64-linux.caddy", "aarch64-linux", ".#c", None),
        Job("devShells.x86_64-linux.default", "x86_64-linux", ".#d", None),
    ]
    kept = _selected(jobs, rules, ["x86_64-linux"], None)
    assert [job.path for job in kept] == ["legacyPackages.x86_64-linux.caddy"]


def test_config_eval_failure_without_system_is_kept() -> None:
    rules = Rules(systems=(), include=("nixosConfigurations.*",), exclude=())
    jobs = [Job("nixosConfigurations.baldy", "", "", "error: is marked as broken")]
    kept = _selected(jobs, rules, ["x86_64-linux"], None)
    assert [job.path for job in kept] == ["nixosConfigurations.baldy"]


def test_cell_uses_default_runner_when_system_unknown() -> None:
    cell = _cell(Job("nixosConfigurations.baldy", "", "", "boom"))
    assert cell.runner == "ubuntu-latest"
    assert cell.installable == ""
    assert cell.error


def _cells(count: int) -> list[Cell]:
    return [
        Cell("x86_64-linux", "ubuntu-latest", f"p{i}", f".#p{i}", "")
        for i in range(count)
    ]


def test_single_chunk_named_build() -> None:
    chunks = _chunks(_cells(5))
    assert len(chunks) == 1
    assert chunks[0].name == "build"
    assert len(json.loads(chunks[0].cells)["include"]) == 5


def test_chunks_split_at_256() -> None:
    chunks = _chunks(_cells(257))
    assert [chunk.name for chunk in chunks] == ["build 1", "build 2"]
    assert len(json.loads(chunks[0].cells)["include"]) == 256
    assert len(json.loads(chunks[1].cells)["include"]) == 1
