"""Add `channels` and `specs` to the empack_env_meta.json of the npm package
(pixi task `pack`).

`empack pack env` writes the file with the packages of the packed python
environment only. The npm package also solves against it at runtime
(`packages` / `installPackages`, mambajs: `empackLockToMambajsLock`), which
needs two more keys, written into the same file:

- `channels`: where the environment came from (mambajs needs them)
- `specs`: the base requirements of every later solve; python is pinned to
  the exact build shipped with the package, so the solver never replaces the
  running interpreter

and marks the extension-module packages of the split python recipe
(python-ssl, python-sqlite3, ...: side modules in lib-dynload) `optional`:
their tarballs are shipped, but only installed when asked for (option
`stdlib`, `installPackages(["sqlite3"])`), see npm/src/runtime.ts. A python
without them (built in) has no such packages: nothing is marked.

    python npm_env_meta.py <empack_env_meta.json> <channel> [<channel> ...]
"""

import json
import sys

# the packages of the python recipe with optional extension modules
OPTIONAL = {"python-ssl", "python-sqlite3", "python-lzma", "python-cjkcodecs", "python-test-modules"}


def main(meta_path, channels):
    with open(meta_path) as f:
        meta = json.load(f)
    python = [p for p in meta["packages"] if p["name"] == "python"]
    if len(python) != 1:
        sys.exit(f"{meta_path}: expected exactly one python package, got {len(python)}")
    python = python[0]
    meta["channels"] = list(channels)
    meta["specs"] = [f"python {python['version']} {python['build']}"]
    optional = []
    for p in meta["packages"]:
        if p["name"] in OPTIONAL:
            p["optional"] = True
            optional.append(p["name"])
        # a locally built package (rattler-build output dir, file:// channel):
        # unreachable from a browser, and mambajs rejects channels it does not
        # know. It is installed already (never downloaded by the solver), so
        # the first channel is only a label.
        if p.get("channel", "").startswith("file://"):
            print(f"{p['name']}: local channel {p['channel']} -> {channels[0]}")
            p["channel"] = channels[0]
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"{meta_path}: channels={meta['channels']} specs={meta['specs']} optional={optional}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2:])
