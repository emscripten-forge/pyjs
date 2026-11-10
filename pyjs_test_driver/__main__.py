"""CLI of the test driver: `python -m pyjs_test_driver build-page|run ...`."""

import argparse
import sys

from . import driver, pages


def main(argv=None):
    """parse the command line, build a page or run one; returns the exit code"""
    parser = argparse.ArgumentParser(prog="pyjs_test_driver", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build-page", help="create a page dir")
    build.add_argument("kind", choices=["vanilla", "npm", *pages.BUNDLERS])
    build.add_argument("--out", required=True, help="page dir to create")
    build.add_argument("--assets", help="vanilla: runtime + empack-packed env")
    build.add_argument("--package", help="npm: the npm package dir")
    build.add_argument("--tgz", help="bundlers: the packed npm package")
    build.add_argument("--arch", default="wasm32", choices=["wasm32", "wasm64"], help="npm")
    build.add_argument("--packages", nargs="*", default=[], help="npm / bundlers: test packages")
    build.add_argument("--work-dir", help="bundlers: dir of the app projects")

    run = sub.add_parser("run", help="run a suite on a page dir")
    run.add_argument("page_dir")
    run.add_argument("--browser", default="chromium", choices=["chromium", "firefox", "webkit"])
    run.add_argument("--mode", default="main", choices=["main", "worker"])
    run.add_argument("--entry", default="tests", choices=list(driver.SUITES))
    run.add_argument("--disable-jspi", action="store_true", help="test like without JSPI")
    run.add_argument("--preload", choices=["0", "1"], help="preload shared libs (default: page)")
    run.add_argument("--option", action="append", default=[], metavar="KEY=VALUE",
                     help="passed to the suite's main(options), e.g. filter=async")
    run.add_argument("--result-json", help="write the result to this file")
    run.add_argument("--retries", type=int, default=0,
                     help="rerun if pyjs could not be set up (network errors), not on failed tests")
    run.add_argument("--retry-delay", type=float, default=10, help="seconds between the retries")
    run.add_argument("--meta", action="append", default=[], metavar="KEY=VALUE",
                     help="added to the result file as `build` (e.g. git_rev=...)")

    args = parser.parse_args(argv)
    if args.command == "build-page":
        if args.kind == "vanilla":
            pages.build_vanilla(args.out, args.assets)
        elif args.kind == "npm":
            pages.build_npm(args.out, args.package, args.arch, args.packages)
        else:
            pages.build_bundler(args.kind, args.out, args.tgz, args.packages, args.work_dir)
        print(f"page ({args.kind}): {args.out}")
        return 0

    options = dict(option.split("=", 1) for option in args.option)
    options.update(
        mode=args.mode,
        entry=args.entry,
        disable_jspi="1" if args.disable_jspi else None,
        preload=args.preload,
    )
    meta = dict(item.split("=", 1) for item in args.meta)
    return driver.run(
        args.page_dir, args.browser, options, args.result_json, meta, args.retries, args.retry_delay
    )


if __name__ == "__main__":
    sys.exit(main())
