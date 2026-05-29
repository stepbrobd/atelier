import fnmatch
import tomllib
from pathlib import Path

from atelier.types import DEFAULT_INCLUDE, DEFAULT_SYSTEMS, Rules


def load(path: Path) -> Rules:
    """Read a rule file, falling back to defaults for any omitted key."""
    data = tomllib.loads(path.read_text())
    return Rules(
        systems=tuple(data.get("systems", DEFAULT_SYSTEMS)),
        include=tuple(data.get("include", DEFAULT_INCLUDE)),
        exclude=tuple(data.get("exclude", ())),
    )


def matches(pattern: str, path: str) -> bool:
    """Match a dotted glob against a flake attribute path.

    Matching is segment wise with an equal segment count, so a bare ``*`` spans
    exactly one segment and a nested scope needs its own segment. Thus
    ``legacyPackages.*.*`` matches ``legacyPackages.x86_64-linux.caddy`` but not
    ``legacyPackages.x86_64-linux.ocamlPackages.dune``, which needs the explicit
    ``legacyPackages.*.ocamlPackages.*``.
    """
    pat = pattern.split(".")
    seg = path.split(".")
    if len(pat) != len(seg):
        return False
    return all(fnmatch.fnmatchcase(s, p) for p, s in zip(pat, seg, strict=True))


def included(path: str, rules: Rules) -> bool:
    """True when `path` matches any include glob."""
    return any(matches(pattern, path) for pattern in rules.include)


def excluded(path: str, rules: Rules) -> bool:
    """True when `path` matches any exclude glob."""
    return any(matches(pattern, path) for pattern in rules.exclude)
