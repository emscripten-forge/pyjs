"""Serve the npm example page (npm/example/) with the locally built package.

    python build_utils/npm_example_server.py [build_root/npm/package] [--port 8000]

then open the printed url (`&arch=wasm64` for the wasm64 runtime).
"""

import argparse
import time
from pathlib import Path

from npm_smoke_test import serve

ROOT = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("package_dir", nargs="?", default=str(ROOT / "build_root/npm/package"))
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server, base_url = serve(
        {"/example": ROOT / "npm/example", "/pkg": Path(args.package_dir).resolve()},
        port=args.port,
    )
    print(f"{base_url}/example/index.html?pkg={base_url}/pkg", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.shutdown()
