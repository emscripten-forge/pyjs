import asyncio
import importlib
import importlib.util
import os
import sys

import pyjs
import pyjs_core


async def test_archive_unpacked_at_init():
    """The npm / bundler pages unpack /test-data/archive_init.tar.gz into
    /unpacked_at_init (option `archives`): done before python started."""
    assert os.path.isdir("/unpacked_at_init/unpacked_init_pkg")
    with open("/unpacked_at_init/data/info.txt") as f:
        assert f.read().strip() == "unpacked_init_pkg"

    sys.path.insert(0, "/unpacked_at_init")
    try:
        import unpacked_init_pkg
    finally:
        sys.path.remove("/unpacked_at_init")
    assert unpacked_init_pkg.VALUE == "init"


async def test_unpack_archive_at_runtime():
    """`pyjs.unpackArchive` unpacks an archive (here bzip2) into the running
    runtime, independent of the cwd; importable right away."""
    old_cwd = os.getcwd()
    os.chdir("/tmp")  # relative paths of the archive must not depend on the cwd
    try:
        archive = pyjs.js.Function(
            "url", "path", "return {url: url, path: path}"
        )("/test-data/archive_runtime.tar.bz2", "/unpacked/at/runtime")
        written = pyjs.to_py(await pyjs_core._module.unpackArchive(archive))
    finally:
        os.chdir(old_cwd)

    assert sorted(written) == [
        "/unpacked/at/runtime/data/info.txt",
        "/unpacked/at/runtime/unpacked_runtime_pkg/__init__.py",
    ], written
    sys.path.insert(0, "/unpacked/at/runtime")
    try:
        import unpacked_runtime_pkg
    finally:
        sys.path.remove("/unpacked/at/runtime")
    assert unpacked_runtime_pkg.VALUE == "runtime"


ARCHIVE_URL = "/test-data/archive_runtime.tar.bz2"


def _archive(path, cache):
    """an archive option for `unpackArchive` (JS object)"""
    return pyjs.js.Function(
        "url", "path", "cache", "return {url: url, path: path, cache: cache}"
    )(ARCHIVE_URL, path, cache)


def _cache_key(path):
    """the key of an archive in the caches: its absolute URL + the destination"""
    url = str(pyjs.js.URL.new(ARCHIVE_URL, pyjs.js.location.href).href)
    return f"{url}?pyjs-archive-path={pyjs.js.encodeURIComponent(path)}"


async def _cached(cache_name, key):
    """the cache entry, waiting up to ~5 s (written in the background)"""
    cache = await pyjs.js.caches.open(cache_name)
    for _ in range(100):
        if await cache.match(key) is not None:
            return True
        await asyncio.sleep(0.05)
    return False


async def test_archive_cache():
    """`cache: true`: the unpacked files and their bytecode are cached by URL +
    path; unpacking it again needs no download and brings back both. Without
    it (the default) nothing is cached."""
    if not pyjs.js.Function("return typeof caches !== 'undefined'")():
        return  # (no Cache Storage here)
    path = "/cached/archive"
    module_file = f"{path}/unpacked_runtime_pkg/__init__.py"
    await pyjs_core._module.unpackArchive(_archive(path, True))
    sys.modules.pop("unpacked_runtime_pkg", None)  # (imported from another path before)
    sys.path.insert(0, path)
    try:
        import unpacked_runtime_pkg as cached_pkg  # (writes its .pyc)
    finally:
        sys.path.remove(path)
    assert cached_pkg.__file__ == module_file
    pyc = importlib.util.cache_from_source(module_file)
    assert os.path.exists(pyc)
    await pyjs_core._module.saveBytecode()
    assert await _cached("pyjs-packages-v2", _cache_key(path))
    assert await _cached("pyjs-packages-v2-bytecode", _cache_key(path))
    # (the earlier test unpacked it without `cache`)
    assert await (await pyjs.js.caches.open("pyjs-packages-v2")).match(_cache_key("/unpacked/at/runtime")) is None

    os.unlink(module_file)
    os.unlink(pyc)
    pyjs.js.performance.clearResourceTimings()
    await pyjs_core._module.unpackArchive(_archive(path, True))
    fetched = pyjs.to_py(pyjs.js.Function("return performance.getEntriesByType('resource').map((e) => e.name)")())
    assert not any(ARCHIVE_URL in u for u in fetched), fetched
    assert os.path.exists(module_file) and os.path.exists(pyc)
