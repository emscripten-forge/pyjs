"""Large memory: the runtime is linked with -sMAXIMUM_MEMORY=4GB (wasm32) /
16GB (wasm64), see CMakeLists.txt (emscripten's default is 2GB).

Each test allocates more than the boundary in total, so some memory reaches
above it, and hands a pointer above the boundary to JS.
"""

import ctypes
import sys

import pytest

import pyjs

IS_WASM64 = sys.maxsize > 2**32


CHUNK = 2**29  # 512 MiB (on wasm32 a single object must be < 2 GiB)


def _check_large_memory(boundary):
    # allocate more than `boundary` in total: (at least) one chunk then
    # reaches above the boundary
    chunks = []
    for i in range(boundary // CHUNK + 1):
        chunk = bytearray(CHUNK)
        chunk[0] = i % 256
        chunk[-16:] = bytes(range(16))
        chunks.append(chunk)

    def last_address(chunk):
        return ctypes.addressof((ctypes.c_char * CHUNK).from_buffer(chunk)) + CHUNK - 1

    high = max(chunks, key=last_address)
    assert last_address(high) >= boundary, hex(last_address(high))
    assert all(c[0] == i % 256 and c[-1] == 15 for i, c in enumerate(chunks))

    # a pointer above the boundary passed to JS (view + copy)
    js_sum = pyjs.js.Function("a", "return a.reduce((s, x) => s + x, 0);")
    js_len = pyjs.js.Function("a", "return a.length;")
    for view in (True, False):
        js_array = pyjs.buffer_to_js_typed_array(memoryview(high)[-16:], view=view)
        assert js_len(js_array) == 16
        assert js_sum(js_array) == sum(range(16))
    del chunks, high


@pytest.mark.skipif(IS_WASM64, reason="wasm32 only")
def test_memory_above_2gib_wasm32():
    _check_large_memory(2**31)


@pytest.mark.skipif(not IS_WASM64, reason="wasm64 only")
def test_memory_above_4gib_wasm64():
    _check_large_memory(2**32)
