"""Smoke test of the built documentation (build_local.sh wasm32 --docs --test).

Serves the html output and checks in a headless browser (playwright) that the
JupyterLite embedded in the docs works with pyjs:

* the xeus-python kernel imports pyjs (the python module from this repository)
  and calls JavaScript from Python
* all code cells of the JavaScript API tour (examples/js_api_tour.js) run in
  both runtimes of the javascript kernel (IFrame and Web Worker), ie pyjs can be
  loaded from the `pyjs-runtime/` deployed next to the JupyterLite

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
import pyjs
assert pyjs.__file__.startswith("/lib/python3"), pyjs.__file__
assert pyjs.js.Function("a", "b", "return a + b")(40, 2) == 42
print("_".join(["SMOKE", "DONE"]))
"""


def serve(directory):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    handler.log_message = lambda *args: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


async def run_in_repl(browser, base_url, kernel, code):
    """Run `code` in the JupyterLite REPL, return (ok, page text)."""
    page = await browser.new_page()
    try:
        query = urllib.parse.urlencode({"kernel": kernel, "execute": "1", "code": code})
        await page.goto(f"{base_url}/lite/repl/index.html?{query}")
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


def js_tour_code(html_dir):
    notebook = json.loads((Path(html_dir) / "lite" / "files" / "js_api_tour.ipynb").read_text())
    cells = [
        cell["source"] if isinstance(cell["source"], str) else "".join(cell["source"])
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    ]
    return "\n;\n".join(cells + [DONE])


async def main(html_dir, browser_name):
    server, base_url = serve(html_dir)
    checks = [
        ("python repl (xpython)", "xpython", PYTHON_CODE),
        ("javascript tour (IFrame)", "javascript", js_tour_code(html_dir)),
        ("javascript tour (Web Worker)", "javascript-worker", js_tour_code(html_dir)),
    ]
    failed = 0
    try:
        async with async_playwright() as p:
            browser = await getattr(p, browser_name).launch(headless=True)
            for name, kernel, code in checks:
                ok, text = await run_in_repl(browser, base_url, kernel, code)
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
