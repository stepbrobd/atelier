from atelier.rules import excluded, included, matches
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
