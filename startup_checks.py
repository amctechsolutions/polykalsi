"""Fail-closed startup assertions for arb-obs.

Every function here raises StartupAbort on violation. main() in data_logger.py
must run ALL of these before opening a single socket, and let StartupAbort
propagate to a non-zero exit — never caught-and-continued.
"""
import re
from pathlib import Path

import yaml


class StartupAbort(RuntimeError):
    pass


def assert_no_poly_env(environ):
    hits = [k for k in environ if k.startswith("POLY")]
    if hits:
        raise StartupAbort(f"POLY* env var(s) present, Polymarket must be zero-credential: {hits}")


def assert_kalshi_not_demo(host):
    if "demo" in host.lower():
        raise StartupAbort(f"Kalshi host resolves to demo environment: {host}")


def assert_kalshi_key_read_only(scopes):
    """scopes: list[str] as returned by GET /trade-api/v2/api_keys for the
    configured key id. Any write scope fails closed."""
    write_scopes = [s for s in scopes if s == "write" or s.startswith("write::")]
    if write_scopes:
        raise StartupAbort(f"Kalshi key is not read-only, write scope(s) present: {write_scopes}")
    if not scopes:
        raise StartupAbort("Kalshi key returned no scopes; cannot verify read-only")


_PEM_PATTERN = re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_WALLET_PATTERNS = [
    re.compile(rb"0x[a-fA-F0-9]{40}"),
    re.compile(rb"\bxprv[a-zA-Z0-9]{50,}\b"),
    re.compile(rb"\bmnemonic\b", re.IGNORECASE),
]


def scan_for_stray_secrets(root, declared_kalshi_key_path):
    """Content-scans every file under `root` for PEM private-key blocks or
    wallet-like patterns, EXCLUDING the one declared Kalshi key path. This is
    a content scan, not an any-file check, per spec: a file that happens to
    be named "key.pem" but contains no such pattern is not flagged, and a
    file with an innocuous name that DOES contain a PEM block is."""
    root = Path(root)
    declared = declared_kalshi_key_path.resolve() if declared_kalshi_key_path else None
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if declared is not None and path.resolve() == declared:
            continue
        if "arb_env" in path.parts:
            continue  # venv site-packages are not operator content
        try:
            content = path.read_bytes()
        except OSError:
            continue
        if _PEM_PATTERN.search(content):
            raise StartupAbort(f"PEM private-key block found outside declared Kalshi key path: {path}")
        for pattern in _WALLET_PATTERNS:
            if pattern.search(content):
                raise StartupAbort(f"wallet-like pattern found in {path}: {pattern.pattern!r}")


def load_and_validate_pairs(path):
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        raise StartupAbort(f"pairs.yaml missing or empty: {path}")
    with open(path) as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise StartupAbort(f"pairs.yaml unparseable: {exc}") from exc
    if not data or not data.get("pairs"):
        raise StartupAbort(f"pairs.yaml parsed but contains no pairs: {path}")
    return data


def assert_memory_headroom(min_mb=512, meminfo_path="/proc/meminfo"):
    """Gates on MemAvailable, not raw MemFree — see US-ARB-OBS-01 Task 0
    finding: MemFree understates headroom because Linux uses idle RAM for
    reclaimable page cache (buff/cache)."""
    with open(meminfo_path) as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                kb = int(line.split()[1])
                mb = kb / 1024
                if mb < min_mb:
                    raise StartupAbort(f"MemAvailable {mb:.0f}MB < required {min_mb}MB")
                return mb
    raise StartupAbort(f"MemAvailable not found in {meminfo_path}")
