"""Smoke test of the npm package's `lock` CLI (pixi task `test-lock`).

`npx <pkg> lock <specs>` solves package specs in node, at build time, and
writes the pinned packages ({arch: [{url, sha256}]}) that apps pass as `urls`
to `initializePyjsRuntime` (no solver in the browser). The CLI is a separate
node bundle (`bin/lock.mjs`) that no browser test covers, so the task runs it
for real (`lock tabulate`, against the real channels) and this script checks
its output: every architecture of the package pins a tabulate package, with a
sha256 (needed for `verifySha256`).
"""

import json
import sys


def main(path):
    """exit with an error if the lock file does not pin tabulate for every arch"""
    with open(path) as f:
        lock = json.load(f)
    ok = lock and all(
        any("/tabulate-" in p["url"] and p.get("sha256") for p in pinned) for pinned in lock.values()
    )
    if not ok:
        sys.exit(f"unexpected lock file {path}: {lock}")
    print(f"lock ok: {', '.join(lock)}")


if __name__ == "__main__":
    main(sys.argv[1])
