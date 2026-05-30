from unittest import mock

from atelier.cli import _FALLBACK_WORKERS, _default_workers, _workers_for_memory

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
