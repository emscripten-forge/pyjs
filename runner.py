import asyncio
import contextlib
import os
import shutil
import sys
from pathlib import Path

import typer
from typing import List

from runner_tools.runners_utils import (  # find_free_port,
    pack_directory,
    patch_emscripten_generated_js,
    playwright_main,
    restore_cwd,
    server_context,
)

THIS_DIR = os.path.dirname(os.path.realpath(__file__))
PAGE_FILENAME = os.path.join(THIS_DIR, "runner_tools", "runner.html")
WORKER_FILENAME = os.path.join(THIS_DIR, "runner_tools", "worker.js")
BLD_DIR = os.path.join(THIS_DIR, "build")
PYJS_MAIN_JS_FILENAME = os.path.join(BLD_DIR, "pyjs_runtime_browser.js")

app = typer.Typer()
run_app = typer.Typer()
app.add_typer(run_app, name="run")


@run_app.command()
def script(
    directory: Path = typer.Option(  # noqa: B008
        ...,
        "--directory",
        "-d",
        help="directory to mount",
    ),
    mount_path: Path = typer.Option(  # noqa: B008
        ...,
        "--mount-path",
        "-m",
        help="where to mount directory",
    ),
    main: Path = typer.Option(  # noqa: B008
        ...,
        "--main",
        "-q",
        help="path to main",
    ),
    port: int = typer.Option(  # noqa: B008
        8000,
        "--port",
        "-p",
        help="port mode",
    ),
    debug: bool = typer.Option(  # noqa: B008
        False,
        "--debug",
        "-x",
        help="debug mode",
    ),
    async_main: bool = typer.Option(  # noqa: B008
        False,
        "--async-main",
        "-a",
        help="run async main",
    ),
):
    directory = Path(directory).resolve()
    # for script_file in script_files:
    #     if not os.path.isabs(script_file):
    #         script_file = Path(script_file).resolve()
    main_script_basename = os.path.basename(main)

    # port = find_free_port()

    # patching
    patch_emscripten_generated_js(PYJS_MAIN_JS_FILENAME)

    # copy page.htm and worker.js to work_dir
    shutil.copy(PAGE_FILENAME, BLD_DIR)
    shutil.copy(WORKER_FILENAME, BLD_DIR)

    # pack the file
    with restore_cwd():
        # with contextlib.redirect_stdout(None):
        os.chdir(BLD_DIR)
        pack_directory(directory, mount_path)

    with server_context(work_dir=BLD_DIR, port=port) as (server, url):
        page_url = f"{url}/runner.html"
        ret = asyncio.run(
            playwright_main(
                page_url=page_url,
                script_basename=main_script_basename,
                workdir=mount_path,
                debug=debug,
                async_main=async_main,
            )
        )
    sys.exit(ret)


if __name__ == "__main__":
    app()
