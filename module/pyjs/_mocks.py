"""Stand-ins for parts of the standard library that cannot work in a browser.

Many packages import modules like `resource` at import time without really
needing them. When the Python build has no such module (there are no process
limits, terminals or child processes in a browser), the import would fail.
A stand-in module of the same name lets such packages import; using it
raises an AttributeError that says why.

Only for modules that are MISSING: a module the build has (`fcntl` and
`termios` are built in) is never hidden behind a stand-in.
"""

import asyncio
import importlib.util
import sys
import time
import types

import pyjs_core

from .core import can_run_sync, run_sync

_js = pyjs_core.global_this()


class _StandIn(types.ModuleType):
    """A module that exists but has nothing: every attribute that is not set
    raises AttributeError (what `hasattr`, `getattr(m, name, default)` and
    `except AttributeError` expect), with a message that says why."""

    def __getattr__(self, attribute):
        # (only called for attributes that do not exist)
        if attribute.startswith("__"):
            raise AttributeError(attribute)
        raise AttributeError(f"{self.__name__}.{attribute} is not available in the browser (pyjs)")


def _stand_in(name, **attributes):
    """install a stand-in for module `name` if the Python build has none"""
    if name in sys.modules or importlib.util.find_spec(name) is not None:
        return
    module = _StandIn(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    sys.modules[name] = module


def _mock_missing_modules():
    for name in ("fcntl", "pexpect", "resource"):
        _stand_in(name)
    # (the constant packages commonly read at import time)
    _stand_in("termios", TCSAFLUSH=2)


def _mock_time_sleep():
    """`time.sleep(seconds)` in the browser.

    Python code runs on the browser's one thread: while it blocks, nothing
    else happens (no drawing, no events, no other asyncio task). So:
      - where the Python stack can be suspended (JSPI, `pyjs.can_run_sync()`:
        e.g. in an asyncio task), it waits like `asyncio.sleep`, and the
        browser and the other tasks go on meanwhile (as in pyodide)
      - elsewhere (a synchronous event handler, no JSPI) it busy-waits: it
        keeps the promise of the name, but blocks the page meanwhile. In
        async code prefer `await asyncio.sleep(...)`.
    """

    def sleep(seconds):
        """Delay execution for a given number of seconds.  The argument may be
        a floating point number for subsecond precision.
        """
        if seconds < 0:
            raise ValueError("sleep length must be non-negative")
        if can_run_sync():
            run_sync(asyncio.sleep(seconds))
            return
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            pass

    time.sleep = sleep


def _mock_webbrowser():
    """`webbrowser.open(url)`: opens a tab. In a web worker there is no
    `window`, so the request is posted to the main thread as
    ``{OPEN_TAB: {url, new}}`` (the page has to handle that message)."""
    webbrowser = types.ModuleType("webbrowser")

    def get(using=None):
        """the "browser controller": this module itself"""
        return webbrowser

    def open(url, new=0, autoraise=True):
        """open `url` in a new tab"""
        is_main_thread = _js.Function(
            'return typeof WorkerGlobalScope === "undefined" || !(self instanceof WorkerGlobalScope);'
        )()
        if is_main_thread:
            _js.window.open(url)
        else:
            message = _js.Function("url", "n", "return {OPEN_TAB: {url: url, new: n}};")(url, new)
            _js.postMessage(message)
        # (like the real webbrowser.open: True when the request was made)
        return True

    def open_new(url):
        return open(url, 1)

    def open_new_tab(url):
        return open(url, 2)

    webbrowser.name = _js.Function(
        """
        // (no navigator: node)
        if (typeof navigator === "undefined") return "Unknown";
        return /firefox/i.test(navigator.userAgent) ? "firefox"
          : /edg/i.test(navigator.userAgent) ? "edge"
          : /chrome|crios/i.test(navigator.userAgent) ? "chrome"
          : /safari/i.test(navigator.userAgent) ? "safari"
          : "Unknown";"""
    )()
    webbrowser.get = get
    webbrowser.open = open
    webbrowser.open_new = open_new
    webbrowser.open_new_tab = open_new_tab
    webbrowser.Error = RuntimeError

    sys.modules["webbrowser"] = webbrowser


def install():
    """install all of the above"""
    _mock_missing_modules()
    _mock_time_sleep()
    _mock_webbrowser()
