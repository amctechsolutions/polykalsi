import pytest

from startup_checks import (
    StartupAbort,
    assert_kalshi_key_read_only,
    assert_kalshi_not_demo,
    assert_memory_headroom,
    assert_no_poly_env,
    load_and_validate_pairs,
    scan_for_stray_secrets,
)


def test_assert_no_poly_env_rejects_any_poly_var():
    with pytest.raises(StartupAbort):
        assert_no_poly_env({"POLYMARKET_API_KEY": "x", "PATH": "/bin"})


def test_assert_no_poly_env_passes_clean_env():
    assert_no_poly_env({"PATH": "/bin", "KALSHI_API_KEY_ID": "x"})


def test_assert_kalshi_not_demo_rejects_demo_host():
    with pytest.raises(StartupAbort):
        assert_kalshi_not_demo("wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2")


def test_assert_kalshi_not_demo_passes_prod_host():
    assert_kalshi_not_demo("wss://external-api-ws.kalshi.com/trade-api/ws/v2")


def test_assert_kalshi_key_read_only_rejects_write_scope():
    with pytest.raises(StartupAbort):
        assert_kalshi_key_read_only(["read", "write::trade"])


def test_assert_kalshi_key_read_only_rejects_bare_write():
    with pytest.raises(StartupAbort):
        assert_kalshi_key_read_only(["write"])


def test_assert_kalshi_key_read_only_rejects_empty_scopes():
    with pytest.raises(StartupAbort):
        assert_kalshi_key_read_only([])


def test_assert_kalshi_key_read_only_passes_read_only():
    assert_kalshi_key_read_only(["read", "read::portfolio_balance"])


def test_scan_for_stray_secrets_flags_pem_outside_declared_path(tmp_path):
    declared = tmp_path / "kalshi_key.pem"
    declared.write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n-----END RSA PRIVATE KEY-----\n")
    stray = tmp_path / "notes.txt"
    stray.write_text("-----BEGIN PRIVATE KEY-----\nleaked\n-----END PRIVATE KEY-----\n")
    with pytest.raises(StartupAbort):
        scan_for_stray_secrets(tmp_path, declared_kalshi_key_path=declared)


def test_scan_for_stray_secrets_allows_declared_path(tmp_path):
    declared = tmp_path / "kalshi_key.pem"
    declared.write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n-----END RSA PRIVATE KEY-----\n")
    scan_for_stray_secrets(tmp_path, declared_kalshi_key_path=declared)  # must not raise


def test_scan_for_stray_secrets_flags_wallet_pattern(tmp_path):
    (tmp_path / "config.txt").write_text("addr = 0x1234567890abcdef1234567890abcdef12345678")
    with pytest.raises(StartupAbort):
        scan_for_stray_secrets(tmp_path, declared_kalshi_key_path=None)


def test_scan_for_stray_secrets_allows_polymarket_condition_id(tmp_path):
    """Regression guard for the v3 pre-flight dry-run bug (2026-08-30): a
    real pairs.yaml legitimately contains 0x-prefixed 64-char condition IDs
    (keccak256 hashes), which must NOT be flagged as a wallet address (40
    hex chars) just because they happen to contain 40+ consecutive hex
    digits. Without the \\b boundary this raised on every real pairs.yaml."""
    (tmp_path / "pairs.yaml").write_text(
        "pairs:\n  - polymarket_condition_id: "
        "\"0xa3b36b2d6104d34af4e6c6215fc818e43352e78a748fbfb0b85e3a35f71dec9a\"\n"
    )
    scan_for_stray_secrets(tmp_path, declared_kalshi_key_path=None)  # must not raise


def test_load_and_validate_pairs_rejects_missing_file(tmp_path):
    with pytest.raises(StartupAbort):
        load_and_validate_pairs(tmp_path / "does_not_exist.yaml")


def test_load_and_validate_pairs_rejects_empty_file(tmp_path):
    p = tmp_path / "pairs.yaml"
    p.write_text("")
    with pytest.raises(StartupAbort):
        load_and_validate_pairs(p)


def test_load_and_validate_pairs_rejects_unparseable(tmp_path):
    p = tmp_path / "pairs.yaml"
    p.write_text("pairs: [this is not: valid: yaml: at: all")
    with pytest.raises(StartupAbort):
        load_and_validate_pairs(p)


def test_load_and_validate_pairs_accepts_valid(tmp_path):
    p = tmp_path / "pairs.yaml"
    p.write_text("pairs:\n  - pair_id: p1\n    enabled: true\n")
    data = load_and_validate_pairs(p)
    assert data["pairs"][0]["pair_id"] == "p1"


def test_assert_memory_headroom_rejects_low_available(tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 2000000 kB\nMemFree: 100000 kB\nMemAvailable: 200000 kB\n")
    with pytest.raises(StartupAbort):
        assert_memory_headroom(min_mb=512, meminfo_path=str(meminfo))


def test_assert_memory_headroom_passes_high_available(tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 2000000 kB\nMemFree: 100000 kB\nMemAvailable: 1200000 kB\n")
    mb = assert_memory_headroom(min_mb=512, meminfo_path=str(meminfo))
    assert mb > 512
