import asyncio
import contextlib
import os
import shutil

import typer

from runner_tools.runners_utils import (
    find_free_port,
    pack_script,
    patch_emscripten_generated_js,
    playwright_main,
    restore_cwd,
    server_context,
)

THIS_DIR = os.path.dirname(os.path.realpath(__file__))
PAGE_FILENAME = os.path.join(THIS_DIR, "runner_tools", "runner.html")
WORKER_FILENAME = os.path.join(THIS_DIR, "runner_tools", "worker.js")
BLD_DIR = os.path.join(THIS_DIR, "build")
PYJS_MAIN_JS_FILENAME = os.path.join(BLD_DIR, "pyjs_main.js")

app = typer.Typer()
run_app = typer.Typer()
app.add_typer(run_app, name="run")


@run_app.command()
def script(script_file):

    if not os.path.isabs(script_file):
        script_file = os.path.abspath(script_file)
    script_basename = os.path.basename(script_file)

    port = find_free_port()

    # patching
    patch_emscripten_generated_js(PYJS_MAIN_JS_FILENAME)

    # copy page.htm and worker.js to work_dir
    shutil.copy(PAGE_FILENAME, BLD_DIR)
    shutil.copy(WORKER_FILENAME, BLD_DIR)

    # pack the file
    with restore_cwd():
        with contextlib.redirect_stdout(None):
            os.chdir(BLD_DIR)
            pack_script(script_file)

    with server_context(work_dir=BLD_DIR, port=port) as (server, url):
        page_url = f"{url}/runner.html"
        asyncio.run(
            playwright_main(
                page_url=page_url, script_basename=script_basename, workdir="/script"
            )
        )


if __name__ == "__main__":
    app()
