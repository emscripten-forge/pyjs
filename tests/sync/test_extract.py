"""The runtime's archive extraction, Module._extract_archive (src/extract.cpp,
libarchive): formats (detected from the content), conda packages (.tar.bz2,
.conda), links, renaming, metadata members, shared libraries, unsafe paths.
The archives are built here with python's tarfile / zipfile / compression.zstd.
"""

import io
import json
import os
import shutil
import sys
import tarfile
import zipfile
from compression import zstd

import pytest

import pyjs
import pyjs_core

WASM_MAGIC = b"\0asm\x01\0\0\0"


def extract(data, dest, **options):
    """Module._extract_archive(bytes, dest, options) -> its result as python
    (meta: {member: bytes})"""
    js_bytes = pyjs.buffer_to_js_typed_array(memoryview(bytes(data)), view=False)
    js_options = pyjs.js.JSON.parse(json.dumps(options))
    result = pyjs_core._module._extract_archive(js_bytes, dest, js_options)
    meta_names = pyjs.to_py(pyjs.js.Object.keys(result.meta))
    to_list = pyjs.js.Function("a", "return Array.from(a);")
    return {
        "files": sorted(pyjs.to_py(result.files)),
        "sharedLibs": sorted(pyjs.to_py(result.sharedLibs)),
        "meta": {name: bytes(pyjs.to_py(to_list(result.meta[name]))) for name in meta_names},
    }


def tar_bytes(members, mode="w"):
    """a tar archive (compression by `mode`, e.g. "w:gz") of members:
    (name, bytes) files, (name, None) directories, (name, "->target") symlinks,
    (name, "=>target") hard links"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode=mode, format=tarfile.PAX_FORMAT) as tar:
        for name, content in members:
            info = tarfile.TarInfo(name)
            if content is None:
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            elif isinstance(content, str) and content.startswith("->"):
                info.type, info.linkname = tarfile.SYMTYPE, content[2:]
                tar.addfile(info)
            elif isinstance(content, str) and content.startswith("=>"):
                info.type, info.linkname = tarfile.LNKTYPE, content[2:]
                tar.addfile(info)
            else:
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def read(path):
    with open(path, "rb") as f:
        return f.read()


@pytest.fixture
def dest(tmp_path_factory):
    """a fresh, empty destination directory"""
    d = f"/tmp/extract_test_{os.urandom(4).hex()}"
    yield d
    shutil.rmtree(d, ignore_errors=True)


SIMPLE = [("pkg/__init__.py", b"VALUE = 1\n"), ("data/empty.txt", b""), ("dir_only", None)]


@pytest.mark.parametrize("mode", ["w", "w:gz", "w:bz2"])
def test_tar_formats(dest, mode):
    """plain, gzip and bzip2 tar archives; files, empty files and directories"""
    result = extract(tar_bytes(SIMPLE, mode), dest)
    assert result["files"] == [f"{dest}/data/empty.txt", f"{dest}/pkg/__init__.py"]
    assert read(f"{dest}/pkg/__init__.py") == b"VALUE = 1\n"
    assert read(f"{dest}/data/empty.txt") == b""
    assert os.path.isdir(f"{dest}/dir_only")


def test_tar_zstd(dest):
    """a zstd compressed tar (the inner archives of .conda packages)"""
    extract(zstd.compress(tar_bytes(SIMPLE)), dest)
    assert read(f"{dest}/pkg/__init__.py") == b"VALUE = 1\n"


def test_zip(dest):
    """a zip archive"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("a/b.txt", "zip content")
    extract(buf.getvalue(), dest)
    assert read(f"{dest}/a/b.txt") == b"zip content"


def test_long_names_and_pax(dest):
    """names beyond the 100 characters of ustar (pax headers), non-ascii names"""
    long = "/".join(["d" * 60] * 5) + "/file.txt"
    extract(tar_bytes([(long, b"long"), ("ünïcödé.txt", b"u")], "w:gz"), dest)
    assert read(f"{dest}/{long}") == b"long"
    assert read(f"{dest}/ünïcödé.txt") == b"u"


