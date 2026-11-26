import pytest
import pyjs

from helpers import *


class TestPyToJs:
    @pytest.mark.parametrize(
        "test_input",
        [-1, 1, 1.0, 0, True, False, "0"],
    )
    def test_fundamentals(self, test_input):
        output = pyjs.to_js(test_input)
        # (values that are converted automatically pass through to_js unchanged)
        assert js_assert_eq(output, test_input)

    def test_none(self):
        t = pyjs.to_js(None)
        assert pyjs.pyjs_core._module._is_undefined(t) == True

    @pytest.mark.parametrize(
        "keys",
        [
            (1, "1"),
            (1.0, "1"),
            (1.5, "1.5"),
            (True, "true"),
            # floats JavaScript names differently than Python
            (float("inf"), "Infinity"),
            (float("-inf"), "-Infinity"),
            (float("nan"), "NaN"),
            (1e21, "1e+21"),
            (1e-7, "1e-7"),
        ],
    )
    def test_dict_key_collision(self, keys):
        """two keys that become the same JavaScript property: an error, not
        a silently lost value"""
        with pytest.raises(pyjs.ConversionError):
            pyjs.to_js(dict.fromkeys(keys, 0))

    def test_c_long_buffer(self):
        """a buffer of C longs (format "l": 32 bit on wasm32, 64 bit on
        wasm64, numpy's int64 there): the typed array has the right item
        size, through to_js and buffer_to_js"""
        import array
        import struct

        longs = array.array("l", [1, -2, 3])
        expected_class = "Int32Array" if struct.calcsize("l") == 4 else "BigInt64Array"
        for js_array in [pyjs.to_js(longs), pyjs.buffer_to_js_typed_array(longs)]:
            assert js_array.constructor.name == expected_class
            assert [int(x) for x in js_array] == [1, -2, 3]

    def test_dict_float_keys_without_collision(self):
        """float keys become the property names JavaScript gives them"""
        obj = pyjs.to_js({float("inf"): 1, 1e21: 2, 0.5: 3})
        assert pyjs.to_py(pyjs.js.Object.keys(obj)) == ["Infinity", "1e+21", "0.5"]

    def test_only_lists_and_tuples_become_arrays(self):
        # as in pyodide: other sequences (range, deque, ...) are not copied,
        # JavaScript gets a proxy of them
        import collections

        is_array = pyjs.js.Array.isArray
        assert is_array(pyjs.to_js([1, 2]))
        assert is_array(pyjs.to_js((1, 2)))
        for sequence in [range(3), collections.deque([1, 2])]:
            # (an object that is not converted comes back as a proxy of it,
            # a JSDoubleProxy)
            result = pyjs.to_js(sequence)
            assert isinstance(result, pyjs.ffi.JSDoubleProxy)
            assert not is_array(result)
            assert result.unwrap() is sequence
        # a range far too big to copy: no attempt to copy it
        huge = range(2**31)
        assert pyjs.to_js(huge).unwrap() is huge
        # inside a converted container: stored as proxy, read back as itself
        inner = range(2)
        array = pyjs.to_js([inner])
        assert is_array(array)
        assert not is_array(pyjs.js.Function("a", "return a[0];")(array))
        assert array[0] is inner


