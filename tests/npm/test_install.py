"""The npm package's install path (npm/src/runtime.ts, install.ts, fetch.ts):
pinned packages (no solver) at init and at runtime, .conda / .tar.bz2,
prefix relocation, replacing a package, sha256 (only when asked), the package
cache, progress events, files at init, a runtime compiled once (wasmModule).

The packages come from the driver's test channel at /test-channel/
(pyjs_test_driver/test_channel.py)."""

import asyncio
import importlib
import importlib.util
import os
import sys

import pyjs
import pyjs_core

ARCH = "wasm64" if sys.maxsize > 2**32 else "wasm32"
CHANNEL = "/test-channel"
ARCH_V1 = f"{CHANNEL}/emscripten-{ARCH}/pyjs-test-channel-arch-1.0.0-0.tar.bz2"
ARCH_V2 = f"{CHANNEL}/emscripten-{ARCH}/pyjs-test-channel-arch-2.0.0-0.tar.bz2"
CONDA_PKG = f"{CHANNEL}/noarch/pyjs-test-channel-conda-1.0.0-py_0.conda"
SHARE = f"{sys.prefix}/share/pyjs_test_channel".replace("//", "/")

module = pyjs_core._module
js_json = pyjs.js.JSON.parse


def js(value):
    """a python value as JS (via JSON)"""
    import json

    return js_json(json.dumps(value))


async def install(packages, **options):
    """Module.installPackages(packages, options) -> the installed names; the
    progress events of the call are in options["progress"] when asked"""
    events = options.pop("progress", None)
    js_options = js(options)
    if events is not None:
        record = pyjs.js.Function("events", "return (p) => events.push({...p})")
        js_events = pyjs.js.Array.new()
        js_options.onProgress = record(js_events)
    names = pyjs.to_py(await module.installPackages(js(packages), js_options))
    if events is not None:
        events.extend(pyjs.to_py(js_events))
    return names


async def test_pinned_package_at_init():
    """the page pins the arch package (option `urls`): installed before python
    started, its prefix placeholder relocated to "/" """
    with open(f"{SHARE}/arch.txt") as f:
        assert f.read() == ARCH
    with open(f"{SHARE}/prefix.txt") as f:
        assert f.read().strip() == "/share/pyjs_test_channel"


async def test_files_at_init():
    """option `files`: written before python started"""
    if not os.path.exists("/files_at_init"):
        return  # (not every page passes files)
    with open("/files_at_init/hello.txt") as f:
        assert f.read() == "hello from files"


async def test_pinned_conda_format():
    """a pinned .conda package (zip + zstd): noarch site-packages/ lands in
    lib/pythonX.Y/site-packages, importable right away"""
    assert await install([CONDA_PKG]) == ["pyjs-test-channel-conda"]
    import pyjs_test_conda

    assert pyjs_test_conda.FORMAT == "conda"
    assert "/lib/python" in pyjs_test_conda.__file__


async def test_replacing_a_package_removes_its_files():
    """v2 of an installed package: v1's files are gone, v2's are there; back to v1"""
    assert os.path.exists(f"{SHARE}/only_in_v1.txt")
    assert await install([ARCH_V2]) == ["pyjs-test-channel-arch"]
    assert not os.path.exists(f"{SHARE}/only_in_v1.txt")
    assert os.path.exists(f"{SHARE}/only_in_v2.txt")
    # (other tests rely on v1)
    await install([ARCH_V1])
    assert os.path.exists(f"{SHARE}/only_in_v1.txt") and not os.path.exists(f"{SHARE}/only_in_v2.txt")


async def test_sha256_only_checked_when_asked():
    """a wrong sha256 is ignored by default, an error with verifySha256 (then the
    file is downloaded and checked, not taken from the cache)"""
    wrong = {"url": ARCH_V1, "sha256": "0" * 64}
    assert await install([wrong]) == ["pyjs-test-channel-arch"]
    try:
        await install([wrong], verifySha256=True)
    except Exception as e:
        assert "sha256 mismatch" in str(e), e
    else:
        raise AssertionError("a wrong sha256 was accepted with verifySha256")


async def test_package_cache():
    """installed packages are cached as their final layout (Cache Storage, by
    URL; written in the background): the next install of the same URL reports
    "cached" instead of downloading, and gives the same files"""
    if not pyjs.js.Function("return typeof caches !== 'undefined'")():
        return  # (no Cache Storage here)
    url = str(pyjs.js.URL.new(CONDA_PKG, pyjs.js.location.href).href)
    cache = await pyjs.js.caches.open("pyjs-packages-v2")
    for _ in range(100):  # (at most ~5 s)
        if await cache.match(url) is not None:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("not cached after the first install")
    os.unlink(pyjs_test_conda_file())  # (the cached layout brings it back)
    events = []
    await install([CONDA_PKG], progress=events)
    phases = [e["phase"] for e in events if e["item"] == "pyjs-test-channel-conda"]
    assert "cached" in phases and "download" not in phases, phases
    with open(pyjs_test_conda_file()) as f:
        assert f.read() == "FORMAT = 'conda'\n"


