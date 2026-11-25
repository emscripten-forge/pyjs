"""Optional parts of the stdlib in the npm package (npm/src/runtime.ts,
`optionalPackages`): with a python whose extension modules are separate
packages (python-lzma, python-sqlite3, ...), their tarballs are shipped but
only installed when asked for (option `stdlib`, `installPackages(["lzma"])`).

Skipped with a python that has these modules built in."""

import importlib.util
import sys

import pytest

import pyjs
import pyjs_core

module = pyjs_core._module

pytestmark = [
    pytest.mark.skipif(not hasattr(module, "installPackages"), reason="not the npm package"),
    pytest.mark.skipif("_lzma" in sys.builtin_module_names, reason="the extension modules are built into this python"),
]


def js(value):
    import json

    return pyjs.js.JSON.parse(json.dumps(value))


async def install(packages):
    return pyjs.to_py(await module.installPackages(js(packages), js({})))


def test_stdlib_option_at_init():
    """the test page asks for ssl, sqlite3, lzma (option `stdlib`): installed
    before python started"""
    import lzma
    import sqlite3
    import ssl  # noqa: F401

    assert lzma.decompress(lzma.compress(b"x" * 100)) == b"x" * 100


async def test_optional_stdlib_installed_on_request():
    """the CJK codecs (not in the page's `stdlib`) are not installed by
    default; installed from the shipped tarball (no solve) by their short
    name; a second request is a no-op"""
    if importlib.util.find_spec("_multibytecodec") is not None:
        pytest.skip("python-cjkcodecs is installed already (by an earlier test)")
    # (not checked with "...".encode("shift_jis"): python's codec registry
    # caches a failed lookup, the codec would stay unknown after the install)
    assert importlib.util.find_spec("_codecs_jp") is None

    assert await install(["cjkcodecs"]) == ["python-cjkcodecs"]
    assert "日本".encode("shift_jis").decode("shift_jis") == "日本"
    assert await install(["python-cjkcodecs"]) == []


async def test_ssl():
    """_ssl brings its own openssl (linked statically, symbols hidden)"""
    if importlib.util.find_spec("_ssl") is None:
        assert await install(["ssl"]) == ["python-ssl"]
    import hashlib
    import ssl

    assert ssl.OPENSSL_VERSION.startswith("OpenSSL")
    assert ssl.create_default_context().protocol == ssl.PROTOCOL_TLS_CLIENT
    assert hashlib.sha256(b"abc").hexdigest().startswith("ba7816bf")


async def test_sqlite_with_its_own_library():
    """_sqlite3 brings its own sqlite (linked statically, symbols hidden):
    open, query, close (close used to trap when the symbols were bound to
    another copy of sqlite)"""
    if importlib.util.find_spec("_sqlite3") is None:
        assert await install(["sqlite3"]) == ["python-sqlite3"]
    import sqlite3

    con = sqlite3.connect(":memory:")
    con.execute("create table t(x)")
    con.executemany("insert into t values (?)", [(i,) for i in range(10)])
    assert con.execute("select sum(x) from t").fetchone() == (45,)
    con.close()
