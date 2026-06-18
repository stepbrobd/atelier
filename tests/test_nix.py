from atelier.nix import _build_select, _eval_command, clean_error, is_skippable, to_job
from atelier.types import MAX_RECURSE_DEPTH


def test_per_system_leaf() -> None:
    job = to_job(
        {
            "attrPath": ["legacyPackages.x86_64-linux", "caddy"],
            "drvPath": "/nix/store/x.drv",
            "system": "x86_64-linux",
        }
    )
    assert job.path == "legacyPackages.x86_64-linux.caddy"
    assert job.system == "x86_64-linux"
    assert job.installable == ".#legacyPackages.x86_64-linux.caddy"
    assert job.error is None


def test_nested_scope_leaf() -> None:
    job = to_job(
        {
            "attrPath": ["legacyPackages.x86_64-linux", "ocamlPackages", "dune"],
            "drvPath": "/nix/store/y.drv",
        }
    )
    assert job.path == "legacyPackages.x86_64-linux.ocamlPackages.dune"
    assert job.system == "x86_64-linux"
    assert job.installable == ".#legacyPackages.x86_64-linux.ocamlPackages.dune"


def test_error_without_system_field_derives_from_path() -> None:
    job = to_job(
        {
            "attrPath": ["legacyPackages.aarch64-darwin", "bird3"],
            "error": "boom",
            "fatal": False,
        }
    )
    assert job.system == "aarch64-darwin"
    assert job.installable == ""
    assert job.error == "boom"


def test_formatter_leaf_derives_system_and_installable() -> None:
    # a leaf set roots the derivation at "<set>.<system>", so attrPath has a
    # single element and the system comes from the path's second segment; the
    # "system" field is omitted so the test proves the path derivation
    job = to_job(
        {
            "attrPath": ["formatter.x86_64-linux"],
            "drvPath": "/nix/store/f.drv",
        }
    )
    assert job.path == "formatter.x86_64-linux"
    assert job.system == "x86_64-linux"
    assert job.installable == ".#formatter.x86_64-linux"


def test_config_uses_toplevel_installable() -> None:
    job = to_job(
        {
            "attrPath": ["nixosConfigurations", "baldy"],
            "drvPath": "/nix/store/z.drv",
            "system": "x86_64-linux",
        }
    )
    assert job.path == "nixosConfigurations.baldy"
    assert job.system == "x86_64-linux"
    assert job.installable == ".#nixosConfigurations.baldy.config.system.build.toplevel"


def test_to_job_marks_cached_when_substitutable() -> None:
    job = to_job(
        {
            "attrPath": ["packages.x86_64-linux", "hello"],
            "drvPath": "/nix/store/x.drv",
            "system": "x86_64-linux",
            "cacheStatus": "cached",
        }
    )
    assert job.cached is True


def test_to_job_not_cached_when_not_built() -> None:
    job = to_job(
        {
            "attrPath": ["packages.x86_64-linux", "hello"],
            "drvPath": "/nix/store/x.drv",
            "cacheStatus": "notBuilt",
        }
    )
    assert job.cached is False


def test_to_job_local_is_not_cached() -> None:
    # "local" is present only in this runner's store, not in a shared cache, so a
    # build on a different runner could not substitute it; it must still build
    job = to_job(
        {
            "attrPath": ["packages.x86_64-linux", "hello"],
            "drvPath": "/nix/store/x.drv",
            "cacheStatus": "local",
        }
    )
    assert job.cached is False


def test_to_job_not_cached_when_status_absent() -> None:
    job = to_job(
        {"attrPath": ["packages.x86_64-linux", "hello"], "drvPath": "/nix/store/x.drv"}
    )
    assert job.cached is False


def test_eval_command_requests_cache_status() -> None:
    assert "--check-cache-status" in _eval_command("flake#", "SELECT", 2, frozenset())


def test_eval_command_passes_sorted_substituters() -> None:
    cmd = _eval_command(
        "flake#",
        "SELECT",
        2,
        frozenset({"https://cache.ysun.co", "https://cache.nixos.org"}),
    )
    value = cmd[cmd.index("extra-substituters") + 1]
    assert value == "https://cache.nixos.org https://cache.ysun.co"
    # an untrusted cache's signature is irrelevant to a mere existence check, so
    # the check must not require a trusted signature or it would miss the path
    assert cmd[cmd.index("require-sigs") + 1] == "false"


def test_eval_command_omits_substituters_when_none() -> None:
    assert "extra-substituters" not in _eval_command("flake#", "SELECT", 2, frozenset())


