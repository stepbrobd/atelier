from dataclasses import dataclass
from typing import Final

# nix system to github hosted runner label
RUNNERS: Final[dict[str, str]] = {
    "x86_64-linux": "ubuntu-latest",
    "aarch64-linux": "ubuntu-24.04-arm",  # no ubuntu-latest-arm label exists
    "aarch64-darwin": "macos-latest",
}

# runner for a cell whose system is unknown, e.g. a config that failed to
# evaluate so nix-eval-jobs produced no derivation and thus no system
# such a cell only prints the eval error, so any runner works
DEFAULT_RUNNER: Final[str] = "ubuntu-latest"

# applied when the rule file omits the corresponding key
DEFAULT_SYSTEMS: Final[tuple[str, ...]] = ("x86_64-linux",)
DEFAULT_INCLUDE: Final[tuple[str, ...]] = ("packages.*.*", "devShells.*.default")

# always queried for cache status, even when the rule file names no substituter,
# so a path already on the official cache is skipped without configuration
NIXOS_CACHE: Final[str] = "https://cache.nixos.org"

# output sets enumerated per system, addressed as <set>.<system>.<rest>
PER_SYSTEM_SETS: Final[frozenset[str]] = frozenset(
    {"packages", "legacyPackages", "checks", "devShells"}
)
# output sets addressed by host whose buildable derivation is a sub attribute
CONFIG_SETS: Final[frozenset[str]] = frozenset(
    {"nixosConfigurations", "darwinConfigurations"}
)

# github caps a single matrix at 256 jobs, the matrix is chunked to stay under it
MATRIX_CHUNK: Final[int] = 256

# an eval error matching this denotes an expected unbuildable attribute
# (wrong platform, broken, unfree, insecure) which becomes a skipped check
# rather than a failure
# the phrases are the canonical nixpkgs check-meta rejections, not bare words,
# so an ordinary error that merely contains "broken" or "unsupported" is not
# misread as a skip and silently passed
SKIP_PATTERN: Final[str] = (
    r"refusing to evaluate"
    r"|is marked as broken"
    r"|is marked as insecure"
    r"|has an unfree license"
    r"|not available on the requested hostplatform"
    r"|is not supported on system"
    r"|known ?vulnerabilit"
    r"|may not be built"
)


@dataclass(frozen=True)
class Rules:
    """A parsed atelier rule file."""

    systems: tuple[str, ...]
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    # binary caches checked for an attribute's outputs before building it; a set
    # so duplicates collapse. `load` always folds in the official cache. An
    # attribute already in any of these is skipped rather than built and pushed.
    substituters: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Job:
    """
    One attribute surfaced by nix-eval-jobs.

    `path` is the full flake attribute, e.g. ``legacyPackages.x86_64-linux.caddy``.
    `installable` is the buildable flake reference, empty when evaluation failed.
    `error` carries the eval error text, ``None`` on success.
    `cached` is true when every output is already in a queried binary cache, so a
    build runner would only substitute it; such an attribute is skipped.
    """

    path: str
    system: str
    installable: str
    error: str | None
    cached: bool = False


@dataclass(frozen=True)
class Cell:
    """
    A single build matrix cell, rendered as its own check run.
    """

    system: str
    runner: str
    label: str
    installable: str
    error: str


@dataclass(frozen=True)
class Skipped:
    """
    An attribute reported as a skipped check instead of being built.
    """

    system: str
    label: str
    reason: str


@dataclass(frozen=True)
class Chunk:
    """
    A slice of at most ``MATRIX_CHUNK`` cells for one reusable build call.

    `cells` is the json encoded ``{"include": [...]}`` consumed verbatim as the
    reusable workflow matrix.
    """

    name: str
    cells: str
