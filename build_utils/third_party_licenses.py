"""Write THIRD_PARTY_LICENSES.md of the npm package (pixi task `pack`): the
license texts of everything the package contains that is not pyjs itself.

- `--linked <env>`: the conda packages linked statically into the runtime wasm
  (the `*-static` libraries of the host env, e.g. libpython-static,
  libarchive-static, ..., and nanobind)
- `--shipped <env>`: every conda package of the shipped python environment
  (python, its stdlib extension modules with openssl / sqlite / xz, pip, ...)
- `--emscripten <dir>`: emscripten's own code in the runtime (its JS runtime,
  musl libc, libc++ / libc++abi, compiler-rt) and the ports it links (SDL2,
  emdawnwebgpu)

The texts of a conda package are its `info/licenses/` files, read from the
package cache (`extracted_package_dir` in the env's conda-meta record).

    python third_party_licenses.py <out.md> --linked <env> --shipped <env> --emscripten <dir>
"""

import argparse
import json
import sys
from pathlib import Path

# besides the *-static libraries, the host packages compiled into the runtime
LINKED_EXTRA = {"nanobind"}

# emscripten's parts of the runtime: (name, license file glob below the emscripten dir)
EMSCRIPTEN_PARTS = [
    ("emscripten (JS runtime, system libraries)", "LICENSE"),
    ("musl libc", "system/lib/libc/musl/COPYRIGHT"),
    ("libc++", "system/lib/libcxx/LICENSE.TXT"),
    ("libc++abi", "system/lib/libcxxabi/LICENSE.TXT"),
    ("compiler-rt", "system/lib/compiler-rt/LICENSE.TXT"),
    ("SDL2 (emscripten port)", "cache/ports/sdl2/*/LICENSE.txt"),
    ("Dawn / emdawnwebgpu (emscripten port)", "cache/ports/emdawnwebgpu/*/webgpu_cpp/LICENSE"),
]


def conda_packages(env, linked_only):
    """(record, license texts) of the packages in `env`"""
    result = []
    for meta in sorted((Path(env) / "conda-meta").glob("*.json")):
        rec = json.loads(meta.read_text())
        name = rec["name"]
        if linked_only and not (name.endswith("-static") or name in LINKED_EXTRA):
            continue
        texts = []
        pkg_dir = rec.get("extracted_package_dir")
        lic_dir = Path(pkg_dir) / "info" / "licenses" if pkg_dir else None
        if lic_dir and lic_dir.is_dir():
            for f in sorted(p for p in lic_dir.rglob("*") if p.is_file()):
                texts.append((f.relative_to(lic_dir).as_posix(), f.read_text(errors="replace")))
        if not texts:
            print(f"warning: no license text for {name} {rec['version']}", file=sys.stderr)
        result.append((rec, texts))
    return result


# license text -> the section it was printed in (each text only once: the
# packages of one recipe, e.g. python-core / python-ssl, share theirs)
_printed = {}


def section(out, title, license_id, source, texts):
    out.append(f"## {title}\n")
    if license_id:
        out.append(f"License: {license_id}  ")
    out.append(f"Source: {source}\n")
    if not texts:
        out.append("(license text not found in the package, see its source)\n")
    for fname, text in texts:
        text = text.rstrip()
        if text in _printed:
            out.append(f"### {fname}\n\nSame text as in \"{_printed[text]}\".\n")
            continue
        _printed[text] = title
        out.append(f"### {fname}\n\n```\n{text}\n```\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--linked", required=True)
    ap.add_argument("--shipped", required=True)
    ap.add_argument("--emscripten", required=True)
    args = ap.parse_args()

    out = [
        "# Third-party licenses\n",
        "The pyjs runtime (`pyjs_runtime_browser.*`) and the python environment "
        "shipped next to it contain the following third-party software.\n",
    ]
    seen = set()
    for env, linked_only, what in [(args.linked, True, "linked into the runtime"), (args.shipped, False, "shipped python environment")]:
        for rec, texts in conda_packages(env, linked_only):
            key = (rec["name"], rec["version"])
            if key in seen:
                continue
            seen.add(key)
            section(out, f"{rec['name']} {rec['version']} ({what})", rec.get("license"), rec.get("url", ""), texts)
    root = Path(args.emscripten)
    for title, pattern in EMSCRIPTEN_PARTS:
        files = sorted(root.glob(pattern))
        if not files:
            print(f"warning: no license file {pattern} below {root}", file=sys.stderr)
        texts = [(f.name, f.read_text(errors="replace")) for f in files[:1]]
        section(out, title, None, "emscripten", texts)
    Path(args.out).write_text("\n".join(out))
    print(f"{args.out}: {len(seen)} conda packages + {len(EMSCRIPTEN_PARTS)} emscripten parts")


if __name__ == "__main__":
    main()
