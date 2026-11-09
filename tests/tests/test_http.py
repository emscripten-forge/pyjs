"""HTTP downloads through the pyodide compatible API of pyjs.

urllib3 (`urllib3/contrib/emscripten`), requests, pyodide-http and pooch (used by
e.g. `scipy.datasets`) download via a synchronous XMLHttpRequest and use `js` /
`pyodide.ffi` (provided by pyjs). The tests are layered, so the first failing
layer shows which part breaks:

1. ffi primitives these libraries rely on
2. a copy of the XMLHttpRequest code of urllib3 / pyodide-http
3. urllib3, 4. requests, 5. pooch, 6. pyodide-http

No internet needed: the file downloaded is the pyjs runtime (`.wasm`, binary with
all byte values) served by pyjs-code-runner next to the page / worker.
The expected bytes are computed in JavaScript only (base64 = ascii string), so
the reference does not go through the code paths under test.
"""

import base64
import hashlib
import tempfile

import pytest

import pyjs

from .conftest import *

FILENAME = "pyjs_runtime_browser.wasm"


def _url():
    return str(pyjs.js.URL.new(FILENAME, pyjs.js.location.href).href)


_EXPECTED = {}


def _expected_bytes():
    if "data" not in _EXPECTED:
        js_b64 = pyjs.js.Function(
            "url",
            """
            const xhr = new XMLHttpRequest();
            // raw bytes as chars 0..255 (works in the main thread and in workers)
            xhr.overrideMimeType("text/plain; charset=x-user-defined");
            xhr.open("GET", url, false);
            xhr.send();
            if (xhr.status !== 200) {
                throw new Error("status " + xhr.status + " for " + url);
            }
            const text = xhr.responseText;
            let binary = "";
            const chunk = 0x8000;
            for (let i = 0; i < text.length; i += chunk) {
                const part = new Array(Math.min(chunk, text.length - i));
                for (let j = 0; j < part.length; j++) {
                    part[j] = String.fromCharCode(text.charCodeAt(i + j) & 0xff);
                }
                binary += part.join("");
            }
            return [text.length, btoa(binary)];
            """,
        )
        n, b64 = js_b64(_url())
        data = base64.b64decode(str(b64))
        assert len(data) == int(n) > 0
        _EXPECTED["data"] = data
    return _EXPECTED["data"]


def _assert_same_bytes(got, expected):
    assert isinstance(got, bytes), type(got)
    if got != expected:
        first_diff = next(
            (i for i, (a, b) in enumerate(zip(got, expected)) if a != b),
            min(len(got), len(expected)),
        )
        pytest.fail(
            f"downloaded {len(got)} bytes, expected {len(expected)} bytes, "
            f"first difference at byte {first_diff}, "
            f"got[:16]={got[:16]!r} expected[:16]={expected[:16]!r}"
        )


def _is_main_thread_like_urllib3():
    # urllib3/contrib/emscripten/fetch.py: is_in_browser_main_thread
    js = pyjs.js
    return hasattr(js, "window") and hasattr(js, "self") and js.self == js.window


def _is_main_thread_js():
    return bool(
        pyjs.js.Function(
            "return typeof window !== 'undefined' && self === window"
        )()
    )


# ---------------------------------------------------------------------------
# 1. ffi primitives
# ---------------------------------------------------------------------------
def test_http_reference_download():
    data = _expected_bytes()
    # a wasm module: magic number + all byte values occur
    assert data[:4] == b"\x00asm"
    assert len(set(data)) == 256


def test_http_thread_detection():
    assert _is_main_thread_like_urllib3() == _is_main_thread_js()


def test_http_js_string_with_all_chars_to_py():
    s = pyjs.js.Function(
        "const a = []; for (let i = 0; i < 256; i++) a.push(i); "
        "return String.fromCharCode(...a);"
    )()
    assert isinstance(s, str), type(s)
    assert len(s) == 256
    assert [ord(c) for c in s] == list(range(256))
    assert s.encode("latin-1") == bytes(range(256))


def test_http_js_string_iso_8859_15_roundtrip():
    # main thread path: XMLHttpRequest decodes the body as ISO-8859-15,
    # urllib3 / pyodide-http encode it back
    expected = bytes(range(256))
    s = pyjs.js.TextDecoder.new("iso-8859-15").decode(
        pyjs.js.Uint8Array["from"](pyjs.to_js(list(range(256))))
    )
    assert isinstance(s, str), type(s)
    assert len(s) == 256
    assert s.encode("ISO-8859-15") == expected


def test_http_array_buffer_to_bytes():
    # worker path: `xhr.response.to_py().tobytes()` (response is an ArrayBuffer)
    js_buffer = pyjs.js.Function(
        "const a = new Uint8Array(256); for (let i = 0; i < 256; i++) a[i] = i; "
        "return a.buffer;"
    )()
    assert js_buffer.to_py().tobytes() == bytes(range(256))