class TestToJsWithOptions:
    """`to_js` with an option (`pyproxies`, `dict_converter`, a converter
    function, ...) is done step by step by Python code (pyjs/convert.py),
    not by the one-hop conversion in C++: a second implementation, which
    must give the same results."""

    def test_converter_temporaries_are_different_objects(self):
        """A converter that builds a new Python object per item and has it
        converted: every item gets its OWN JavaScript object. (The
        conversion remembers what it converted by `id(obj)`; the id of a
        freed temporary is reused by the next one.)"""

        class Point:
            def __init__(self, v):
                self.v = v

        def converter(obj, convert, cache_conversion):
            return convert({"v": obj.v})

        points = [Point(i) for i in range(10)]
        result = pyjs.to_js(points, default_converter=converter)
        assert [item.v for item in result] == list(range(10))

    @pytest.mark.parametrize(
        "options",
        [
            lambda: dict(pyproxies=pyjs.js.Array.new()),
            lambda: dict(create_pyproxies=False),
            lambda: dict(dict_converter=pyjs.js.Object.fromEntries),
            lambda: dict(default_converter=lambda obj, convert, cache: convert(obj)),
            lambda: dict(eager_converter=lambda obj, convert, cache: convert(obj)),
        ],
        ids=["pyproxies", "create_pyproxies", "dict_converter", "default_converter", "eager_converter"],
    )
    def test_jsnull_with_every_option(self, options):
        """`jsnull` (JavaScript's null) converts to null, whatever option is
        given, in a list and as a dict value"""
        is_null = pyjs.js.Function("x", "return x === null;")
        array = pyjs.to_js([1, pyjs.jsnull], **options())
        assert is_null(array[1]) is True
        obj = pyjs.to_js({"a": pyjs.jsnull}, **options())
        assert is_null(pyjs.js.Function("o", "return o.a;")(obj)) is True

    def test_converter_may_return_jsnull(self):
        is_null = pyjs.js.Function("a", "return a[0] === null;")
        array = pyjs.to_js([object()], default_converter=lambda obj, convert, cache: pyjs.jsnull)
        assert is_null(array) is True


class TestDeepNesting:
    """The deep conversions walk a structure by recursion, one call per
    level of nesting. The call stack of the browser is small (a WebKit worker
    gives up at about 500 levels, which ends the page), so the conversions
    stop at a fixed depth that is safe everywhere: RecursionError beyond."""

    # (MAX_NESTING in src/deep.cpp)
    LIMIT = 200

    @staticmethod
    def nested_list(levels):
        """a list nested `levels` deep below the outermost one"""
        nested = []
        for _ in range(levels):
            nested = [nested]
        return nested

    # the same in JavaScript
    js_nested_list = staticmethod(
        pyjs.js.Function(
            "levels",
            """
            let nested = [];
            for (let i = 0; i < levels; i++) nested = [nested];
            return nested;
            """,
        )
    )

    @staticmethod
    def depth_of(nested):
        depth = 0
        while nested:
            nested = nested[0]
            depth += 1
        return depth

    def test_up_to_the_limit(self):
        nested = self.nested_list(self.LIMIT)
        js_value = pyjs.to_js(nested)
        assert self.depth_of(pyjs.to_py(js_value)) == self.LIMIT
        assert self.depth_of(pyjs.to_py(self.js_nested_list(self.LIMIT))) == self.LIMIT

    @pytest.mark.parametrize("levels", [LIMIT + 1, 5000])
    def test_to_js_beyond_the_limit(self, levels):
        nested = self.nested_list(levels)
        try:
            with pytest.raises(RecursionError, match="nested more than 200 levels"):
                pyjs.to_js(nested)
        finally:
            # Taken apart level by level. Just dropping a very deep list
            # makes Python free it recursively, which can overflow the stack
            # of the browser too (CPython's own limit, not the conversion's).
            while nested:
                nested = nested.pop()

    @pytest.mark.parametrize("levels", [LIMIT + 1, 5000])
    def test_to_py_beyond_the_limit(self, levels):
        with pytest.raises(RecursionError, match="nested more than 200 levels"):
            pyjs.to_py(self.js_nested_list(levels))

    def test_depth_argument_is_not_affected(self):
        """the limit is about the levels that are converted: with `depth`
        the rest of a deep structure stays a proxy"""
        result = pyjs.to_py(self.js_nested_list(5000), depth=3)
        assert isinstance(result[0][0][0], pyjs.JSProxy)

    def test_container_changed_during_the_conversion(self):
        """Converting an item can run Python code. A list that such code
        empties while the list is converted is an error, not a read of items
        that are gone."""

        class Emptier:
            def __init__(self, victim):
                self.victim = victim

            def __buffer__(self, flags):
                self.victim.clear()
                return memoryview(b"x")

        data = []
        data.extend([Emptier(data), "a" * 100, "b" * 100])
        with pytest.raises(RuntimeError, match="changed size"):
            pyjs.to_js(data)

    def test_reasonable_depth_still_works(self):
        nested = []
        for _ in range(100):
            nested = [nested]
        back = pyjs.to_py(pyjs.to_js(nested))
        depth = 0
        while back:
            back = back[0]
            depth += 1
        assert depth == 100


