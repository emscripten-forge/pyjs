"""httpx2 synchronous client (httpx2.Client) via the fetch transport
(httpx2_jsfetch, mounted by build_local.sh): with JSPI the pyodide version uses
pyodide.ffi.run_sync (fetch), without it a synchronous XMLHttpRequest.
The file downloaded is the pyjs runtime served next to the page / worker.
"""

import base64

import pytest

import pyjs
from pyjs import js

from .conftest import *

FILENAME = "pyjs_runtime_browser.wasm"


def _url():
    return str(js.URL.new(FILENAME, js.location.href).href)


def _expected_bytes():
    b64 = js.Function(
        "url",
        """
        const xhr = new XMLHttpRequest();
        xhr.overrideMimeType("text/plain; charset=x-user-defined");
        xhr.open("GET", url, false);
        xhr.send();
        const text = xhr.responseText;
        let binary = "";
        for (let i = 0; i < text.length; i += 0x8000) {
            const part = [];
            for (let j = i; j < Math.min(i + 0x8000, text.length); j++) {
                part.push(String.fromCharCode(text.charCodeAt(j) & 0xff));
            }
            binary += part.join("");
        }
        return btoa(binary);
        """,
    )(_url())
    return base64.b64decode(str(b64))


def test_httpx_sync_get():
    httpx2 = pytest.importorskip("httpx2")
    pytest.importorskip("httpx2_jsfetch")
    expected = _expected_bytes()
    with httpx2.Client() as client:
        response = client.get(_url())
    assert response.status_code == 200
    assert response.content == expected


def test_httpx_sync_stream():
    httpx2 = pytest.importorskip("httpx2")
    pytest.importorskip("httpx2_jsfetch")
    expected = _expected_bytes()
    with httpx2.Client(timeout=httpx2.Timeout(5.0, read=60.0)) as client:
        with client.stream("GET", _url()) as response:
            assert response.status_code == 200
            body = b"".join(response.iter_bytes())
    assert body == expected
