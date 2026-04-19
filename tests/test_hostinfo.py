"""Unit tests for :mod:`cooldown.collectors.hostinfo`."""
from __future__ import annotations

from cooldown.collectors import hostinfo


def test_collect_returns_stable_dataclass():
    h1 = hostinfo.collect()
    h2 = hostinfo.collect()
    # lru_cache keeps the result identical across calls — the payload
    # never changes at runtime so consumers can treat it as a constant.
    assert h1 is h2


def test_collect_on_current_host_has_plausible_values():
    h = hostinfo.collect()
    # Don't hard-code anything machine-specific; just assert sanity.
    assert isinstance(h.model, str) and h.model
    assert isinstance(h.chip, str) and h.chip
    assert h.perf_cores >= 0
    assert h.eff_cores >= 0
    assert h.perf_cores + h.eff_cores >= 1
    # 4GB minimum for any supported Mac.
    assert h.ram_bytes >= 4 * 1024 ** 3
    # 1GB minimum on the boot volume — anything lower would be /dev/null.
    assert h.disk_total_bytes >= 1024 ** 3
    # macOS version strings look like "14.5" / "15.2" / "26.2".
    assert "." in h.macos_version


def test_topology_string_matches_p_plus_e_pattern():
    h = hostinfo.collect()
    topo = h.topology
    assert topo.endswith("E")
    assert "P+" in topo
    # Parse back and compare to the raw fields.
    p_str, e_str = topo.split("P+")
    assert int(p_str) == h.perf_cores
    assert int(e_str.rstrip("E")) == h.eff_cores