class TestDetachedBuffers:
    """An ArrayBuffer that was transferred away (postMessage, structuredClone
    with `transfer`) is "detached": it still exists, with length 0, but
    JavaScript throws when a view of it is created. Converting one must give
    the empty result its length says, not let that JavaScript exception
    travel through Python's C code (which ends the page)."""

    DETACHED = """
        (() => {
            const buffer = new ArrayBuffer(16);
            const view = new Float64Array(buffer);
            structuredClone(buffer, { transfer: [buffer] });
            return { buffer, view };
        })()
    """

    def test_to_py_of_a_detached_buffer(self):
        detached = pyjs.code.run_js(self.DETACHED)
        assert bytes(detached.buffer.to_py()) == b""
        assert bytes(detached.view.to_py()) == b""
        # inside a structure
        assert [bytes(x) for x in pyjs.to_py(pyjs.js.Array.of(detached.buffer, detached.view))] == [b"", b""]

    def test_to_bytes_of_a_detached_buffer(self):
        detached = pyjs.code.run_js(self.DETACHED)
        assert detached.buffer.to_bytes() == b""
        assert detached.view.to_bytes() == b""

    def test_python_still_works_afterwards(self):
        assert pyjs.to_py(pyjs.to_js([1, 2, 3])) == [1, 2, 3]


class TestOddKeysAndObjects:
    """data whose keys have a special meaning in JavaScript"""

    def test_to_py_object_with_a_key_called_constructor(self):
        # (e.g. parsed JSON: a plain object, although `obj.constructor` is
        # not `Object` here)
        obj = pyjs.code.run_js('JSON.parse(\'{"constructor": "x", "a": [1]}\')')
        assert pyjs.to_py(obj) == {"constructor": "x", "a": [1]}

    def test_to_js_dict_with_a_key_called_proto(self):
        # `obj["__proto__"] = value` in JavaScript sets the prototype of
        # the object instead of creating a property
        result = pyjs.to_js({"__proto__": {"injected": 1}, "a": 2})
        own = pyjs.to_py(pyjs.js.Object.getOwnPropertyNames(result))
        assert sorted(own) == ["__proto__", "a"]
        assert pyjs.code.run_js("(o) => o.injected")(result) is None

    def test_to_py_while_another_to_py_is_running(self):
        """a getter that itself converts something: the outer conversion
        is not disturbed"""
        obj = pyjs.code.run_js(
            """
            ({
                a: [1, 2],
                get b() {
                    const inner = pyjs.toPy(["inner", { deep: [1, 2, 3] }]);
                    inner.destroy();
                    return "b";
                },
                c: { d: "e" },
            })
            """
        )
        assert pyjs.to_py(obj) == {"a": [1, 2], "b": "b", "c": {"d": "e"}}

    def test_to_py_started_by_python_code_of_another_to_py(self):
        """the same from the Python side: while `to_py` builds a dict, the
        `__hash__` of a key converts something else"""

        class Key:
            def __hash__(self):
                assert pyjs.to_py(pyjs.code.run_js("[['inner', 1], {deep: [2, 3]}]")) == [["inner", 1], {"deep": [2, 3]}]
                return 1

            def __eq__(self, other):
                return self is other

        key = Key()
        # (roundtrip=False: read back from JavaScript it is `key` itself)
        proxy = pyjs.create_proxy(key, roundtrip=False)
        try:
            js_map = pyjs.js.Map.new()
            js_map.set(proxy, pyjs.code.run_js("[1, 2, 3]"))
            js_map.set("after", pyjs.code.run_js("({k: [4, 5], text: 'some text'})"))
            assert pyjs.to_py(js_map) == {key: [1, 2, 3], "after": {"k": [4, 5], "text": "some text"}}
        finally:
            proxy.destroy()


