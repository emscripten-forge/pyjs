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
