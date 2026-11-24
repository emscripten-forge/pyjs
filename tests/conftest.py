# pytest configuration of the test suite (pytest runs inside the browser,
# started by tests/main.py).
import pytest


def pytest_configure(config):
    """the markers the tests use"""
    # (async tests need no marker: tests/pytest_async.py takes every
    # `async def test_*`)
    config.addinivalue_line("markers", "leaks: this test keeps JS handles / proxies alive on purpose")
