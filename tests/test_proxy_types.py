"""The methods of JSProxy by kind of JavaScript object (pyjs/_proxy_types.py):
arrays, typed arrays / buffers, maps, generators, async iterators."""

import collections.abc

import pytest

import pyjs
from pyjs import run_js
from pyjs.ffi import (
    JSArray,
    JSAsyncGenerator,
    JSAsyncIterable,
    JSAsyncIterator,
    JSBuffer,
    JSCallable,
    JSGenerator,
    JSIterable,
    JSIterator,
    JSMap,
    JSMutableMap,
    JSPromise,
    JSProxy,
    JSTypedArray,
)


def js_list(proxy):
    """the items of a JS array as python list"""
    return list(proxy)


# --------------------------------------------------------------------------
# which classes a proxy is an instance of
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "code, expected, not_expected",
    [
        ("[1, 2]", [JSArray, JSIterable], [JSMap, JSBuffer, JSCallable]),
        ("new Uint8Array(2)", [JSTypedArray, JSBuffer, JSIterable], [JSArray, JSMap]),
        ("new ArrayBuffer(2)", [JSBuffer], [JSTypedArray, JSArray]),
        ("new DataView(new ArrayBuffer(2))", [JSBuffer], [JSTypedArray]),
        ("new Map()", [JSMap, JSMutableMap], [JSArray]),
        ("({get(){}, has(){}, size: 0, [Symbol.iterator](){}})", [JSMap], [JSMutableMap]),
        ("new Set()", [JSIterable], [JSMap, JSArray]),
        ("({})", [], [JSArray, JSMap, JSBuffer, JSCallable, JSIterable, JSPromise]),
        ("(() => 1)", [JSCallable], [JSArray, JSIterable]),
        ("Promise.resolve(1)", [JSPromise], [JSCallable]),
        ("[1][Symbol.iterator]()", [JSIterator, JSIterable], [JSGenerator, JSAsyncIterator]),
        ("(function*(){})()", [JSGenerator, JSIterator], [JSAsyncGenerator]),
        ("(async function*(){})()", [JSAsyncGenerator, JSAsyncIterator], [JSGenerator, JSIterator]),
        ("({[Symbol.asyncIterator](){}})", [JSAsyncIterable], [JSAsyncIterator]),
    ],
)
def test_proxy_classes(code, expected, not_expected):
    proxy = run_js(code)
    assert isinstance(proxy, JSProxy)
    for cls in expected:
        assert isinstance(proxy, cls), cls
    for cls in not_expected:
        assert not isinstance(proxy, cls), cls


def test_abc_registration():
    assert isinstance(run_js("[]"), collections.abc.MutableSequence)
    assert isinstance(run_js("new Uint8Array(1)"), collections.abc.Sequence)
    assert isinstance(run_js("new Map()"), collections.abc.MutableMapping)
    assert not isinstance(run_js("({})"), collections.abc.Mapping)


# --------------------------------------------------------------------------
# arrays
# --------------------------------------------------------------------------
def test_array_append_extend_insert():
    a = run_js("[1]")
    a.append(2)
    a.extend([3, 4])
    a.extend(x for x in (5,))
    a.insert(0, 0)
    a.insert(-1, 4.5)
    assert js_list(a) == [0, 1, 2, 3, 4, 4.5, 5]
    a += [6]
    assert js_list(a) == [0, 1, 2, 3, 4, 4.5, 5, 6]
    assert isinstance(a, JSArray)


def test_array_pop():
    a = run_js("[1, 2, 3, 4]")
    assert a.pop() == 4
    assert a.pop(0) == 1
    assert a.pop(-2) == 2
    assert js_list(a) == [3]
    with pytest.raises(IndexError):
        a.pop(5)
    a.pop()
    with pytest.raises(IndexError):
        a.pop()


def test_array_reverse_clear_reversed():
    a = run_js("[1, 2, 3]")
    assert list(reversed(a)) == [3, 2, 1]
    a.reverse()
    assert js_list(a) == [3, 2, 1]
    a.clear()
    assert len(a) == 0


def test_array_index_count_remove():
    a = run_js("[1, 'x', 1, 2]")
    assert a.index("x") == 1
    assert a.count(1) == 2
    a.remove(1)
    assert js_list(a) == ["x", 1, 2]
    with pytest.raises(ValueError):
        a.index("missing")
    with pytest.raises(ValueError):
        a.remove("missing")


def test_array_get_slice():
    a = run_js("[0, 1, 2, 3, 4, 5]")
    for key in [
        slice(1, 3),
        slice(None),
        slice(-2, None),
        slice(4, 2),
        slice(None, None, 2),
        slice(None, None, -1),
        slice(5, 0, -2),
        slice(10, 20),
    ]:
        result = a[key]
        assert isinstance(result, JSArray), key
        assert js_list(result) == [0, 1, 2, 3, 4, 5][key], key


