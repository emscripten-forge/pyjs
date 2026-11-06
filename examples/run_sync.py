# %% [markdown]
# # Waiting for JavaScript promises in synchronous code
#
# JavaScript APIs like `fetch` return promises. In `async` code they can simply
# be awaited (`await pyjs.js.fetch(url)`). With `pyjs.run_sync`, also a plain,
# synchronous Python function can wait for a promise, without making all its
# callers `async`.
#
# This uses JSPI (JavaScript Promise Integration), supported by recent
# Chromium, Firefox and Safari. pyjs uses it automatically when the browser
# supports it: `pyjs.jspi_enabled()`. Libraries built for pyodide use it too,
# e.g. urllib3 / requests download via `fetch` then.
#
# `pyjs.can_run_sync()` tells whether the current code may wait: JSPI is
# available and the code runs in an asyncio task. Notebook cells run as
# coroutines, so this is the case here.

# %% [code]
import pyjs
from pyjs import js

print("JSPI:", pyjs.jspi_enabled(), "| can_run_sync:", pyjs.can_run_sync())

# %% [markdown]
# Two **synchronous** functions, waiting for a JavaScript timer and for `fetch`:

# %% [code]
def sleep_ms(ms):
    """Wait for a JavaScript timer, return `ms`."""
    promise = js.Function("ms", "return new Promise(r => setTimeout(() => r(ms), ms));")(ms)
    return pyjs.run_sync(promise)


def fetch_text(url):
    """Download `url` with the JavaScript fetch API, return the text."""
    response = pyjs.run_sync(js.fetch(url))
    return pyjs.run_sync(response.text())

# %% [code]
if pyjs.can_run_sync():
    print("slept", sleep_ms(500), "ms")
    html = fetch_text(js.location.href)
    print("fetched", len(html), "characters:", html[:60].replace("\n", " "), "...")
else:
    print("this browser has no JSPI: use `await` instead, e.g. `await js.fetch(url)`")

# %% [markdown]
# The browser stays responsive while Python waits: other JavaScript and other
# asyncio tasks keep running. A rejected promise raises a `pyjs.JsException`:

# %% [code]
if pyjs.can_run_sync():
    try:
        pyjs.run_sync(js.Function("return Promise.reject(new Error('nope'))")())
    except pyjs.JsException as err:
        # the JavaScript error object
        print("rejected with:", err.get_js_proxy().message)
