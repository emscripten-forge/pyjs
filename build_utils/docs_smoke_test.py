"""Smoke test of the built documentation (build_local.sh docs --test).

Serves the html output and checks in a headless browser (playwright) that the
JupyterLite embedded in the docs works with pyjs:

* the xeus-python kernels (two jupyterlite deployments: lite/ wasm32,
  lite64/ wasm64) import pyjs
  (the python module from this repository), call JavaScript from Python and,
  if the browser supports JSPI, use pyjs.run_sync
* all code cells of the JavaScript API tour (examples/js_api_tour.js) run in
  both runtimes of the javascript kernel (IFrame and Web Worker), ie pyjs can be
  loaded from the `pyjs-runtime/{wasm32,wasm64}/` deployed next to the JupyterLite

Usage: python docs_smoke_test.py <html dir> [--browser chromium|firefox|webkit]
"""

import argparse
import asyncio
import functools
import http.server
import json
import threading
import urllib.parse
from pathlib import Path

from playwright.async_api import async_playwright

TIMEOUT_MS = 180_000

# the marker is assembled at runtime, so it does not appear in the code input
DONE = '["SMOKE", "DONE"].join("_")'
DONE_TEXT = "SMOKE_DONE"

PYTHON_CODE = """\
import pyjs, sys
assert pyjs.__file__.startswith("/lib/python3"), pyjs.__file__
assert pyjs.js.Function("a", "b", "return a + b")(40, 2) == 42
# cells run as coroutines (webloop task steps): run_sync works with JSPI
if pyjs.jspi_enabled():
    assert pyjs.can_run_sync()
    assert pyjs.run_sync(pyjs.js.Promise.resolve(41)) == 41
print("pointer size", 8 if sys.maxsize > 2**32 else 4, "jspi", pyjs.jspi_enabled())
print("_".join(["SMOKE", "DONE"]))
"""


def serve(directory):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    handler.log_message = lambda *args: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


async def run_in_repl(browser, base_url, kernel, code, lite="lite"):
    """Run `code` in the REPL of the JupyterLite deployment `lite`, return (ok, page text)."""
    page = await browser.new_page()
    try:
        query = urllib.parse.urlencode({"kernel": kernel, "execute": "1", "code": code})
        await page.goto(f"{base_url}/{lite}/repl/index.html?{query}")
        try:
            await page.wait_for_function(
                f"() => /{DONE_TEXT}|Error:|Traceback/.test(document.body.innerText)",
                timeout=TIMEOUT_MS,
            )
        except Exception:
            pass
        text = await page.evaluate("() => document.body.innerText")
        ok = DONE_TEXT in text and "Error:" not in text and "Traceback" not in text
        return ok, text
    finally:
        await page.close()


def notebook_code_cells(html_dir, name):
    notebook = json.loads((Path(html_dir) / "lite" / "files" / name).read_text())
    return [
        cell["source"] if isinstance(cell["source"], str) else "".join(cell["source"])
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    ]


def python_notebook_code(html_dir, name):
    # all code cells of a python notebook, then the done marker
    return "\n".join(notebook_code_cells(html_dir, name) + ['print("_".join(["SMOKE", "DONE"]))'])


def js_tour_code(html_dir, wasm_type=None):
    cells = notebook_code_cells(html_dir, "js_api_tour.ipynb")
    # force the wasm32 / wasm64 pyjs runtime (default: wasm64 if memory64 works)
    prelude = [f'globalThis.PYJS_WASM = "{wasm_type}"'] if wasm_type else []
    return "\n;\n".join(prelude + cells + [DONE])


async def main(html_dir, browser_name):
    server, base_url = serve(html_dir)
    # two independent jupyterlite deployments: lite/ (wasm32), lite64/ (wasm64)
    lites = ["lite"] + (["lite64"] if (Path(html_dir) / "lite64").is_dir() else [])
    checks = []
    for lite in lites:
        checks += [
            (f"python repl ({lite})", lite, "xpython", PYTHON_CODE),
            (f"run_sync notebook ({lite})", lite, "xpython", python_notebook_code(html_dir, "run_sync.ipynb")),
        ]
    checks += [
        ("javascript tour (IFrame, pyjs wasm32)", "lite", "javascript", js_tour_code(html_dir, "wasm32")),
        ("javascript tour (IFrame, pyjs wasm64)", "lite", "javascript", js_tour_code(html_dir, "wasm64")),
        ("javascript tour (Web Worker)", "lite", "javascript-worker", js_tour_code(html_dir)),
    ]
    failed = 0
    try:
        async with async_playwright() as p:
            browser = await getattr(p, browser_name).launch(headless=True)
            for name, lite, kernel, code in checks:
                ok, text = await run_in_repl(browser, base_url, kernel, code, lite)
                print(f"{'PASSED' if ok else 'FAILED'}  {name}", flush=True)
                if not ok:
                    failed += 1
                    print("\n".join(text.splitlines()[-30:]))
            await browser.close()
    finally:
        server.shutdown()
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("html_dir")
    parser.add_argument("--browser", default="chromium", choices=["chromium", "firefox", "webkit"])
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.html_dir, args.browser)))