def test_array_set_slice():
    for key, items in [
        (slice(1, 3), [10, 11, 12]),
        (slice(1, 3), []),
        (slice(2, 2), [7]),
        (slice(None), [1]),
        (slice(None, None, 2), [7, 8, 9]),
        (slice(None, None, -1), [9, 8, 7, 6, 5, 4]),
    ]:
        expected = [0, 1, 2, 3, 4, 5]
        a = run_js("[0, 1, 2, 3, 4, 5]")
        expected[key] = items
        a[key] = items
        assert js_list(a) == expected, key
    a = run_js("[0, 1, 2, 3]")
    with pytest.raises(ValueError):
        a[::2] = [1]


def test_array_del_slice():
    for key in [slice(1, 3), slice(None), slice(None, None, 2), slice(None, None, -2), slice(3, 1)]:
        expected = [0, 1, 2, 3, 4, 5]
        a = run_js("[0, 1, 2, 3, 4, 5]")
        del expected[key]
        del a[key]
        assert js_list(a) == expected, key


def test_slice_of_unsliceable():
    with pytest.raises(TypeError):
        run_js("new Map()")[1:2]
    with pytest.raises(TypeError):
        run_js("new Map()")[1:2] = [1]


# --------------------------------------------------------------------------
# typed arrays / buffers
# --------------------------------------------------------------------------
def test_typed_array_slices():
    a = run_js("new Int16Array([0, 1, 2, 3, 4, 5])")
    part = a[1:3]
    assert isinstance(part, JSTypedArray)
    assert part.constructor.name == "Int16Array"
    assert list(part) == [1, 2]
    step = a[::-2]
    assert step.constructor.name == "Int16Array"
    assert list(step) == [5, 3, 1]
    a[1:3] = [10, 20]
    assert list(a) == [0, 10, 20, 3, 4, 5]
    with pytest.raises(ValueError):
        a[1:3] = [1]
    with pytest.raises(TypeError):
        del a[1:3]


def test_buffer_to_bytes_and_memoryview():
    a = run_js("new Float64Array([1.5, 2.5])")
    view = a.to_memoryview()
    assert view.format == "d"
    assert list(view) == [1.5, 2.5]
    assert len(a.to_bytes()) == 16
    # only the part of the ArrayBuffer the typed array looks at
    part = run_js("new Uint8Array(new Uint8Array([1, 2, 3, 4]).buffer, 1, 2)")
    assert part.to_bytes() == b"\x02\x03"
    assert run_js("new Uint8Array([1, 2]).buffer").to_bytes() == b"\x01\x02"
    assert run_js("new DataView(new Uint8Array([1, 2]).buffer)").to_bytes() == b"\x01\x02"


def test_buffer_to_string():
    assert run_js("new TextEncoder().encode('häy')").to_string() == "häy"
    assert run_js("new Uint8Array([0xe4])").to_string("latin1") == "ä"


def test_buffer_assign():
    a = run_js("new Uint8Array(4)")
    a.assign(b"\x01\x02\x03\x04")
    assert list(a) == [1, 2, 3, 4]
    f = run_js("new Float32Array(2)")
    f.assign(memoryview(bytearray(8)))
    with pytest.raises(ValueError):
        a.assign(b"\x01")
    # a view of a part of a buffer: only that part is written
    whole = run_js("new Uint8Array(4)")
    part = pyjs.js.Uint8Array.new(whole.buffer, 1, 2)
    part.assign(b"\x07\x08")
    assert list(whole) == [0, 7, 8, 0]


def test_buffer_assign_item_types():
    """assign between a typed array and a Python buffer: the item types must
    match, under all their names; a C long ("l") is 32 bit on wasm32 and 64
    bit on wasm64"""
    import array
    import struct

    with pytest.raises(ValueError, match="incompatible formats"):
        run_js("new Float64Array(1)").assign(array.array("q", [1]))
    longs = array.array("l", [1, 2])
    if struct.calcsize("l") == 4:
        target = run_js("new Int32Array(2)")
    else:
        target = run_js("new BigInt64Array(2)")
        with pytest.raises(ValueError, match="incompatible formats"):
            run_js("new Int32Array(4)").assign(longs)
    target.assign(longs)
    assert [int(x) for x in target] == [1, 2]
    # plain bytes go into every typed array
    run_js("new Float64Array(1)").assign(bytes(8))


def test_buffer_assign_to():
    a = run_js("new Uint16Array([1, 2])")
    target = bytearray(4)
    a.assign_to(target)
    assert target == bytearray(a.to_bytes())
    with pytest.raises(ValueError):
        a.assign_to(bytearray(3))
    with pytest.raises(TypeError):
        a.assign_to(b"1234")


