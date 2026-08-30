"""Static execution-code gate: fails the build if any order-placement path
or trading-capable HTTP verb appears anywhere in the shipped source tree.
Only application source is scanned (this tests/ directory and the arb_env
venv are excluded) so this file itself is free to name the patterns."""
from pathlib import Path

import pytest

ARB_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_PATTERNS = [
    b"place_order",
    b"placeOrder",
    b"CreateOrder",
    b"create_order",
    b"cancel_order",
    b"/orders",
    b"clob-orders",
    b"py_clob_client",  # Polymarket's official order-placing SDK
    b"eth_sendTransaction",
    b"sign_and_send",
    b".post(",
    b"requests.post",
    b"http.post",
    b"import ccxt",
    b"import alpaca",
    b"web3.eth.account",
]

EXCLUDED_DIR_NAMES = {"arb_env", "tests", ".git", "__pycache__"}


def _source_files():
    for path in ARB_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIR_NAMES for part in path.relative_to(ARB_ROOT).parts):
            continue
        if path.suffix in (".py", ".js"):
            yield path


@pytest.mark.parametrize("pattern", FORBIDDEN_PATTERNS)
def test_no_forbidden_pattern_in_source_tree(pattern):
    hits = []
    for path in _source_files():
        content = path.read_bytes()
        if pattern in content:
            hits.append(str(path))
    assert not hits, f"forbidden pattern {pattern!r} found in: {hits}"


def test_source_tree_is_actually_scanned():
    """Guard against the scan silently matching zero files (e.g. a path bug)."""
    assert len(list(_source_files())) >= 3
