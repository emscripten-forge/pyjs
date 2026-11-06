"""Async tests for httpx2 with httpx2-jsfetch (pure python, uses pyjs: js.fetch,
response body stream reader, to_js / to_py).

No internet needed: the file downloaded is the pyjs runtime (`.wasm`) served by
pyjs-code-runner next to the page / worker, the expected bytes are read in
JavaScript (base64), independent of the code under test.
Skipped when httpx2 / httpx2_jsfetch are not installed (no-numpy deploy env).
"""

import base64

import pyjs
from pyjs import js

FILENAME = "pyjs_runtime_browser.wasm"


def _url():
    return str(js.URL.new(FILENAME, js.location.href).href)


async def _expected_bytes():
    b64 = await js.Function(
        "url",
        """
        return (async () => {
            const buffer = await (await fetch(url)).arrayBuffer();
            const bytes = new Uint8Array(buffer);
            let binary = "";
            for (let i = 0; i < bytes.length; i += 0x8000) {
                binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
            }
            return btoa(binary);
        })();
        """,
    )(_url())
    data = base64.b64decode(str(b64))
    assert len(data) > 0
    return data


def _httpx_modules():
    try:
        import httpx2
        import httpx2_jsfetch
    except ImportError as e:
        print(f"  skipped: {e}")
        return None
    return httpx2, httpx2_jsfetch


def _assert_same_bytes(got, expected):
    assert isinstance(got, bytes), type(got)
    if got != expected:
        first_diff = next(
            (i for i, (a, b) in enumerate(zip(got, expected)) if a != b),
            min(len(got), len(expected)),
        )
        raise AssertionError(
            f"downloaded {len(got)} bytes, expected {len(expected)}, "
            f"first difference at byte {first_diff}"
        )


async def test_httpx_stream_default_client():
    # like the user code: httpx2.AsyncClient() without an explicit transport
    modules = _httpx_modules()
    if modules is None:
        return
    httpx2, _ = modules
    expected = await _expected_bytes()
    chunks = []
    async with httpx2.AsyncClient() as client:
        async with client.stream("GET", _url()) as response:
            assert response.status_code == 200, response.status_code
            async for chunk in response.aiter_bytes():
                chunks.append(chunk)
    _assert_same_bytes(b"".join(chunks), expected)


async def test_httpx_stream_read_timeout_config():
    # the pattern of a user report (there with a large file from a server that
    # stalls > 5 s at times, hence the longer read timeout)
    modules = _httpx_modules()
    if modules is None:
        return
    httpx2, _ = modules
    expected = await _expected_bytes()
    n = 0
    chunks = []
    async with httpx2.AsyncClient(timeout=httpx2.Timeout(5.0, read=60.0)) as client:
        async with client.stream("GET", _url()) as r:
            assert r.status_code == 200, r.status_code
            async for chunk in r.aiter_bytes():
                n += len(chunk)
                chunks.append(chunk)
    assert n == len(expected) == int(r.headers["content-length"])
    _assert_same_bytes(b"".join(chunks), expected)


async def test_httpx_stream_jsfetch_transport():
    modules = _httpx_modules()
    if modules is None:
        return
    httpx2, httpx2_jsfetch = modules
    expected = await _expected_bytes()
    chunks = []
    transport = httpx2_jsfetch.AsyncJavascriptFetchTransport()
    async with httpx2.AsyncClient(transport=transport) as client:
        async with client.stream("GET", _url()) as response:
            assert response.status_code == 200, response.status_code
            async for chunk in response.aiter_bytes():
                chunks.append(chunk)
    assert len(chunks) >= 1
    _assert_same_bytes(b"".join(chunks), expected)


async def test_httpx_get_jsfetch_transport():
    modules = _httpx_modules()
    if modules is None:
        return
    httpx2, httpx2_jsfetch = modules
    expected = await _expected_bytes()
    transport = httpx2_jsfetch.AsyncJavascriptFetchTransport()
    async with httpx2.AsyncClient(transport=transport) as client:
        response = await client.get(_url())
        assert response.status_code == 200, response.status_code
        assert int(response.headers["content-length"]) == len(expected)
        _assert_same_bytes(response.content, expected)


# a fake globalThis.fetch for the timeout tests (restored afterwards)
_FAKE_FETCH = js.Function(
    "kind",
    """
    const original = globalThis.fetch;
    globalThis.fetch = (url, init) => {
        const signal = init && init.signal;
        const rejectOnAbort = (reject) => signal && signal.addEventListener(
            "abort", () => reject(new DOMException("aborted", "AbortError")));
        if (kind === "stalled-headers") {
            // the response never arrives
            return new Promise((resolve, reject) => rejectOnAbort(reject));
        }
        // the response arrives, its body never delivers data
        const body = new ReadableStream({
            start(controller) {
                signal && signal.addEventListener("abort", () =>
                    controller.error(new DOMException("aborted", "AbortError")));
            }
        });
        return Promise.resolve(new Response(body, {status: 200}));
    };
    return () => { globalThis.fetch = original; };
    """,
)


async def test_httpx_read_timeout():
    # a stalled body read must become httpx2.ReadTimeout (needs the AbortError
    # of the rejected read promise to arrive as a JsException)
    modules = _httpx_modules()
    if modules is None:
        return
    httpx2, httpx2_jsfetch = modules
    restore = _FAKE_FETCH("stalled-body")
    try:
        transport = httpx2_jsfetch.AsyncJavascriptFetchTransport()
        async with httpx2.AsyncClient(transport=transport, timeout=httpx2.Timeout(5.0, read=0.2)) as client:
            async with client.stream("GET", "https://example.invalid/stalled") as response:
                try:
                    async for _ in response.aiter_bytes():
                        pass
                except httpx2.ReadTimeout:
                    pass
                else:
                    raise AssertionError("expected httpx2.ReadTimeout")
    finally:
        restore()


async def test_httpx_connect_timeout():
    modules = _httpx_modules()
    if modules is None:
        return
    httpx2, httpx2_jsfetch = modules
    restore = _FAKE_FETCH("stalled-headers")
    try:
        transport = httpx2_jsfetch.AsyncJavascriptFetchTransport()
        async with httpx2.AsyncClient(transport=transport, timeout=httpx2.Timeout(5.0, connect=0.2)) as client:
            try:
                await client.get("https://example.invalid/stalled")
            except httpx2.ConnectTimeout:
                pass
            else:
                raise AssertionError("expected httpx2.ConnectTimeout")
    finally:
        restore()

