"""The stand-ins pyjs installs for standard library modules that cannot work
in a browser (module/pyjs/_mocks.py)."""

import asyncio
import importlib
import sys
import time

import pytest

import pyjs
from helpers import requires_jspi


@pytest.mark.parametrize("name, attribute", [("fcntl", "flock"), ("termios", "tcgetattr")])
def test_real_modules_are_not_hidden(name, attribute):
    """A module the Python build has (as builtin) is the real one, not an
    empty stand-in: `fcntl.flock` exists (it may fail when called, like on
    every platform without file locks)."""
    if name not in sys.builtin_module_names:
        pytest.skip(f"this Python has no {name}")
    module = importlib.import_module(name)
    assert hasattr(module, attribute), f"{name} is a stand-in"


def test_stand_in_says_what_is_missing():
    """A module the browser cannot have (`resource`: process limits) can be
    imported, so that packages importing it at import time work. Using it
    raises an AttributeError (what `hasattr` / `getattr(..., default)` and
    `except AttributeError` expect) that says why."""
    if "resource" in sys.builtin_module_names:
        pytest.skip("this Python has a real resource module")
    import resource

    with pytest.raises(AttributeError, match="not available in the browser"):
        resource.getrlimit
    assert not hasattr(resource, "getrlimit")


def test_sleep_rejects_negative_seconds():
    # (as time.sleep everywhere)
    with pytest.raises(ValueError):
        time.sleep(-1)


def test_sleep_waits_at_least_the_time():
    start = time.monotonic()
    time.sleep(0.02)
    assert time.monotonic() - start >= 0.02


@requires_jspi
async def test_sleep_lets_other_tasks_run():
    """Where the Python stack can be suspended (an asyncio task with JSPI),
    `time.sleep` waits like `asyncio.sleep`: the browser and the other tasks
    go on meanwhile. (Busy waiting would block everything.)"""
    steps = []

    async def other():
        steps.append("other ran")

    task = asyncio.ensure_future(other())
    assert pyjs.can_run_sync()
    time.sleep(0.01)
    # the other task ran DURING the sleep, before this line
    assert steps == ["other ran"]
    await task
