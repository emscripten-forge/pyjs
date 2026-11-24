"""Stand-ins for parts of the standard library that cannot work in a browser.

Many packages import modules like `fcntl` or `termios` at import time without
really needing them. In the browser those modules do not exist (there are no
file locks, terminals or child processes), so the import would fail. Empty or
minimal modules of the same name let such packages import.
"""

import sys
import time
import types

import pyjs_core

_js = pyjs_core.global_this()


def _mock_empty_modules():
    """modules that only have to exist"""
    for name in ("fcntl", "pexpect", "resource"):
        sys.modules.setdefault(name, types.ModuleType(name))


def _mock_termios():
    """terminal control: only the constant packages commonly read"""
    termios = types.ModuleType("termios")
    termios.TCSAFLUSH = 2
    sys.modules.setdefault("termios", termios)


def _mock_time_sleep():
    """`time.sleep` cannot block in a browser (there is one thread, and it
    must return to the browser's event loop to let anything else happen).
    This version at least keeps the promise of the name: it returns after
    `seconds`, by busy waiting. In async code use `await asyncio.sleep(...)`."""

    def sleep(seconds):
        """Delay execution for a given number of seconds.  The argument may be
        a floating point number for subsecond precision.
        """
        start = now = time.time()
        while now - start < seconds:
            now = time.time()

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

    def open_new(url):
        return open(url, 1)

    def open_new_tab(url):
        return open(url, 2)

    webbrowser.name = _js.Function(
        """
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
    _mock_empty_modules()
    _mock_termios()
    _mock_time_sleep()
    _mock_webbrowser()
