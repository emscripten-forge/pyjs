import asyncio
import functools
import http
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import List, Optional

import empack
import typer
from playwright.async_api import Page, async_playwright


@contextmanager
def restore_cwd():
    base_work_dir = os.getcwd()
    yield
    os.chdir(base_work_dir)


def find_free_port():
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def start_server(work_dir, port):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=work_dir, **kwargs)

        def log_message(self, format, *args):
            return

    httpd = HTTPServer(("localhost", port), Handler)

    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    return thread, httpd


@contextmanager
def server_context(work_dir, port):
    thread, server = start_server(work_dir=work_dir, port=port)
    yield server, f"http://localhost:{port}"
    server.shutdown()
    thread.join()


async def playwright_main(page_url, workdir, script_basename):
    async with async_playwright() as p:
        if True:
            browser = await p.chromium.launch(headless=True)
        else:
            browser = await p.chromium.launch(headless=False, slow_mo=100000)
        page = await browser.new_page()

        # 1 min = 60 * 1000 ms
        page.set_default_timeout(60 * 1000)

        async def handle_worker(worker):
            test_output = await worker.evaluate_handle(
                f"""async () =>
            {{
                 const sink = (text) =>{{}}
                 var outputString = ""
                 const print = (text) => {{
                   console.log(text)
                   outputString += text;
                   outputString += "\\n";
                 }}
                 function waitRunDependency() {{
                   const promise = new Promise((r) => {{
                     Module.monitorRunDependencies = (n) => {{
                       if (n === 0) {{
                         r();
                       }}
                     }};
                   }});
                   globalThis.Module.addRunDependency("dummy");
                   globalThis.Module.removeRunDependency("dummy");
                   return promise;
                 }}

                console.log("create module ...")
                var myModule = await createModule({{print:print,error:print}})
                var Module = myModule

                globalThis.Module = Module
                //console.log("import python_data ...")
                await import('./python_data.js')
                //console.log("import script_data ...")
                await import('./script_data.js')
                console.log("wait for dependencies ...")
                var deps = await waitRunDependency()



                console.log("initialize ...")
                myModule.initialize_interpreter()
                console.log("run scripts ...")
                var r = myModule.run_script("{workdir}","{os.path.join(workdir, script_basename)}")

                while(true)
                {{
                    await new Promise(resolve => setTimeout(resolve, 100));
                    const n_unfinished = myModule.n_unfinished();
                    if(n_unfinished <= 0)
                    {{
                        break;
                    }}
                }}

                myModule.run_code("print('collect');import gc;gc.collect();")
                myModule.finalize_interpreter()
                msg = {{
                    return_code : 0,
                    collected_prints : outputString
                }}
                self.postMessage(msg)
                return r
            }}"""
            )
            if int(str(test_output)) != 0:
                raise RuntimeError(f"tests failed with return code: {test_output}")

        page.on("worker", handle_worker)

        async def handle_console(msg):
            txt = str(msg)
            if (
                txt.startswith("warning: Browser does not support creating object URLs")
                or txt.startswith("Failed to load resource:")
                or txt.startswith("Could not find platform dependent libraries")
                or txt.startswith("Consider setting $PYTHONHOME")
            ):
                pass
            else:
                print(txt)

        page.on("console", handle_console)

        await page.goto(page_url)
        await page.wait_for_function("() => globalThis.done")

        test_output = await page.evaluate_handle(
            """
            () =>
            {
            return globalThis.test_output
            }
        """
        )
        return_code = int(str(await test_output.get_property("return_code")))

        await browser.close()
        if return_code != 0:
            sys.exit(return_code)


def pack_script(script_file):
    empack.file_packager.pack_file(
        file=script_file,
        mount_path="/script",
        outname="script_data",
        export_name="globalThis.Module",
        # silent=True,
    )
    # cmd = [f"empack pack file  {script_file}  '/script'  script"]
    # ret = subprocess.run(cmd, shell=True)


def patch_emscripten_generated_js(filename):
    with open(filename, "r") as f:
        content = f.read()
    query = 'Module["preloadPlugins"].push(audioPlugin);'
    content = content.replace(query, "")
    with open(filename, "w") as f:
        f.write(content)