def test_links(dest):
    """symlinks stay symlinks; hard links become copies (MEMFS has none)"""
    members = [("lib/libx.so.1", WASM_MAGIC + b"x"), ("lib/libx.so", "->libx.so.1"),
               ("lib/hard.txt", b"same"), ("lib/hard2.txt", "=>lib/hard.txt")]
    result = extract(tar_bytes(members), dest)
    assert os.path.islink(f"{dest}/lib/libx.so")
    assert os.readlink(f"{dest}/lib/libx.so") == "libx.so.1"
    assert read(f"{dest}/lib/hard2.txt") == b"same"
    # only the real file counts as shared library (no double loading)
    assert result["sharedLibs"] == [f"{dest}/lib/libx.so.1"]


def test_shared_libs(dest):
    """*.so / *.so.* starting with the wasm magic; other .so files are no wasm"""
    members = [("a/ext.cpython-314-wasm32-emscripten.so", WASM_MAGIC), ("b/libz.so.1.3", WASM_MAGIC),
               ("c/not_wasm.so", b"text"), ("d/plain.wasm", WASM_MAGIC)]
    result = extract(tar_bytes(members), dest)
    assert result["sharedLibs"] == [f"{dest}/a/ext.cpython-314-wasm32-emscripten.so",
                                    f"{dest}/b/libz.so.1.3"]


@pytest.mark.parametrize("name", ["../escape.txt", "a/../../escape.txt", "/abs.txt"])
def test_unsafe_paths_rejected(dest, name):
    """paths leaving the destination are an error, nothing is written outside"""
    with pytest.raises(Exception, match="extracting failed"):
        extract(tar_bytes([(name, b"x")]), dest)
    assert not os.path.exists("/tmp/escape.txt")


def test_no_writes_through_own_symlinks(dest):
    """a symlink of the archive pointing outside cannot be written through"""
    members = [("out", "->/tmp"), ("out/evil.txt", b"x")]
    with pytest.raises(Exception, match="symlink"):
        extract(tar_bytes(members), dest)
    assert not os.path.exists("/tmp/evil.txt")


def test_rename(dest):
    """a path prefix renamed while writing (noarch: site-packages/ -> lib/pythonX.Y/...)"""
    result = extract(tar_bytes([("site-packages/mod.py", b"m"), ("bin/tool", b"t")]), dest,
                     rename=[["site-packages/", "lib/python3.14/site-packages/"]])
    assert result["files"] == [f"{dest}/bin/tool", f"{dest}/lib/python3.14/site-packages/mod.py"]


def test_unsupported_format(dest):
    """no archive at all: a clear error"""
    with pytest.raises(Exception, match="not a supported archive"):
        extract(b"this is no archive" * 100, dest)


def test_empty_tar(dest):
    """an empty archive writes nothing"""
    assert extract(tar_bytes([]), dest)["files"] == []


INFO_PATHS = json.dumps({"paths": [{"_path": "lib/a.txt", "prefix_placeholder": "/opt/prefix"}]}).encode()
PKG = [("lib/a.txt", b"prefix=/opt/prefix\n"), ("lib/libp.so", WASM_MAGIC)]


def test_conda_tar_bz2(dest):
    """a .tar.bz2 conda package: info/ is not written, requested info members are returned"""
    data = tar_bytes(PKG + [("info/paths.json", INFO_PATHS), ("info/index.json", b"{}")], "w:bz2")
    result = extract(data, dest, conda=True, meta=["info/paths.json"])
    assert result["files"] == [f"{dest}/lib/a.txt", f"{dest}/lib/libp.so"]
    assert not os.path.exists(f"{dest}/info")
    assert result["meta"] == {"info/paths.json": INFO_PATHS}
    assert result["sharedLibs"] == [f"{dest}/lib/libp.so"]


