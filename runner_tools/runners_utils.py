import http
import os
import socket
import threading
from contextlib import closing, contextmanager
from http.server import HTTPServer
import shutil
import empack
from playwright.async_api import async_playwright

THIS_DIR = os.path.dirname(os.path.realpath(__file__))


def copy_page_content(work_dir):

    shutil.copy(os.path.join(THIS_DIR, "runner_main.html"), work_dir)
    shutil.copy(os.path.join(THIS_DIR, "runner_worker.html"), work_dir)
    shutil.copy(os.path.join(THIS_DIR, "utils.js"), work_dir)
    shutil.copy(os.path.join(THIS_DIR, "worker.js"), work_dir)


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

        def log_message(self, fmt, *args):
            return

    httpd = HTTPServer(("127.0.0.1", port), Handler)

    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    return thread, httpd


@contextmanager
def server_context(work_dir, port):
    thread, server = start_server(work_dir=work_dir, port=port)
    yield server, f"http://127.0.0.1:{port}"
    server.shutdown()
    thread.join()


async def playwright_run_in_worker_thread(
    page_url, workdir, script_basename, debug=False, async_main=False, slow_mo=100000
):
    async with async_playwright() as p:
        if not debug:
            browser = await p.chromium.launch(headless=True)
        else:
            browser = await p.chromium.launch(headless=False, slow_mo=slow_mo)
        page = await browser.new_page()

        # n min = n_min * 60 * 1000 ms
        n_min = 4
        page.set_default_timeout(n_min * 60 * 1000)

        async def handle_worker(worker):
            test_output = await worker.evaluate_handle(
                f"""async () =>
            {{

                importScripts("./utils.js")


                var collected_prints = ""
                const print = (text) => {{
                    console.log(text)
                    collected_prints += text;
                    collected_prints += "\\n";
                }}


                var pyjs = await make_pyjs(print, print);

                var r = eval_main_script(pyjs, "{workdir}","{os.path.join(workdir, script_basename)}");
                if({int(async_main)}){{
                    r = r || await run_async_python_main(pyjs);
                }}

                msg = {{
                    return_code : r,
                    collected_prints : collected_prints
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
    return return_code


async def playwright_run_in_main_thread(
    page_url, workdir, script_basename, debug=False, async_main=False, slow_mo=3000
):
    async with async_playwright() as p:
        if not debug:
            browser = await p.chromium.launch(headless=True)
        else:
            browser = await p.chromium.launch(headless=False, slow_mo=slow_mo)
        page = await browser.new_page()

        # n min = n_min * 60 * 1000 ms
        n_min = 4
        page.set_default_timeout(n_min * 60 * 1000)

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

        with open(os.path.join(THIS_DIR, "utils.js")) as f:
            content = f.read()
            await page.evaluate(
                f"""async () => {{
              {content}
            }}"""
            )

        page.on("console", handle_console)
        await page.goto(page_url)
        status = await page.evaluate(
            f"""async () => {{

                //return 0;
                var collected_prints = ""
                const print = (text) => {{
                    console.log(text)
                    collected_prints += text;
                    collected_prints += "\\n";
                }}
                var pyjs = await globalThis.make_pyjs(print, print);
                var r = globalThis.eval_main_script(pyjs, "{workdir}","{os.path.join(workdir, script_basename)}");
                if({int(async_main)}){{
                    r = r || await run_async_python_main(pyjs);
                }}
                return r;
            }}"""
        )
        return_code = int(status)
    return return_code


def pack_directory(directory, mount_path):
    empack.file_packager.pack_directory(
        directory=directory,
        mount_path=mount_path,
        outname="script_data",
        export_name="globalThis.EmscriptenForgeModule",
        silent=True,
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
