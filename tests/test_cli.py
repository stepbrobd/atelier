from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from atelier.cli import _FALLBACK_WORKERS, _default_workers, _workers_for_memory, cli
from atelier.rules import defaults

GIB = 1024**3


def test_one_worker_per_four_gib_minus_headroom() -> None:
    # 16 GiB -> 16/4 - 1 = 3
    assert _workers_for_memory(16 * GIB) == 3


def test_rounds_partial_gib_down() -> None:
    # a "16 GB" runner reports ~15.6 GiB; flooring it gives the safe CI value of 2
    assert _workers_for_memory(15 * GIB + GIB // 2) == 2


def test_floors_at_one_on_small_hosts() -> None:
    # 4 GiB -> 4/4 - 1 = 0, clamped up so eval still runs (without parallelism)
    assert _workers_for_memory(4 * GIB) == 1
    assert _workers_for_memory(2 * GIB) == 1


def test_scales_with_large_memory() -> None:
    # 64 GiB -> 64/4 - 1 = 15
    assert _workers_for_memory(64 * GIB) == 15


def test_default_reads_detected_memory() -> None:
    pages, page_size = 8 * GIB // 4096, 4096
    sysconf = {"SC_PHYS_PAGES": pages, "SC_PAGE_SIZE": page_size}
    with mock.patch("os.sysconf", side_effect=sysconf.__getitem__):
        assert _default_workers() == 1  # 8 GiB -> 8/4 - 1 = 1


def test_default_falls_back_when_memory_undetectable() -> None:
    # os.sysconf raises on platforms/keys it does not support (e.g. Windows)
    with mock.patch("os.sysconf", side_effect=ValueError):
        assert _default_workers() == _FALLBACK_WORKERS


def test_discover_uses_defaults_when_rule_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a repo with no atelier.toml must still evaluate, with the built-in defaults,
    # rather than erroring on the missing file
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    with mock.patch("atelier.cli._discover.discover", return_value=([], [])) as disc:
        result = runner.invoke(cli, ["discover"], catch_exceptions=False)
    assert result.exit_code == 0
    assert disc.call_args.args[0] == defaults()
    assert "No rule file at atelier.toml" in result.stderr


def test_discover_uses_defaults_when_explicit_rules_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the reusable workflow always passes --rules atelier.toml explicitly (it
    # defaults inputs.rules to that literal), so the fallback must key off the
    # file being absent, not off whether --rules was given on the command line
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    with mock.patch("atelier.cli._discover.discover", return_value=([], [])) as disc:
        result = runner.invoke(
            cli, ["discover", "--rules", "atelier.toml"], catch_exceptions=False
        )
    assert result.exit_code == 0
    assert disc.call_args.args[0] == defaults()
    assert "No rule file at atelier.toml" in result.stderr


def test_discover_loads_an_existing_rule_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "atelier.toml").write_text('systems = ["aarch64-darwin"]\n')
    runner = CliRunner()
    with mock.patch("atelier.cli._discover.discover", return_value=([], [])) as disc:
        result = runner.invoke(cli, ["discover"], catch_exceptions=False)
    assert result.exit_code == 0
    assert disc.call_args.args[0].systems == ("aarch64-darwin",)
    assert "No rule file" not in result.stderr