# --------------------------------------------------------------------------
# maps
# --------------------------------------------------------------------------
def test_map_iteration_and_views():
    m = run_js("new Map([['a', 1], ['b', 2]])")
    assert list(m) == ["a", "b"]
    assert list(m.keys()) == ["a", "b"]
    assert list(m.values()) == [1, 2]
    assert list(m.items()) == [("a", 1), ("b", 2)]
    assert dict(m) == {"a": 1, "b": 2}
    assert len(m) == 2
    assert "a" in m and "c" not in m
    assert "a" in m.keys()


def test_map_get():
    m = run_js("new Map([['a', 1]])")
    assert m.get("a") == 1
    assert m.get("b") is None
    assert m.get("b", 7) == 7
    with pytest.raises(KeyError):
        m["b"]


def test_mutable_map():
    m = run_js("new Map([['a', 1]])")
    m["b"] = 2
    assert m.pop("a") == 1
    assert m.pop("a", "default") == "default"
    with pytest.raises(KeyError):
        m.pop("a")
    with pytest.raises(KeyError):
        del m["a"]
    assert m.setdefault("b", 5) == 2
    assert m.setdefault("c", 5) == 5
    m.update({"d": 4}, e=5)
    assert dict(m) == {"b": 2, "c": 5, "d": 4, "e": 5}
    assert m.popitem() in dict(b=2, c=5, d=4, e=5).items()
    m.clear()
    assert len(m) == 0


# --------------------------------------------------------------------------
# generators
# --------------------------------------------------------------------------
GENERATOR = """
(function* () {
    const log = [];
    try {
        while (true) {
            try {
                log.push(yield log.length);
            } catch (e) {
                log.push("caught " + e.message);
            }
            if (log.length === 4) {
                return log;
            }
        }
    } finally {
        globalThis._pyjs_test_generator_finished = true;
    }
})()
"""


def test_generator_send_and_return_value():
    gen = run_js(GENERATOR)
    assert next(gen) == 0
    assert gen.send("a") == 1
    assert gen.send("b") == 2
    assert gen.throw(ValueError("oops")) == 3
    with pytest.raises(StopIteration) as stop:
        gen.send("c")
    log = list(stop.value.value)
    assert log[:2] == ["a", "b"]
    assert "oops" in log[2]
    assert log[3] == "c"


def test_generator_throw_uncaught_raises_the_original():
    gen = run_js("(function* () { yield 1; yield 2; })()")
    assert next(gen) == 1
    error = KeyError("mine")
    with pytest.raises(KeyError) as raised:
        gen.throw(error)
    assert raised.value is error
    # an exception class, with and without value
    gen = run_js("(function* () { yield 1; })()")
    next(gen)
    with pytest.raises(ValueError, match="text"):
        gen.throw(ValueError, "text")


def test_generator_close():
    pyjs.js._pyjs_test_generator_finished = False
    gen = run_js(GENERATOR)
    next(gen)
    gen.close()
    assert pyjs.js._pyjs_test_generator_finished is True
    with pytest.raises(StopIteration):
        next(gen)
    del pyjs.js._pyjs_test_generator_finished


def test_generator_in_for_loop():
    assert list(run_js("(function* () { yield 1; yield 2; })()")) == [1, 2]


# --------------------------------------------------------------------------
# async iteration
# --------------------------------------------------------------------------
ASYNC_GENERATOR = """
(async function* () {
    let received = [];
    try {
        received.push(yield 1);
        received.push(yield 2);
    } catch (e) {
        yield "caught " + e.message;
    }
    return received;
})()
"""


async def test_async_for_over_async_generator():
    items = []
    async for item in run_js("(async function* () { yield 1; yield 2; })()"):
        items.append(item)
    assert items == [1, 2]


async def test_async_for_over_async_iterable():
    iterable = run_js(
        """({
            [Symbol.asyncIterator]() {
                let i = 0;
                return { next: async () => (i < 3 ? { value: i++, done: false } : { done: true }) };
            }
        })"""
    )
    assert isinstance(iterable, JSAsyncIterable)
    assert [item async for item in iterable] == [0, 1, 2]


async def test_anext():
    gen = run_js("(async function* () { yield 1; })()")
    assert await anext(gen) == 1
    with pytest.raises(StopAsyncIteration):
        await anext(gen)
    assert await anext(gen, "default") == "default"


async def test_async_generator_asend_athrow_aclose():
    gen = run_js(ASYNC_GENERATOR)
    assert await gen.asend(None) == 1
    assert await gen.asend("a") == 2
    assert await gen.athrow(ValueError("oops")) == "caught ValueError('oops')"
    await gen.aclose()
    with pytest.raises(StopAsyncIteration):
        await anext(gen)


async def test_async_generator_athrow_uncaught_raises_the_original():
    gen = run_js("(async function* () { yield 1; yield 2; })()")
    await anext(gen)
    error = KeyError("mine")
    with pytest.raises(KeyError) as raised:
        await gen.athrow(error)
    assert raised.value is error