async def test_bytecode_cache():
    """python's .pyc files of a package are kept in "<cache>-bytecode" by
    package URL (Module.saveBytecode, also automatic) and come back with the
    package; the source keeps the modification time of the archive (python
    validates the .pyc against it)"""
    if not pyjs.js.Function("return typeof caches !== 'undefined'")():
        return  # (no Cache Storage here)
    import pyjs_test_conda

    importlib.reload(pyjs_test_conda)  # (writes its .pyc if not there yet)
    pyc = importlib.util.cache_from_source(pyjs_test_conda_file())
    assert os.path.exists(pyc)
    await module.saveBytecode()
    url = str(pyjs.js.URL.new(CONDA_PKG, pyjs.js.location.href).href)
    cache = await pyjs.js.caches.open("pyjs-packages-v2-bytecode")
    assert await cache.match(url) is not None
    mtime = os.stat(pyjs_test_conda_file()).st_mtime
    os.unlink(pyc)
    await install([CONDA_PKG])
    assert os.path.exists(pyc)
    assert os.stat(pyjs_test_conda_file()).st_mtime == mtime


def pyjs_test_conda_file():
    """where the .conda test package's module is installed"""
    v = sys.version_info
    return f"/lib/python{v.major}.{v.minor}/site-packages/pyjs_test_conda.py"


async def test_install_timings():
    """Module.installTimings: the phase times (ms) of the last installPackages call"""
    await install([ARCH_V1])
    timings = pyjs.to_py(pyjs.js.JSON.parse(pyjs.js.JSON.stringify(module.installTimings)))
    for key in ["total", "solve", "waitDownloads", "extractPackages", "link", "invalidateCaches"]:
        assert key in timings, timings
    assert all(isinstance(v, int) and v >= 0 for v in timings.values()), timings
    assert timings["total"] >= timings["extractPackages"]


async def test_progress_events():
    """the init reports downloads, extraction and the start, in that order"""
    progress = getattr(pyjs.js.globalThis, "__pyjs_progress", None)
    if progress is None:
        return  # (only the npm page records them)
    events = pyjs.to_py(progress)
    # (later installs report to the same callback: the init ends with the start)
    started = {"item": "python", "phase": "start", "done": 1, "total": 1}
    assert started in events, events
    events = events[: events.index(started) + 1]
    phases = [e["phase"] for e in events]
    assert "download" in phases and "extract" in phases, set(phases)
    assert phases.index("start") > max(i for i, p in enumerate(phases) if p == "extract")
    for e in events:
        assert e["total"] == 0 or 0 <= e["done"] <= e["total"], e


async def test_compile_runtime_once():
    """compileRuntime() + initializePyjsRuntime({wasmModule}): a second runtime
    without compiling the wasm again (npm page only: the package at /pyjs/)"""
    entry = "wasm64" if ARCH == "wasm64" else "index"
    url = f"/pyjs/dist/{entry}.js"
    if not (await pyjs.js.fetch(url, js({"method": "HEAD"}))).ok:
        return  # (bundler pages have no unbundled package)
    package = await pyjs.js.Function("url", "return import(url)")(url)
    wasm_module = await package.compileRuntime()
    assert pyjs.js.Function("m", "return m instanceof WebAssembly.Module")(wasm_module)
    options = pyjs.js.Function("m", "return {wasmModule: m}")(wasm_module)
    # (the resource timings of the second init only: the wasm is not fetched again)
    pyjs.js.performance.clearResourceTimings()
    second = await package.initializePyjsRuntime(options)
    assert second.eval("6 * 7") == 42
    fetched = pyjs.to_py(pyjs.js.Function("return performance.getEntriesByType('resource').map((e) => e.name)")())
    assert any("empack_env_meta.json" in u for u in fetched), fetched  # (timings are recorded)
    assert not any(u.endswith("pyjs_runtime_browser.wasm") for u in fetched), fetched


# a worker getting the compiled runtime by postMessage: initializes pyjs with it
# and answers with a python result (or the error)
_RUNTIME_WORKER = """
self.onmessage = async ({ data }) => {
  try {
    const { initializePyjsRuntime } = await import(data.url);
    const pyjs = await initializePyjsRuntime({ wasmModule: data.wasmModule });
    self.postMessage({ result: pyjs.eval("6 * 7") });
  } catch (e) {
    self.postMessage({ error: String(e && e.stack || e) });
  }
};
"""

_RUN_IN_WORKER = pyjs.js.Function(
    "code",
    "url",
    "wasmModule",
    """
    const blob = new Blob([code], { type: "text/javascript" });
    const worker = new Worker(URL.createObjectURL(blob), { type: "module" });
    return new Promise((resolve) => {
      worker.onmessage = ({ data }) => { worker.terminate(); resolve(data); };
      worker.onerror = (e) => { worker.terminate(); resolve({ error: e.message || "worker error" }); };
      worker.postMessage({ url, wasmModule });
    });
    """,
)


async def test_compiled_runtime_posted_to_a_worker():
    """compileRuntime() in this thread, the module posted to a worker which
    starts pyjs with it (the way to share one compile between workers)"""
    if not pyjs.js.Function("return typeof document !== 'undefined'")():
        return  # (main thread pages only: no nested worker needed)
    entry = "wasm64" if ARCH == "wasm64" else "index"
    url = str(pyjs.js.URL.new(f"/pyjs/dist/{entry}.js", pyjs.js.location.href).href)
    if not (await pyjs.js.fetch(url, js({"method": "HEAD"}))).ok:
        return  # (bundler pages have no unbundled package)
    package = await pyjs.js.Function("url", "return import(url)")(url)
    wasm_module = await package.compileRuntime()
    async def run():
        return await _RUN_IN_WORKER(_RUNTIME_WORKER, url, wasm_module)

    answer = await asyncio.wait_for(run(), 120)  # (a hang guard only)
    assert pyjs.to_py(pyjs.js.JSON.parse(pyjs.js.JSON.stringify(answer))) == {"result": 42}