def test_http_uint8array_with_offset_to_bytes():
    js_array = pyjs.js.Function(
        "const a = new Uint8Array(256); for (let i = 0; i < 256; i++) a[i] = i; "
        "return a.subarray(10, 20);"
    )()
    assert js_array.to_py().tobytes() == bytes(range(10, 20))


def test_http_send_body_conversion():
    # `xhr.send(to_js(body))` with body None (GET) or bytes
    from pyodide.ffi import to_js

    is_nullish = pyjs.js.Function("x", "return x === null || x === undefined")
    assert is_nullish(to_js(None))
    assert int(to_js(b"abc").byteLength) == 3


# ---------------------------------------------------------------------------
# 2. the XMLHttpRequest code of urllib3 / pyodide-http, by hand
# ---------------------------------------------------------------------------
def test_http_xhr_like_urllib3():
    import js
    from email.parser import Parser
    from pyodide.ffi import to_js

    main_thread = _is_main_thread_js()
    xhr = js.XMLHttpRequest.new()
    if not main_thread:
        xhr.responseType = "arraybuffer"
    else:
        xhr.overrideMimeType("text/plain; charset=ISO-8859-15")
    xhr.open("GET", _url(), False)
    xhr.send(to_js(None))
    assert xhr.status == 200

    headers = dict(Parser().parsestr(xhr.getAllResponseHeaders()))
    assert int(headers["content-length"]) == len(_expected_bytes())

    if not main_thread:
        body = xhr.response.to_py().tobytes()
    else:
        body = xhr.response.encode("ISO-8859-15")
    _assert_same_bytes(body, _expected_bytes())


# ---------------------------------------------------------------------------
# 3. urllib3
# ---------------------------------------------------------------------------
def test_http_urllib3_uses_emscripten_backend():
    urllib3 = pytest.importorskip("urllib3")
    from urllib3.contrib.emscripten.connection import EmscriptenHTTPConnection

    assert urllib3.connectionpool.HTTPConnectionPool.ConnectionCls is EmscriptenHTTPConnection


def test_http_urllib3_request():
    urllib3 = pytest.importorskip("urllib3")
    response = urllib3.request("GET", _url())
    assert response.status == 200
    _assert_same_bytes(response.data, _expected_bytes())


def test_http_urllib3_request_streamed():
    urllib3 = pytest.importorskip("urllib3")
    response = urllib3.request("GET", _url(), preload_content=False)
    assert response.status == 200
    body = b"".join(response.stream(1024 * 64))
    response.release_conn()
    _assert_same_bytes(body, _expected_bytes())


# ---------------------------------------------------------------------------
# 4. requests
# ---------------------------------------------------------------------------
def test_http_requests_get():
    requests = pytest.importorskip("requests")
    response = requests.get(_url())
    assert response.status_code == 200
    _assert_same_bytes(response.content, _expected_bytes())


def test_http_requests_get_streamed():
    # what pooch's HTTPDownloader does
    requests = pytest.importorskip("requests")
    response = requests.get(_url(), stream=True)
    response.raise_for_status()
    body = b"".join(response.iter_content(chunk_size=1024))
    _assert_same_bytes(body, _expected_bytes())


# ---------------------------------------------------------------------------
# 5. pooch (scipy.datasets)
# ---------------------------------------------------------------------------
def test_http_pooch_retrieve():
    pooch = pytest.importorskip("pooch")
    expected = _expected_bytes()
    path = pooch.retrieve(
        _url(),
        known_hash=f"sha256:{hashlib.sha256(expected).hexdigest()}",
        path=tempfile.mkdtemp(),
        progressbar=False,
    )
    with open(path, "rb") as f:
        _assert_same_bytes(f.read(), expected)


# ---------------------------------------------------------------------------
# 6. pyodide-http (patches requests / urllib globally -> last)
# ---------------------------------------------------------------------------
def test_http_pyodide_http_requests():
    pyodide_http = pytest.importorskip("pyodide_http")
    requests = pytest.importorskip("requests")
    pyodide_http.patch_all()
    response = requests.get(_url())
    assert response.status_code == 200
    _assert_same_bytes(response.content, _expected_bytes())


def test_http_pyodide_http_urllib():
    pyodide_http = pytest.importorskip("pyodide_http")
    import urllib.request

    pyodide_http.patch_all()
    with urllib.request.urlopen(_url()) as response:
        body = response.read()
    _assert_same_bytes(body, _expected_bytes())


def test_http_typed_array_buffer_like_memoryview():
    # urllib3 (JSPI fetch path) slices the result of `Uint8Array.to_py()`,
    # which is a memoryview in pyodide
    buf = pyjs.js.Function(
        "const a = new Uint8Array(10); for (let i = 0; i < 10; i++) a[i] = i; return a;"
    )().to_py()
    assert len(buf) == 10
    assert buf[3] == 3
    assert bytes(buf[2:5]) == bytes([2, 3, 4])
    assert buf.tolist() == list(range(10))
    target = bytearray(4)
    target[0:4] = buf[6:10]
    assert target == bytes([6, 7, 8, 9])