def test_conda_v2(dest):
    """a .conda package (zip with pkg-*.tar.zst and info-*.tar.zst)"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("metadata.json", '{"conda_pkg_format_version": 2}')
        z.writestr("pkg-x-1.0-0.tar.zst", zstd.compress(tar_bytes(PKG)))
        z.writestr("info-x-1.0-0.tar.zst", zstd.compress(tar_bytes([("paths.json", INFO_PATHS)])))
    result = extract(buf.getvalue(), dest, conda=True, meta=["info/paths.json"])
    assert result["files"] == [f"{dest}/lib/a.txt", f"{dest}/lib/libp.so"]
    assert result["meta"] == {"info/paths.json": INFO_PATHS}
    assert result["sharedLibs"] == [f"{dest}/lib/libp.so"]
    assert not os.path.exists(f"{dest}/metadata.json")


def extract_with_tar(data, dest, **options):
    """Module._extract_archive with tar=True -> (result, the tar as bytes)"""
    js_bytes = pyjs.buffer_to_js_typed_array(memoryview(bytes(data)), view=False)
    options["tar"] = True
    result = pyjs_core._module._extract_archive(js_bytes, dest, pyjs.js.JSON.parse(json.dumps(options)))
    to_list = pyjs.js.Function("a", "return Array.from(a);")
    return sorted(pyjs.to_py(result.files)), bytes(pyjs.to_py(to_list(result.tar)))


def tree(root):
    """{relative path: content / '-> target'} of a directory"""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root)
            out[rel] = "-> " + os.readlink(path) if os.path.islink(path) else read(path)
    return out


@pytest.mark.parametrize("conda", [False, True])
def test_tar_of_the_extracted_layout(dest, conda):
    """tar=True: an uncompressed tar of what was written (renamed, no info/,
    hard links as copies): extracting it gives the same files (the npm
    package's extracted cache)"""
    if conda:
        buf = io.BytesIO()
        payload = tar_bytes(PKG + [("site-packages/m.py", b"m"), ("lib/link.so", "->libp.so"),
                                   ("lib/copy.txt", "=>lib/a.txt")])
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
            z.writestr("pkg-x-1-0.tar.zst", zstd.compress(payload))
            z.writestr("info-x-1-0.tar.zst", zstd.compress(tar_bytes([("paths.json", INFO_PATHS)])))
        data, options = buf.getvalue(), {"conda": True, "rename": [["site-packages/", "lib/python3.14/site-packages/"]]}
    else:
        data, options = tar_bytes(SIMPLE + [("lib/l", "->../pkg/__init__.py")], "w:bz2"), {}
    files, tar = extract_with_tar(data, dest, **options)
    assert tar[257:262] == b"ustar"  # (a plain, uncompressed tar)
    second = dest + "_from_tar"
    try:
        assert extract(tar, second)["files"] == [f.replace(dest, second, 1) for f in files]
        assert tree(second) == tree(dest)
    finally:
        shutil.rmtree(second, ignore_errors=True)


def test_modification_times_kept(dest):
    """files get the archive's modification time (python's bytecode caches are
    validated against it), also through the tar of the extracted layout"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("m.py")
        info.size, info.mtime = 2, 1_000_000_000
        tar.addfile(info, io.BytesIO(b"x\n"))
    files, tar = extract_with_tar(buf.getvalue(), dest)
    assert os.stat(f"{dest}/m.py").st_mtime == 1_000_000_000
    second = dest + "_from_tar"
    try:
        extract(tar, second)
        assert os.stat(f"{second}/m.py").st_mtime == 1_000_000_000
    finally:
        shutil.rmtree(second, ignore_errors=True)


def test_tar_files(dest):
    """Module._tar_files(paths): regular files relative to "/", with their
    modification times; missing paths and directories are skipped"""
    os.makedirs(f"{dest}/a")
    with open(f"{dest}/a/x.pyc", "wb") as f:
        f.write(b"bytecode")
    os.utime(f"{dest}/a/x.pyc", (1_234_567, 1_234_567))
    to_list = pyjs.js.Function("a", "return Array.from(a);")
    paths = pyjs.js.JSON.parse(json.dumps([f"{dest}/a/x.pyc", f"{dest}/missing.pyc", f"{dest}/a"]))
    data = bytes(pyjs.to_py(to_list(pyjs_core._module._tar_files(paths))))
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        (member,) = tar.getmembers()
        assert member.name == f"{dest}/a/x.pyc".lstrip("/")
        assert member.mtime == 1_234_567
        assert tar.extractfile(member).read() == b"bytecode"


@pytest.mark.skipif(sys.maxsize <= 2**32, reason="wasm64 only: a member > 4 GiB of address space")
def test_large_member_wasm64(dest):
    """a member larger than 1 GiB (the old untar limit), written block by block"""
    size = 2**30 + 17
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo("big.bin")
        info.size = size
        tar.addfile(info, io.BytesIO(b"\1" * size))
    data = buf.getvalue()
    del buf
    extract(data, dest)
    assert os.path.getsize(f"{dest}/big.bin") == size
