"""CLI of the test driver: `python -m pyjs_test_driver build-page|run ...`."""

import argparse
import sys
from pathlib import Path

from . import driver, pages


def main(argv=None):
    """parse the command line, build a page or run one; returns the exit code"""
    parser = argparse.ArgumentParser(prog="pyjs_test_driver", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build-page", help="create a page dir")
    build.add_argument("kind", choices=["npm", "pyodide", *pages.BUNDLERS])
    build.add_argument("--out", required=True, help="page dir to create")
    build.add_argument("--package", help="npm: the npm package dir")
    build.add_argument("--tgz", help="bundlers: the packed npm package (or its directory)")
    build.add_argument("--arch", default="wasm32", choices=["wasm32", "wasm64"], help="npm")
    build.add_argument("--packages", nargs="*", default=[], help="npm / bundlers: test packages")
    build.add_argument("--work-dir", help="bundlers: dir of the app projects")
    build.add_argument("--pyodide-version", help="pyodide: the release")
    build.add_argument("--cache-dir", help="pyodide: where releases are downloaded to (once)")

    run = sub.add_parser("run", help="run a suite on a page dir (every browser x mode)")
    run.add_argument("page_dir")
    # (several, also as one space separated string: `--browser "chromium firefox"`)
    run.add_argument("--browser", nargs="+", default=["chromium"])
    run.add_argument("--mode", nargs="+", default=["main"])
    run.add_argument("--label", help="name of the page in the summary (default: its dir name)")
    run.add_argument("--entry", default="tests", choices=list(driver.SUITES))
    run.add_argument("--disable-jspi", action="store_true", help="test like without JSPI")
    run.add_argument("--preload", choices=["0", "1"], help="preload shared libs (default: page)")
    run.add_argument("--option", action="append", default=[], metavar="KEY=VALUE",
                     help="passed to the suite's main(options), e.g. filter=async")
    run.add_argument("--result-json",
                     help="write each result to this file ({browser} / {mode} are replaced)")
    run.add_argument("--retries", type=int, default=0,
                     help="rerun if pyjs could not be set up (network errors), not on failed tests")
    run.add_argument("--retry-delay", type=float, default=10, help="seconds between the retries")
    run.add_argument("--meta", action="append", default=[], metavar="KEY=VALUE",
                     help="added to the result file as `build` (e.g. git_rev=...)")

    args = parser.parse_args(argv)
    if args.command == "build-page":
        if args.kind == "npm":
            pages.build_npm(args.out, args.package, args.arch, args.packages)
        elif args.kind == "pyodide":
            pages.build_pyodide(args.out, args.pyodide_version, args.packages, args.cache_dir)
        else:
            pages.build_bundler(args.kind, args.out, args.tgz, args.packages, args.work_dir)
        print(f"page ({args.kind}): {args.out}")
        return 0

    return run_all(args)


def split_words(values):
    """["chromium firefox", "webkit"] -> ["chromium", "firefox", "webkit"]"""
    return [word for value in values for word in value.split()]


def run_all(args):
    """the suite on the page for every browser x mode, then a summary; 1 if one failed"""
    browsers, modes = split_words(args.browser), split_words(args.mode)
    for value, allowed in ((browsers, {"chromium", "firefox", "webkit"}), (modes, {"main", "worker"})):
        if not set(value) <= allowed:
            sys.exit(f"unknown: {sorted(set(value) - allowed)} (allowed: {sorted(allowed)})")
    label = args.label or Path(args.page_dir).name
    summary, failed = [], False
    for browser in browsers:
        for mode in modes:
            print(f"========================================\n{label}: {browser} / {mode}\n"
                  "========================================", flush=True)
            options = dict(option.split("=", 1) for option in args.option)
            options.update(
                mode=mode,
                entry=args.entry,
                disable_jspi="1" if args.disable_jspi else None,
                preload=args.preload,
            )
            meta = dict(item.split("=", 1) for item in args.meta)
            if meta:
                meta.update(browser=browser, mode=mode)
            result_json = args.result_json.format(browser=browser, mode=mode) if args.result_json else None
            ok = driver.run(args.page_dir, browser, options, result_json, meta, args.retries, args.retry_delay) == 0
            summary.append(f"  {'PASSED' if ok else 'FAILED'}  {label} / {browser} / {mode}")
            failed |= not ok
    print("\nsummary:\n" + "\n".join(summary), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
