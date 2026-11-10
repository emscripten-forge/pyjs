"""Complete an empack_env_meta.json for the npm package (build_local.sh npm).

mambajs (`empackLockToMambajsLock`) needs the channels of the environment, and
the specs are the base of every later solve (`installPackages`): python is
pinned to the exact build shipped with the package, so the solver never
replaces the running interpreter.

    python npm_env_meta.py <empack_env_meta.json> <channel> [<channel> ...]
"""

import json
import sys


def main(meta_path, channels):
    with open(meta_path) as f:
        meta = json.load(f)
    python = [p for p in meta["packages"] if p["name"] == "python"]
    if len(python) != 1:
        sys.exit(f"{meta_path}: expected exactly one python package, got {len(python)}")
    python = python[0]
    meta["channels"] = list(channels)
    meta["specs"] = [f"python {python['version']} {python['build']}"]
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"{meta_path}: channels={meta['channels']} specs={meta['specs']}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2:])
