"""Smoke test of the npm package (build_local.sh npm --test).

Serves the assembled package (build_root/npm/package) under
`/node_modules/<name>/` and the test pages (build_utils/npm_smoke_test/) under
`/test/`, then runs in a headless browser (playwright), for every entry
(`.` = wasm32, `./wasm32`, `./wasm64`) in the main thread and in a module worker:

* offline: init, the Module API (exec / eval / exec_eval / async_exec_eval /
  to_js), stdlib, pointer size of the architecture
* network (--network): `extraPackages: ["numpy"]` and `installPackages(["six"])`
  from the emscripten-forge / conda-forge channels

Each case runs in a fresh page. Timeouts are hang guards only.

Usage: python npm_smoke_test.py <package dir> [--browser chromium|firefox|webkit]
           [--network] [--entries index wasm32 wasm64] [--modes main worker]
"""

import argparse
import asyncio
import functools
import http.server
import json
import sys
import threading
import urllib.parse
from pathlib import Path

from playwright.async_api import async_playwright

TIMEOUT_MS = 600_000
TEST_DIR = Path(__file__).parent / "npm_smoke_test"


class Handler(http.server.SimpleHTTPRequestHandler):
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

    def translate_path(self, path):
        path = urllib.parse.unquote(urllib.parse.urlsplit(path).path)
        for prefix, directory in self.routes.items():
            if path.startswith(prefix):
                rel = path[len(prefix):].lstrip("/")
                target = (directory / rel).resolve()
                if directory.resolve() in [target, *target.parents]:
                    return str(target)
        return "/nonexistent"

    def end_headers(self):
        # always revalidate: a rebuilt package / edited example page is picked
        # up by a plain reload
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, *args):
        pass


def serve(routes, port=0):
    handler = functools.partial(Handler, routes=routes)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


async def run_case(browser, base_url, pkg_url, entry, mode, network):
    page = await browser.new_page()
    console = []
    page.on("console", lambda msg: console.append(f"[{msg.type}] {msg.text}"))
    page.on("pageerror", lambda err: console.append(f"[pageerror] {err}"))
    try:
        query = urllib.parse.urlencode(
            {"entry": entry, "mode": mode, "network": "1" if network else "0", "pkg": pkg_url}
        )
        await page.goto(f"{base_url}/test/index.html?{query}")
        try:
            await page.wait_for_function("() => window.__result !== undefined", timeout=TIMEOUT_MS)
            result = await page.evaluate("() => window.__result")
        except Exception as e:  # hang guard
            result = {"ok": False, "error": f"no result: {e}"}
        return result, console
    finally:
        await page.close()


async def main(pkg_dir, browser_name, entries, modes, network):
    pkg_dir = Path(pkg_dir)
    name = json.loads((pkg_dir / "package.json").read_text())["name"]
    server, base_url = serve({"/test": TEST_DIR, f"/node_modules/{name}": pkg_dir})
    pkg_url = f"{base_url}/node_modules/{name}"
    summary = []
    try:
        async with async_playwright() as p:
            browser = await getattr(p, browser_name).launch()
            try:
                for entry in entries:
                    for mode in modes:
                        label = f"{browser_name} / {entry} / {mode}{' / network' if network else ''}"
                        print(f"=== {label}", flush=True)
                        result, console = await run_case(browser, base_url, pkg_url, entry, mode, network)
                        for c in result.get("checks", []):
                            status = "ok  " if c["ok"] else "FAIL"
                            extra = "" if c["ok"] else f" (got {c['actual']!r}, expected {c['expected']!r})"
                            print(f"  {status} {c['name']}{extra}")
                        if "info" in result:
                            print(f"  info: {result['info']}")
                        if not result.get("ok"):
                            print(f"  error: {result.get('error')}")
                            print("  output:", *result.get("output", []), sep="\n    ")
                            print("  console (last 40):", *console[-40:], sep="\n    ")
                        summary.append((label, bool(result.get("ok"))))
            finally:
                await browser.close()
    finally:
        server.shutdown()
    print("\nnpm smoke test summary:")
    for label, ok in summary:
        print(f"  {'PASSED' if ok else 'FAILED'}  {label}")
    return all(ok for _, ok in summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("package_dir")
    parser.add_argument("--browser", default="chromium", choices=["chromium", "firefox", "webkit"])
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--entries", nargs="+", default=["index", "wasm32", "wasm64"])
    parser.add_argument("--modes", nargs="+", default=["main", "worker"])
    args = parser.parse_args()
    ok = asyncio.run(main(args.package_dir, args.browser, args.entries, args.modes, args.network))
    sys.exit(0 if ok else 1)