def test_unsupported_platform_is_skippable() -> None:
    assert is_skippable("error: not available on the requested hostPlatform")


def test_broken_is_skippable() -> None:
    assert is_skippable("Package foo is marked as broken")


def test_syntax_error_is_not_skippable() -> None:
    assert not is_skippable("error: syntax error, unexpected end of file")


def test_unsupported_argument_is_not_skippable() -> None:
    assert not is_skippable("error: function call has an unsupported argument")


def test_missing_broken_attr_is_not_skippable() -> None:
    assert not is_skippable("error: attribute 'broken' missing")


def test_clean_error_keeps_innermost_message() -> None:
    raw = "error:\n  in the assert\n  error: Refusing to evaluate package 'x'"
    assert clean_error(raw) == "error: Refusing to evaluate package 'x'"


def test_clean_error_neutralises_workflow_commands() -> None:
    assert "::" not in clean_error("boom ::stop-commands::abcd")
    # odd-length colon runs must not leave a "::" a single replace would miss
    assert "::" not in clean_error("boom :::warning file=x::spoof")


def test_build_select_rejects_unallowlisted_values() -> None:
    import pytest

    with pytest.raises(ValueError, match="unknown system"):
        _build_select(['x"; evil; "y'], ["legacyPackages"], [])
    with pytest.raises(ValueError, match="unknown output set"):
        _build_select(["x86_64-linux"], ["evil"], [])
    with pytest.raises(ValueError, match="unknown output set"):
        _build_select(["x86_64-linux"], [], [], ["evil"])


def test_build_select_injects_allowlisted_lists() -> None:
    expr = _build_select(
        ["x86_64-linux"], ["legacyPackages"], ["nixosConfigurations"], ["formatter"]
    )
    assert 'systems = [ "x86_64-linux" ]' in expr
    assert 'perSystemSets = [ "legacyPackages" ]' in expr
    assert 'configSets = [ "nixosConfigurations" ]' in expr
    assert 'leafSets = [ "formatter" ]' in expr


def test_build_select_sanitizes_per_system_scopes() -> None:
    # the per system rooting must prune scope plumbing before force-recurse: drop
    # functions and recurseForDerivations=false aliases, drop the named attrset
    # plumbing (lib), and bound recursion to the include depth
    expr = _build_select(["x86_64-linux"], ["legacyPackages"], [], max_depth=4)
    assert "sanitize" in expr
    assert "builtins.isFunction raw" in expr
    assert "recurseForDerivations or true) == false" in expr
    assert '"lib"' in expr
    # maxDepth 4 leaves a recursion budget of one level past the depth-3 children
    assert "maxDepth = 4;" in expr


def test_build_select_clamps_depth_to_cap() -> None:
    # a caller asking for more depth than the hard cap is clamped, so a pathological
    # include can never request an unbounded recursion
    expr = _build_select(
        ["x86_64-linux"], ["legacyPackages"], [], max_depth=MAX_RECURSE_DEPTH + 99
    )
    assert f"maxDepth = {MAX_RECURSE_DEPTH};" in expr


def test_build_select_guards_leaf_derivations() -> None:
    # a non derivation leaf value must throw per attribute, not be recursed
    # into (its children's 3-segment paths could never match "formatter.*")
    expr = _build_select(["x86_64-linux"], [], [], ["formatter"])
    assert 'if (v.type or null) == "derivation" then v' in expr
    assert "is not a derivation" in expr


def test_build_select_prunes_excluded_leaves() -> None:
    expr = _build_select(
        ["x86_64-linux"],
        ["legacyPackages"],
        [],
        exclude_leaves={
            "legacyPackages": {"*": ["spotify", "verus"], "aarch64-darwin": ["bird3"]}
        },
    )
    assert "removeAttrs" in expr
    assert '"*" = [ "spotify" "verus" ];' in expr
    assert '"aarch64-darwin" = [ "bird3" ];' in expr


def test_build_select_escapes_exclude_leaves() -> None:
    # a crafted leaf name must stay inside its nix string, not break out
    expr = _build_select(
        ["x86_64-linux"],
        ["legacyPackages"],
        [],
        exclude_leaves={"legacyPackages": {"*": ['evil"; x']}},
    )
    assert '"evil\\"; x"' in expr


def test_build_select_rejects_unknown_exclude_set() -> None:
    import pytest

    with pytest.raises(ValueError, match="unknown output set"):
        _build_select(
            ["x86_64-linux"],
            ["legacyPackages"],
            [],
            exclude_leaves={"bogus": {"*": ["x"]}},
        )
