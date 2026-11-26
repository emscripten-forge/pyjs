"""Open the example page in headless chromium, check that python printed
"hello world" into it (exit code 1 otherwise).

    python check.py            # serves this directory itself

Needs the package in node_modules/ (see README.md) and playwright's chromium.
"""

import functools
import http.server
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    """serves files without a log line per request"""

    def log_message(self, *args):
        pass


def main():
    # serve this directory on a free port
    handler = functools.partial(QuietHandler, directory=HERE)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/index.html"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda message: print(f"[console] {message.text}"))
        page.on("pageerror", lambda error: print(f"[page error] {error}"))
        page.goto(url)
        try:
            page.wait_for_function(
                "document.getElementById('output').textContent === 'hello world'", timeout=120_000
            )
        except Exception:
            print(f"FAILED: the page shows {page.inner_text('#output')!r}, not 'hello world'")
            sys.exit(1)
        browser.close()
    server.shutdown()
    print("hello world")
    print("OK")


if __name__ == "__main__":
    main()
