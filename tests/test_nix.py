from atelier.nix import _build_select, clean_error, is_skippable, to_job


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


def test_build_select_rejects_unallowlisted_values() -> None:
    import pytest

    with pytest.raises(ValueError, match="unknown system"):
        _build_select(['x"; evil; "y'], ["legacyPackages"], [])
    with pytest.raises(ValueError, match="unknown output set"):
        _build_select(["x86_64-linux"], ["evil"], [])


def test_select_injects_allowlisted_lists() -> None:
    expr = _build_select(["x86_64-linux"], ["legacyPackages"], ["nixosConfigurations"])
    assert 'systems = [ "x86_64-linux" ]' in expr
    assert 'perSystemSets = [ "legacyPackages" ]' in expr
    assert 'configSets = [ "nixosConfigurations" ]' in expr
