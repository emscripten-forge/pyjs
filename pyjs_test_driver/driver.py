"""`run`: run a test suite on a page dir in a browser.

Knows nothing about how the page was made, only the page contract: the page
dir has an `index.html` which reads its options from the url, runs the suite
and publishes the result as `window.__pyjs_result` (`{ok, ...}`).

Served on one origin: the page dir at `/`, the suites (`tests/`,
`benchmarks/` of the repository) at `/tests/` / `/benchmarks/`, each with a
generated file list `__files__.json` (the harness copies the suite into the
emscripten file system), and generated test data at `/test-data/`.
"""

import asyncio
import functools
import http.server
import json
import threading
import time
import urllib.parse
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
SUITES = {"tests": ROOT / "tests", "benchmarks": ROOT / "benchmarks"}
# a hang guard only (a failed JSPI suspension can hang a page), not a speed limit
TIMEOUT_S = 30 * 60
# generated test data (no binary files in the repository): the download tests
# (tests/sync/test_http.py, tests/async/test_jspi.py) fetch these
TEST_DATA = {"/test-data/all_bytes.bin": bytes(range(256)) * 256}


class Handler(http.server.SimpleHTTPRequestHandler):
    """static files from a route table + the generated suite file lists"""

    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".wasm": "application/wasm",
        ".json": "application/json",
    }

    def __init__(self, *args, routes, **kwargs):
        self.routes = routes
        super().__init__(*args, **kwargs)

    def do_GET(self):
        """serve `<suite>/__files__.json`, the test data, everything else as static file"""
        path = urllib.parse.urlsplit(self.path).path
        for name, directory in SUITES.items():
            if path == f"/{name}/__files__.json":
                return self.send_body(json.dumps(suite_files(directory)).encode(), "application/json")
        if path in TEST_DATA:
            return self.send_body(TEST_DATA[path], "application/octet-stream")
        return super().do_GET()

    def send_body(self, body, content_type):
        """answer with generated content"""
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def translate_path(self, path):
        """map an url path to a file below one of the routes (longest prefix first)"""
        path = urllib.parse.unquote(urllib.parse.urlsplit(path).path)
        for prefix, directory in sorted(self.routes.items(), key=lambda r: -len(r[0])):
            if path == prefix or path.startswith(prefix.rstrip("/") + "/"):
                target = (directory / path[len(prefix):].lstrip("/")).resolve()
                if directory.resolve() in [target, *target.parents]:
                    return str(target)
        return "/nonexistent"

    def end_headers(self):
        """always revalidate: rebuilt pages / edited tests are picked up"""
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, *args):
        """quiet: the console of the page is the interesting output"""


def suite_files(directory):
    """the files of a suite, relative to it (no caches)"""
    return sorted(
        str(p.relative_to(directory))
        for p in directory.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    )


def serve(page_dir, port=0):
    """serve the page dir + the suites on 127.0.0.1, in a background thread"""
    routes = {"/": Path(page_dir).resolve(), **{f"/{name}": d for name, d in SUITES.items()}}
    handler = functools.partial(Handler, routes=routes)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


async def run_page(page_dir, browser_name="chromium", options=None, headless=True):
    """open the page with `options` (url query), return its result dict"""
    options = {k: v for k, v in (options or {}).items() if v is not None}
    server, base_url = serve(page_dir)
    try:
        async with async_playwright() as p:
            browser = await getattr(p, browser_name).launch(headless=headless)
            try:
                page = await browser.new_page()
                page.on("console", lambda msg: print(msg.text, flush=True))
                page.on("pageerror", lambda err: print(f"[page error] {err}", flush=True))
                query = urllib.parse.urlencode(options)
                await page.goto(f"{base_url}/index.html?{query}")
                try:
                    await page.wait_for_function(
                        "() => window.__pyjs_result !== undefined", timeout=TIMEOUT_S * 1000
                    )
                except Exception as e:
                    return {"ok": False, "error": f"no result within {TIMEOUT_S}s: {e}"}
                return await page.evaluate("() => window.__pyjs_result")
            finally:
                await browser.close()
    finally:
        server.shutdown()


def run(page_dir, browser_name, options, result_json=None, meta=None, retries=0, retry_delay=10):
    """`run` command: run the page, print the result, return the exit code.

    `retries`: rerun (after `retry_delay` seconds) when pyjs could not be
    brought up at all (the page result has an `error`, no test ran), e.g. a
    network error while installing the test packages (npm pages, mambajs).
    Failed tests are never retried.
    """
    result = asyncio.run(run_page(page_dir, browser_name, options))
    for attempt in range(1, retries + 1):
        if "error" not in result:
            break
        print(
            f"\nsetup failed, retry {attempt} / {retries} in {retry_delay}s: "
            f"{result['error'].splitlines()[0]}",
            flush=True,
        )
        time.sleep(retry_delay)
        result = asyncio.run(run_page(page_dir, browser_name, options))
    if meta:
        result["build"] = meta
    if result_json:
        Path(result_json).parent.mkdir(parents=True, exist_ok=True)
        Path(result_json).write_text(json.dumps(result, indent=2))
    summary = {k: v for k, v in result.items() if k not in ("results", "environment", "config")}
    print(f"\nresult ({browser_name}, {options}): {json.dumps(summary)}", flush=True)
    return 0 if result.get("ok") else 1
