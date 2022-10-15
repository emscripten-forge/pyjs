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
    playwright_run_in_worker_thread,
    playwright_run_in_main_thread,
    restore_cwd,
    server_context,
    copy_page_content,
)
import runner_tools


THIS_DIR = os.path.dirname(os.path.realpath(__file__))
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
    slow_mo: int = typer.Option(  # noqa: B008
        0,
        "--slow-mo",
        "-s",
        help="slow_mo",
    ),
    async_main: bool = typer.Option(  # noqa: B008
        False,
        "--async-main",
        "-a",
        help="run async main",
    ),
    worker: bool = typer.Option(  # noqa: B008
        False,
        "--worker",
        "-w",
        help="run code in a worker thread",
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

    # copy .htm and .js file(s) to work_dir
    copy_page_content(work_dir=BLD_DIR)

    # pack the file
    with restore_cwd():
        # with contextlib.redirect_stdout(None):
        os.chdir(BLD_DIR)
        pack_directory(directory, mount_path)

    with server_context(work_dir=BLD_DIR, port=port) as (server, url):

        if worker:
            page_url = f"{url}/runner_worker.html"
            ret = asyncio.run(
                playwright_run_in_worker_thread(
                    page_url=page_url,
                    script_basename=main_script_basename,
                    workdir=mount_path,
                    debug=debug,
                    async_main=async_main,
                    slow_mo=slow_mo,
                )
            )
        else:
            page_url = f"{url}/runner_main.html"
            ret = asyncio.run(
                playwright_run_in_main_thread(
                    page_url=page_url,
                    script_basename=main_script_basename,
                    workdir=mount_path,
                    debug=debug,
                    async_main=async_main,
                    slow_mo=slow_mo,
                )
            )
        if ret != 0:
            os._exit(ret)


if __name__ == "__main__":
    app()