class TestNoLeaksOnErrors:
    def test_to_py_failing_half_way_releases_the_rest(self):
        """`to_py` of a Map whose key cannot be a dict key in Python (a plain
        object becomes a dict: unhashable). The conversion stops there; the
        JavaScript objects written after that key (here functions, which
        Python would get as proxies) must be given back, not leak."""
        from helpers import handle_count

        bad = pyjs.code.run_js(
            """
            new Map([
                [{a: 1}, 1],
                ["f1", () => 1], ["f2", () => 2], ["f3", () => 3],
            ])
            """
        )
        before = handle_count()
        for _ in range(10):
            with pytest.raises(TypeError):
                pyjs.to_py(bad)
        assert handle_count() == before

    def test_long_buffers_on_every_arch(self):
        """C long items (4 bytes on wasm32, 8 on wasm64): the typed array is
        chosen by the real item size"""
        import ctypes

        longs = (ctypes.c_long * 3)(1, -2, 3)
        for result in [pyjs.to_js(longs), pyjs.buffer_to_js_typed_array(longs)]:
            assert result.BYTES_PER_ELEMENT == ctypes.sizeof(ctypes.c_long)
            assert [int(x) for x in result] == [1, -2, 3]


class TestBufferViews:
    def test_view_of_a_readonly_buffer_is_refused(self):
        """A view lets JavaScript write into Python's memory. For a read-only
        buffer (bytes: immutable, possibly shared, with a cached hash) that
        would change an object Python assumes never changes."""
        with pytest.raises(TypeError, match="read-only"):
            pyjs.buffer_to_js_typed_array(b"abc", view=True)
        with pytest.raises(TypeError, match="read-only"):
            pyjs.buffer_to_js_typed_array(memoryview(bytearray(b"abc")).toreadonly(), view=True)

    def test_copy_of_a_readonly_buffer_and_view_of_a_writable_one(self):
        assert list(pyjs.buffer_to_js_typed_array(b"abc")) == [97, 98, 99]
        data = bytearray(b"abc")
        view = pyjs.buffer_to_js_typed_array(data, view=True)
        view[0] = 65
        assert data == bytearray(b"Abc")

    def test_assign_from_bytes_still_works(self):
        """(JSBuffer.assign reads through such a view internally: fine)"""
        target = pyjs.js.Uint8Array.new(3)
        target.assign(b"xyz")
        assert bytes(target.to_bytes()) == b"xyz"


class TestBuffersWithOptions:
    def test_unaligned_buffer(self):
        """a buffer of 8 byte items that does not start at a multiple of 8
        in memory: JavaScript cannot make a Float64Array on it directly"""
        import struct

        raw = bytearray(1) + bytearray(struct.pack("3d", 1.5, 2.5, 3.5))
        unaligned = memoryview(raw)[1:].cast("d")
        for result in [pyjs.to_js(unaligned), pyjs.buffer_to_js_typed_array(unaligned)]:
            assert result.constructor.name == "Float64Array"
            assert list(result) == [1.5, 2.5, 3.5]

    def test_buffer_without_a_typed_array_with_an_option(self):
        """float16 has no typed array class: a TypeError, also on the step
        by step path (it used to recurse until RecursionError)"""
        import array
        import struct

        half_floats = memoryview(bytearray(struct.pack("2e", 1.0, 2.0))).cast("e")
        with pytest.raises(TypeError):
            pyjs.to_js(half_floats)
        with pytest.raises(TypeError):
            pyjs.to_js(half_floats, pyproxies=pyjs.js.Array.new())
        # (one that has a typed array works with the option)
        ints = array.array("i", [1, 2, 3])
        assert list(pyjs.to_js(ints, pyproxies=pyjs.js.Array.new())) == [1, 2, 3]

    def test_to_py_converter_and_a_stored_proxy(self):
        """`to_py` with a converter, of a JavaScript Array holding a proxy
        of a Python dict (create_proxy): the dict itself, not a dict of the
        proxy's internals"""
        data = {"x": 1}
        proxy = pyjs.create_proxy(data)
        try:
            array = pyjs.js.Array.new()
            array.push(proxy)
            result = pyjs.to_py(array, default_converter=lambda obj, convert, cache: "converted")
            assert len(result) == 1
            item = result[0]
            item = item.unwrap() if hasattr(item, "unwrap") else item
            assert item is data
        finally:
            proxy.destroy()
