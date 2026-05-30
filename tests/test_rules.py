from pathlib import Path

from atelier.rules import excluded, included, load, matches, prunable_excludes
from atelier.types import Rules


def test_single_level_star_stops_at_dot() -> None:
    assert matches("legacyPackages.*.*", "legacyPackages.x86_64-linux.caddy")
    assert not matches(
        "legacyPackages.*.*", "legacyPackages.x86_64-linux.ocamlPackages.dune"
    )


def test_nested_scope_needs_its_own_segment() -> None:
    assert matches(
        "legacyPackages.*.ocamlPackages.*",
        "legacyPackages.x86_64-linux.ocamlPackages.dune",
    )
    assert not matches(
        "legacyPackages.*.ocamlPackages.*", "legacyPackages.x86_64-linux.caddy"
    )


def test_within_segment_glob() -> None:
    assert matches(
        "legacyPackages.*.ripe-atlas-*",
        "legacyPackages.x86_64-linux.ripe-atlas-software-probe",
    )


def test_exact_and_segment_count() -> None:
    assert matches("nixosConfigurations.baldy", "nixosConfigurations.baldy")
    assert not matches("nixosConfigurations.baldy", "nixosConfigurations.butte")
    assert not matches("a.b", "a.b.c")


_RULES = Rules(
    systems=("x86_64-linux",),
    include=("legacyPackages.*.*", "legacyPackages.*.ocamlPackages.*"),
    exclude=("legacyPackages.*.spotify",),
)


def test_included() -> None:
    assert included("legacyPackages.x86_64-linux.caddy", _RULES)
    assert included("legacyPackages.x86_64-linux.ocamlPackages.dune", _RULES)
    assert not included("devShells.x86_64-linux.default", _RULES)


def test_excluded() -> None:
    assert excluded("legacyPackages.x86_64-linux.spotify", _RULES)
    assert not excluded("legacyPackages.x86_64-linux.caddy", _RULES)


_NIXOS_CACHE = "https://cache.nixos.org"


def test_load_substituters_default_to_nixos_cache(tmp_path: Path) -> None:
    # an omitted key still queries the official cache, so a path already on
    # cache.nixos.org is skipped without any rule file configuration
    rules = load(_write(tmp_path, ""))
    assert rules.substituters == frozenset({_NIXOS_CACHE})


def test_load_substituters_union_keeps_nixos_cache(tmp_path: Path) -> None:
    rules = load(_write(tmp_path, 'substituters = ["https://cache.ysun.co"]\n'))
    assert rules.substituters == frozenset({"https://cache.ysun.co", _NIXOS_CACHE})


def test_load_substituters_dedups_explicit_nixos_cache(tmp_path: Path) -> None:
    rules = load(
        _write(
            tmp_path,
            'substituters = ["https://cache.nixos.org", "https://cache.ysun.co"]\n',
        )
    )
    assert rules.substituters == frozenset({_NIXOS_CACHE, "https://cache.ysun.co"})


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "atelier.toml"
    path.write_text(body)
    return path


def test_prunable_excludes_groups_by_set_and_system() -> None:
    rules = Rules(
        systems=(),
        include=(),
        exclude=(
            "legacyPackages.*.verus",
            "legacyPackages.*.spotify",
            "legacyPackages.aarch64-darwin.bird3",  # specific system, prunable
            "legacyPackages.*.ripe-atlas-*",  # glob leaf, stays a post filter
            "legacyPackages.*.ocamlPackages.*",  # nested, stays a post filter
            "nixosConfigurations.host",  # not a per system set
        ),
    )
    assert prunable_excludes(rules) == {
        "legacyPackages": {"*": ["spotify", "verus"], "aarch64-darwin": ["bird3"]}
    }
