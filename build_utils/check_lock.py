"""Check the output of `npx <pkg> lock tabulate -o <file>` (pixi task `test-lock`):
every architecture pins a tabulate package with its sha256."""

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
