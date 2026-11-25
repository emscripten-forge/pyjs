# pytest configuration of the test suite (pytest runs inside the browser,
# started by tests/main.py).
import pytest


def pytest_configure(config):
    """Register the custom markers, so that pytest knows them (an unknown
    `@pytest.mark.<name>` only gives a warning, a typo would go unnoticed).

    - `leaks`: the test keeps JS handles / PyProxies alive on purpose. Meant
      for a per-test leak check (count the live handles / proxies before and
      after each test and complain if a test left some behind); the check
      is not built yet, nothing uses the marker so far.

    (Async tests need no marker: tests/pytest_async.py takes every
    `async def test_*`.)"""
    config.addinivalue_line("markers", "leaks: this test keeps JS handles / proxies alive on purpose")
