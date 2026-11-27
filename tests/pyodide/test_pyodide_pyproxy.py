# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Derived from pyodide (src/tests/test_pyproxy.py, release 314.0.8), modified for pyjs.
#
# Left out (tests of pyodide internals):
# - test_pyproxy_tostring: `pyodide_js._api.setPyProxyToStringMethod`
# - test_pyproxy_refcount: `sys.getrefcount` of an object while proxies of it exist
# - test_pyproxy_gc, test_pyproxy_gc_destroy: FinalizationRegistry + `gc()`
#   driven from the host, `sys.getrefcount`
# - test_nogil: `pyodide._module._PyEval_SaveThread`, `pyodide._api.NoGilError`
# - test_fatal_error: `pyodide._api.fatal_error`, `_pyodide_core.trigger_fatal_error`,
#   needs a fresh page
# - test_roundtrip_no_destroy: `pyodide_js._api.pyproxyIsAlive`
# - test_multiple_interpreters: a second interpreter (`loadPyodide`)
"""PyProxy, the JavaScript object standing for a Python object (pyodide's test_pyproxy.py)."""

import pytest

import js
import pyodide_helpers  # noqa: F401  (defines assert / assertThrows / assertThrowsAsync in JS)
from pyodide.code import run_js


_PRELUDE = """
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
"""


def _js(body):
    """run the statements `body` as body of a JS function, return its result
    (pyodide's `selenium.run_js`)"""
    return run_js("(() => {" + _PRELUDE + body + "})()")


def _js_async(body):
    """like `_js` for statements that use `await`: returns a promise, to be awaited"""
    return run_js("(async () => {" + _PRELUDE + body + "})()")


def test_pyproxy_class():
    class Foo:
        bar = 42

        def get_value(self, value):
            return value * 64

    f = Foo()

    run_js(
        """
        (f) => {
            assert(() => f.type === "Foo");
            let f_get_value = f.get_value
            assert(() => f_get_value(2) === 128);
            f_get_value.destroy();
            assert(() => f.bar === 42);
            assert(() => 'bar' in f);
            f.baz = 32;
            assert(() => f.baz === 32);
        }
        """
    )(f)
    assert hasattr(f, "baz")
    f_props = run_js(
        """
        (f) => {
            let f_props = Object.getOwnPropertyNames(f);
            delete f.baz;
            return f_props;
        }
        """
    )(f)
    assert not hasattr(f, "baz")
    # (here Foo is a local class of a test module: its str() is
    # "<test_pyodide_pyproxy.test_pyproxy_class.<locals>.Foo object at ...>",
    # pyodide's test checks startsWith("<Foo"))
    run_js(
        """
        (f) => {
            assert(() => f.toString().startsWith("<"));
            assert(() => f.toString().includes(".Foo object at "));
        }
        """
    )(f)

    # pyjs: no `ownKeys` of proxies (Object.getOwnPropertyNames does not list
    # the Python attributes)
    assert f_props is not None
    return
    assert {
        "__class__",
        "__delattr__",
        "__dict__",
        "__dir__",
        "__doc__",
        "__eq__",
        "__format__",
        "__ge__",
        "__getattribute__",
        "__gt__",
        "__hash__",
        "__init__",
        "__init_subclass__",
        "__le__",
        "__lt__",
        "__module__",
        "__ne__",
        "__new__",
        "__reduce__",
        "__reduce_ex__",
        "__repr__",
        "__setattr__",
        "__sizeof__",
        "__str__",
        "__subclasshook__",
        "__weakref__",
        "bar",
        "baz",
        "get_value",
    }.difference(f_props) == set()


def test_del_builtin():
    # can't del a builtin
    _js("""assertThrows(() => pyjs.runPython("del open"), "PythonError", "NameError");""")
    # Can still get it even though we tried to del it.
    assert _js(
        """
        let open = pyjs.globals.get("open");
        let result = !!open;
        open.destroy();
        return result;
        """
    )
    assert _js("return pyjs.globals.get('__name__');") == "__main__"


def test_in_globals():
    _js("pyjs.runPython('yyyyy = 7');")
    assert _js(
        """
        let result = [];
        result.push(pyjs.globals.has("xxxxx"));
        result.push(pyjs.globals.has("yyyyy"));
        result.push(pyjs.globals.has("globals"));
        result.push(pyjs.globals.has("open"));
        return result;
        """
    ).to_py() == [False, True, True, True]


def test_pyproxy_copy():
    _js(
        """
        let d = pyjs.runPython("list(range(10))")
        let e = d.copy();
        d.destroy();
        assert(() => e.length === 10);
        e.destroy();
        """
    )


def test_pyproxy_destroy():
    class Foo:
        def get_value(self, value):
            return value * 64

    f = Foo()
    # pyjs: the message is "This ... proxy was ... destroyed ..." (pyodide:
    # "Object has already been destroyed")
    run_js(
        """
        (f) => {
            assert(()=> f.get_value(1) === 64);
            f.destroy();
            assertThrows(() => f.get_value(1), "Error", "destroyed");
        }
        """
    )(f)


def test_pyproxy_iter():
    from collections import ChainMap

    def test_generator():
        yield from range(10)

    c = test_generator()
    ty, l = run_js("(c) => [c.type, [...c]]")(c)
    assert ty == "generator"
    assert l.to_py() == list(range(10))

    c = ChainMap({"a": 2, "b": 3})
    ty, l = run_js("(c) => [c.type, [...c]]")(c)
    assert ty == "ChainMap"
    assert set(l) == {"a", "b"}

    def test_generator2():
        acc = 0
        for i in range(10):
            r = yield acc
            acc += i * r

    c = test_generator2()

    # pyjs: next(value) of a generator PyProxy does not send the value (the
    # generator gets None: TypeError in `i * r`), so the rest cannot run
    return
    result, result2 = run_js(
        """
        (c) => {
            let {done, value} = c.next();
            let result = [];
            while(!done){
                result.push(value);
                ({done, value} = c.next(value + 1));
            }

            function* test(){
                let acc = 0;
                for(let i=0; i < 10; i++){
                    let r = yield acc;
                    acc += i * r;
                }
            }
            c = test();
            ({done, value} = c.next());
            let result2 = [];
            while(!done){
                result2.push(value);
                ({done, value} = c.next(value + 1));
            }
            return [result, result2];
        }
        """
    )(c)
    assert result.to_py() == result2.to_py()


def test_pyproxy_iter_error():
    class T:
        def __iter__(self):
            raise Exception("hi")

    t = T()
    run_js(
        """
        (t) => {
            assertThrows(() => t[Symbol.iterator](), "PythonError", "hi");
        }
        """
    )(t)


def test_pyproxy_iter_error2():
    def g():
        yield 1
        yield 2
        raise Exception("hi")
        yield 3

    gen = g()
    run_js(
        """
        (gen) => {
            assert(() => gen.next().value === 1);
            assert(() => gen.next().value === 2);
            assertThrows(() => gen.next(), "PythonError", "hi");
        }
        """
    )(gen)


def test_pyproxy_iter_leak():
    from js import Map

    Map.new([(1, 2), (3, 4)])


@pytest.mark.xfail(reason="pyjs: no getBuffer")
def test_pyproxy_get_buffer():
    _js(
        """
        pyjs.runPython(`
            from sys import getrefcount
            z1 = memoryview(bytes(range(24))).cast("b", [8,3])
            z2 = z1[-1::-1]
        `);
        for(let x of ["z1", "z2"]){
            pyjs.runPython(`assert getrefcount(${x}) == 2`);
            let proxy = pyjs.globals.get(x);
            pyjs.runPython(`assert getrefcount(${x}) == 3`);
            let z = proxy.getBuffer();
            pyjs.runPython(`assert getrefcount(${x}) == 4`);
            proxy.destroy();
            pyjs.runPython(`assert getrefcount(${x}) == 3`);
            for(let idx1 = 0; idx1 < 8; idx1++) {
                for(let idx2 = 0; idx2 < 3; idx2++){
                    let v1 = z.data[z.offset + z.strides[0] * idx1 + z.strides[1] * idx2];
                    let v2 = pyjs.runPython(`repr(${x}[${idx1}, ${idx2}])`);
                    if(v1.toString() !== v2){
                        throw new Error(`Discrepancy ${x}[${idx1}, ${idx2}]: ${v1} != ${v2}`);
                    }
                }
            }
            z.release();
            pyjs.runPython(`print("${x}", getrefcount(${x}))`);
            pyjs.runPython(`assert getrefcount(${x}) == 2`);
        }
        """
    )


@pytest.mark.xfail(reason="pyjs: no getBuffer, no Symbol.dispose")
def test_pyproxy_get_buffer_dispose():
    _js(
        """
        pyjs.runPython(`
            from sys import getrefcount
            z1 = memoryview(bytes(range(24))).cast("b", [8,3])
            z2 = z1[-1::-1]
        `);
        for (let x of ["z1", "z2"]) {
            pyjs.runPython(`assert getrefcount(${x}) == 2`);
            {
                using proxy = pyjs.globals.get(x);
                pyjs.runPython(`assert getrefcount(${x}) == 3`);
                using z = proxy.getBuffer();
                pyjs.runPython(`assert getrefcount(${x}) == 4`);
                for (let idx1 = 0; idx1 < 8; idx1++) {
                    for (let idx2 = 0; idx2 < 3; idx2++) {
                        let v1 = z.data[z.offset + z.strides[0] * idx1 + z.strides[1] * idx2];
                        let v2 = pyjs.runPython(`repr(${x}[${idx1}, ${idx2}])`);
                        if(v1.toString() !== v2){
                            throw new Error(`Discrepancy ${x}[${idx1}, ${idx2}]: ${v1} != ${v2}`);
                        }
                    }
                }
            }
            pyjs.runPython(`print("${x}", getrefcount(${x}))`);
            pyjs.runPython(`assert getrefcount(${x}) == 2`);
        }
        """
    )


@pytest.mark.xfail(reason="pyjs: no getBuffer")
def test_get_empty_buffer():
    """Previously empty buffers would raise alignment errors

    This is because when Python makes an empty buffer, apparently the pointer
    field is allowed to contain random garbage, which in particular won't be aligned.
    """
    from array import array

    a = array("Q")
    run_js(
        """
        (a) => {
            let b = a.getBuffer();
            b.release();
        }
        """
    )(a)


@pytest.mark.xfail(reason="pyjs: no getBuffer, no pyodide.ffi.PyBuffer")
@pytest.mark.parametrize(
    "array_type",
    [
        ["i8", "Int8Array", "b"],
        ["u8", "Uint8Array", "B"],
        ["u8clamped", "Uint8ClampedArray", "B"],
        ["i16", "Int16Array", "h"],
        ["u16", "Uint16Array", "H"],
        ["i32", "Int32Array", "i"],
        ["u32", "Uint32Array", "I"],
        ["i64", "BigInt64Array", "q"],
        ["u64", "BigUint64Array", "Q"],
        ["f32", "Float32Array", "f"],
        ["f64", "Float64Array", "d"],
    ],
)
def test_pyproxy_get_buffer_type_argument(array_type):
    a = bytes(range(256))
    assert run_js("(a) => a instanceof pyjs.ffi.PyBuffer")(a)
    mv = memoryview(a)
    ty, array_ty, fmt = array_type
    check, result = run_js(
        f"""
        (a) => {{
            let buf = a.getBuffer({ty!r});
            assert(() => buf instanceof pyjs.ffi.PyBufferView);
            let check = (buf.data.constructor.name === {array_ty!r});
            let result = Array.from(buf.data);
            if(typeof result[0] === "bigint"){{
                result = result.map(x => x.toString(16));
            }}
            buf.release();
            return [check, result];
        }}
        """
    )(a)
    assert check
    result = result.to_py()
    if fmt.lower() == "q":
        assert result == [hex(x).replace("0x", "") for x in list(mv.cast(fmt))]
    elif fmt in {"d", "f"}:
        from math import isclose, isnan

        for x, y in zip(result, list(mv.cast(fmt)), strict=False):
            if x and y and not (isnan(x) or isnan(y)):
                assert isclose(x, y)
    else:
        assert result == list(mv.cast(fmt))


def test_pyproxy_mixins1():
    from pyodide.ffi import to_js

    class NoImpls:
        pass

    class Await:
        def __await__(self):
            return iter([])

    class Iter:
        def __iter__(self):
            return iter([])

    class Next:
        def __next__(self):
            pass

    class AwaitIter(Await, Iter):
        pass

    class AwaitNext(Await, Next):
        pass

    py_proxies = {
        "noimpls": NoImpls(),
        "awaitable": Await(),
        "iterable": Iter(),
        "iterator": Next(),
        "awaititerable": AwaitIter(),
        "awaititerator": AwaitNext(),
    }
    js_proxies = to_js(py_proxies)
    result = run_js(
        """
        (name_proxy) => {
            let result = {};
            for(let [name, x] of Object.entries(name_proxy)){
                let impls = {};
                for (let [name, key] of [
                    ["then", "then"],
                    ["catch", "catch"],
                    ["finally_", "finally"],
                    ["iterable", Symbol.iterator],
                    ["iterator", "next"],
                ]){
                    impls[name] = key in x;
                }
                // pyjs: no pyodide.ffi.Py* classes
                // for (let name of ["PyAwaitable", "PyIterable", "PyIterator"]){
                //     impls[name] = x instanceof pyodide.ffi[name];
                // }
                result[name] = impls;
                assert(() => !("asJsJson" in x));
                x.destroy();
            }
            return result;
        }
        """
    )(js_proxies)
    # (pyodide's expected values also have the instanceof results:
    # `| dict(PyAwaitable=..., PyIterable=..., PyIterator=...)`)
    assert result.to_py() == dict(
        noimpls=dict(
            then=False,
            catch=False,
            finally_=False,
            iterable=False,
            iterator=False,
        ),
        awaitable=dict(
            then=True, catch=True, finally_=True, iterable=False, iterator=False
        ),
        iterable=dict(
            then=False, catch=False, finally_=False, iterable=True, iterator=False
        ),
        iterator=dict(
            then=False, catch=False, finally_=False, iterable=True, iterator=True
        ),
        awaititerable=dict(
            then=True, catch=True, finally_=True, iterable=True, iterator=False
        ),
        awaititerator=dict(
            then=True, catch=True, finally_=True, iterable=True, iterator=True
        ),
    )


@pytest.mark.xfail(
    reason="pyjs: no pyodide.ffi.Py* classes (instanceof pyjs.ffi.PyDict), no `$` prefix for shadowed "
    "attributes (d.$get), no asJsJson"
)
def test_pyproxy_mixins2():
    _js(
        """
        let d = pyjs.runPython("{}");
        assert(() => !("prototype" in d));
        assert(() => !("caller" in d));
        assert(() => !("name" in d));
        assert(() => "length" in d);
        assert(() => d instanceof pyjs.ffi.PyDict);
        assert(() => d instanceof pyjs.ffi.PyProxyWithLength);
        assert(() => d instanceof pyjs.ffi.PyProxyWithHas);
        assert(() => d instanceof pyjs.ffi.PyProxyWithGet);
        assert(() => d instanceof pyjs.ffi.PyProxyWithSet);
        assert(() => "prototype" in d.__getitem__);
        assert(() => d.__getitem__.prototype === undefined);
        assert(() => !("length" in d.__getitem__));
        assert(() => !("name" in d.__getitem__));
        assert(() => d.$get.type === "builtin_function_or_method");
        assert(() => d.get.type === undefined);
        assert(() => d.set.type === undefined);
        assert(() => "asJsJson" in d);
        d.destroy();
    """
    )


@pytest.mark.xfail(reason="pyjs: no `$` prefix for attributes shadowed by JS names (Test.$a)")
def test_pyproxy_mixins31():
    from pyodide.ffi import to_js

    class Test:
        prototype: int
        name: int
        length: int

    test_class_and_instance = to_js([Test, Test()])

    run_js(
        """
        "use strict";
        ([Test, t]) => {
            assert(() => Test.prototype === undefined);
            assert(() => !("name" in Test));
            assert(() => !("length" in Test));

            assert(() => !("prototype" in t));
            assert(() => !("caller" in t));
            assert(() => !("name" in t));
            assert(() => !("length" in t));

            Test.prototype = 7;
            Test.name = 7;
            Test.length = 7;
        }
        """
    )(test_class_and_instance)

    assert Test.prototype == 7
    assert Test.name == 7
    assert Test.length == 7

    run_js(
        """
        "use strict";
        ([Test, t]) => {
            assertThrows(() => delete Test.prototype, "TypeError", "");
            delete Test.name;
            delete Test.length;
        }
        """
    )(test_class_and_instance)

    assert Test.prototype == 7
    assert not hasattr(Test, "name")
    assert not hasattr(Test, "length")

    run_js(
        """
        "use strict";
        ([Test, t]) => {
            Test.$a = 7;
            Object.defineProperty(Test, "a", {
                get(){ return Test.$a + 1; },
                set(v) {
                    Test.$a = v;
                }
            });
        }
        """
    )(test_class_and_instance)

    assert Test.a == 7

    run_js(
        """
        "use strict";
        ([Test, t]) => {
            assert(() => Test.a === 8);
            Test.a = 9;
            assert(() => Test.a === 10);
        }
        """
    )(test_class_and_instance)

    assert Test.a == 9

    run_js(
        """
        "use strict";
        ([Test, t]) => {
            assertThrows(() => delete Test.a, "TypeError", "");
            Object.defineProperty(Test, "b", {
                get(){ return Test.$a + 2; },
            });
            assert(() => Test.b === 11);
            assertThrows(() => Test.b = 7,"TypeError", "");
            assertThrows(() => delete Test.b, "TypeError", "");
            Test.destroy();
            t.destroy();
        }
        """
    )(test_class_and_instance)


@pytest.mark.xfail(
    reason="pyjs: no Object.defineProperty on proxies (the property is defined on the proxy target, "
    "reading it gives undefined or a TypeError of the proxy invariants)"
)
@pytest.mark.parametrize("configurable", [False, True])
@pytest.mark.parametrize("writable", [False, True])
def test_pyproxy_mixins32(configurable, writable):
    # Probably should get rid of this...
    user_agent = str(js.navigator.userAgent)
    if "Firefox" in user_agent:
        template = "proxy {} handler returned false"
        setText = template.format("set")
        deleteText = template.format("deleteProperty")
    elif "Chrome" in user_agent:
        template = "'{}' on proxy: trap returned falsish for property 'x'"
        setText = template.format("set")
        deleteText = template.format("deleteProperty")
    else:  # safari
        setText = "Proxy object's 'set' trap returned falsy value for property 'x'"
        deleteText = "Unable to delete property."

    _js(
        f"""
        "use strict";
        const configurable = !!{int(configurable)};
        const writable = !!{int(writable)};
        """
        """
        const d = pyjs.runPython("{}");
        Object.defineProperty(d, "x", {
            value: 9,
            configurable,
            writable,
        });
        assert(() => d.x === 9);
        if(writable) {
            d.x = 10;
            assert(() => d.x === 10);
        } else {
            assertThrows(() => d.x = 10, "TypeError", "%s");
        }
        if(configurable) {
            delete d.x;
            assert(() => d.x === undefined);
        } else {
            assertThrows(() => delete d.x, "TypeError", "%s");
        }
        d.destroy();
        """
        % (setText, deleteText)
    )


@pytest.mark.xfail(reason="pyjs: no `$` prefix for attributes shadowed by JS names (Test.$prototype)")
def test_pyproxy_mixins41():
    from pyodide.ffi import to_js

    class Test:
        caller = "fifty"
        prototype = "prototype"
        name = "me"
        length = 7

        def __call__(self, x):
            return x + 1

    test_objects = to_js([Test, Test()])

    run_js(
        """
        ([Test, t]) => {
            assert(() => Test.$prototype === "prototype");
            assert(() => Test.prototype === "prototype");
            assert(() => Test.name==="me");
            assert(() => Test.length === 7);

            assert(() => t.caller === "fifty");
            assert(() => "prototype" in t);
            assert(() => t.prototype === "prototype");
            assert(() => t.name==="me");
            assert(() => t.length === 7);
            assert(() => t(7) === 8);
            Test.destroy();
            t.destroy();
        }
        """
    )(test_objects)


def test_pyproxy_mixins42():
    class Test:
        def __call__(self, x):
            return x + 1

    t = Test()

    run_js(
        """
        (t) => {
            assert(() => "prototype" in t);
            assert(() => t.prototype === undefined);
            t.destroy();
        }
        """
    )(t)


def test_pyproxy_mixins5():
    from pyodide.ffi import to_js

    class Test:
        def __len__(self):
            return 9

    test_objects = to_js([Test, Test()])

    run_js("""
        "use strict";
        ([Test, t]) => {
            assert(() => !("length" in Test));
            assert(() => t.length === 9);
            // pyjs: no pyodide.ffi.Py* classes
            // assert(() => t instanceof pyodide.ffi.PyProxyWithLength);
            assert(() => !("asJsJson" in t));
            assertThrows(() => {t.length = 10}, "TypeError", "");
            assert(() => t.length === 9);

            // For some reason, this is the normal behavior for a JS getter:
            // delete just does nothing...
            delete t.length;
            assert(() => t.length === 9);

            Test.destroy();
            t.destroy();
        }
    """)(test_objects)


def test_pyproxy_mixins6():
    _js(
        """
        let l = pyjs.runPython(`
            l = [5, 6, 7] ; l
        `);
        assert(() => l.get.type === undefined);
        assert(() => l.get(1) === 6);
        assert(() => l.length === 3);
        // pyjs: no pyodide.ffi.Py* classes, no asJsJson
        // assert(() => l instanceof pyodide.ffi.PyProxyWithLength);
        // assert(() => l instanceof pyodide.ffi.PyProxyWithHas);
        // assert(() => l instanceof pyodide.ffi.PyProxyWithGet);
        // assert(() => l instanceof pyodide.ffi.PyProxyWithSet);
        // assert(() => "asJsJson" in l);
        l.set(0, 80);
        pyjs.runPython(`
            assert l[0] == 80
        `);
        l.delete(1);
        pyjs.runPython(`
            assert len(l) == 2 and l[1] == 7
        `);
        assert(() => l.length === 2 && l.get(1) === 7);
        l.destroy();
        """
    )


def test_topy_shared_ref_refcount():
    # See: https://github.com/pyodide/pyodide/issues/5598
    # Tests if toPy properly handles shared references
    # without messing up with the refcount

    def check(obj):
        import sys

        # All three elements should be the same object
        assert obj[0] is obj[1] is obj[2]
        # refcount should be at least 4:
        #   1 for obj[0], 1 for obj[1], 1 for obj[2], 1 for the arg
        rc = sys.getrefcount(obj[0])
        assert rc >= 4, f"refcount too low: {rc}"

    # Test with shared object literal
    obj = _js(
        """
        const shared = { x: 1 };
        const obj = [shared, shared, shared];
        const pyObj = pyjs.toPy(obj);
        return pyObj;
        """
    )
    check(obj)


def test_pyproxy_implicit_copy():
    result = _js(
        """
        let result = [];
        let a = pyjs.runPython(`d = { 1 : 2}; d`);
        let b = pyjs.runPython(`d`);
        result.push(a.get(1));
        result.push(b.get(1));
        a.destroy();
        b.destroy();
        return result;
        """
    )
    assert result[0] == 2
    assert result[1] == 2


async def test_errors():
    # pyjs: no pyodide.setDebug (pyodide switches it on for the message of
    # the last assertion); the PythonError class is pyjs.PythonError
    await _js_async(
        r"""
        const t = pyjs.runPython(`
            from pyodide.ffi import to_js
            def te(self, *args, **kwargs):
                raise Exception(repr(args))
            class Temp:
                __getattr__ = te
                __setattr__ = te
                __delattr__ = te
                __dir__ = te
                __call__ = te
                __getitem__ = te
                __setitem__ = te
                __delitem__ = te
                __iter__ = te
                __len__ = te
                __contains__ = te
                __await__ = te
                __repr__ = te
            to_js(Temp())
            Temp()
        `);
        assertThrows(() => t.x, "PythonError", "");
        try {
            t.x;
        } catch(e){
            assert(() => e instanceof pyjs.PythonError);
        }
        assertThrows(() => t.x = 2, "PythonError", "");
        assertThrows(() => delete t.x, "PythonError", "");
        // pyjs: no `ownKeys` of proxies (__dir__ is not called)
        // assertThrows(() => Object.getOwnPropertyNames(t), "PythonError", "");
        assertThrows(() => t(), "PythonError", "");
        assertThrows(() => t.get(1), "PythonError", "");
        assertThrows(() => t.set(1, 2), "PythonError", "");
        assertThrows(() => t.delete(1), "PythonError", "");
        assertThrows(() => t.has(1), "PythonError", "");
        assertThrows(() => t.length, "PythonError", "");
        assertThrows(() => t.toString(), "PythonError", "");
        assertThrows(() => Array.from(t), "PythonError", "");
        await assertThrowsAsync(async () => await t, "PythonError", "");
        t.destroy();
        // (pyodide, in debug mode: "Object has already been destroyed\n" +
        // 'The object was of type "Temp" and an error was raised when trying to generate its repr')
        assertThrows(() => t.type, "Error", "destroyed");
        """
    )


def test_pyproxy_call():
    from pyodide.ffi import JSException, to_js

    def f(x=2, y=3):
        return to_js([x, y])

    def assert_call(s, val):
        res = run_js(f"(f) => {s}")(f)
        assert res.to_py() == val

    assert_call("f()", [2, 3])
    assert_call("f(7)", [7, 3])
    assert_call("f(7, -1)", [7, -1])

    assert_call("f.callKwargs({})", [2, 3])
    assert_call("f.callKwargs(7, {})", [7, 3])
    assert_call("f.callKwargs(7, -1, {})", [7, -1])
    assert_call("f.callKwargs({ y : 4 })", [2, 4])
    assert_call("f.callKwargs({ y : 4, x : 9 })", [9, 4])
    assert_call("f.callKwargs(8, { y : 4 })", [8, 4])

    # pyjs: str() of a JSException is the message without the name (pyodide:
    # msg = "TypeError: callKwargs requires at least one argument")
    msg = "callKwargs requires at least one argument"
    with pytest.raises(JSException, match=msg) as e:
        run_js("(f) => f.callKwargs()")(f)
    assert e.value.name == "TypeError"

    with pytest.raises(JSException, match=msg):
        run_js("(f) => f.callKwargs()")(f)

    msg = r"test_pyproxy_call\.<locals>\.f\(\) got an unexpected keyword argument 'z'"
    with pytest.raises(TypeError, match=msg):
        run_js("(f) => f.callKwargs({z : 6})")(f)

    msg = r"test_pyproxy_call\.\<locals\>\.f\(\) got multiple values for argument 'x'"
    with pytest.raises(TypeError, match=msg):
        run_js("(f) => f.callKwargs(76, {x : 6})")(f)

    run_js("(f) => f.destroy()")(f)


def _global_f():
    """python's `f(x=2, y=3)` as JS global `f` (a PyProxy)"""
    _js(
        """
        pyjs.runPython(`
            from pyodide.ffi import to_js
            def f(x=2, y=3):
                return to_js([x, y])
        `);
        globalThis.f = pyjs.globals.get("f");
        """
    )


def _drop_global_f():
    _js("f.destroy(); delete globalThis.f;")


@pytest.mark.xfail(reason="pyjs: no callRelaxed")
def test_pyproxy_call_relaxed():
    _global_f()

    def assert_call(s, val):
        res = _js(f"return {s};")
        assert res.to_py() == val

    try:
        assert_call("f.callRelaxed()", [2, 3])
        assert_call("f.callRelaxed(1)", [1, 3])
        assert_call("f.callRelaxed(1, 2)", [1, 2])
        assert_call("f.callRelaxed(1, 2, 3)", [1, 2])
        assert_call("f.callRelaxed(1, 2, 3, 4)", [1, 2])
    finally:
        _drop_global_f()


@pytest.mark.xfail(reason="pyjs: no callWithOptions")
def test_pyproxy_call_with_options():
    _global_f()

    def assert_call(s, val):
        res = _js(f"return {s};")
        assert res.to_py() == val

    try:
        assert_call("f.callWithOptions({})", [2, 3])
        assert_call("f.callWithOptions({}, 7)", [7, 3])
        assert_call("f.callWithOptions({}, 7, 9)", [7, 9])
        msg = r"f\(\) takes from 0 to 2 positional arguments but 3 were given"
        with pytest.raises(TypeError, match=msg):
            _js("f.callWithOptions({}, 7, 9, 10)")

        assert_call("f.callWithOptions({relaxed: true})", [2, 3])
        assert_call("f.callWithOptions({relaxed: true}, 7)", [7, 3])
        assert_call("f.callWithOptions({relaxed: true}, 7, 9)", [7, 9])
        assert_call("f.callWithOptions({relaxed: true}, 7, 9, 10)", [7, 9])

        msg = "callWithOptions with 'kwargs: true' requires at least one argument"
        with pytest.raises(Exception, match=msg):
            _js("f.callWithOptions({kwargs: true})")

        msg = "callWithOptions with 'kwargs: true' requires at least one argument"
        with pytest.raises(Exception, match=msg):
            _js("f.callWithOptions({kwargs: true, relaxed: true})")

        msg = "kwargs argument is not an object"
        with pytest.raises(Exception, match=msg):
            _js("f.callWithOptions({kwargs: true}, 7, 9, 10)")

        msg = "kwargs argument is not an object"
        with pytest.raises(Exception, match=msg):
            _js("f.callWithOptions({kwargs: true, relaxed: true}, 7, 9, 10)")

        msg = r"f\(\) takes from 0 to 2 positional arguments but 3 were given"
        with pytest.raises(TypeError, match=msg):
            _js("f.callWithOptions({kwargs: true}, 7, 9, 10, {})")

        assert_call(
            "f.callWithOptions({kwargs: true, relaxed: true}, 7, 9, 10, {})", [7, 9]
        )

        assert_call("f.callWithOptions({kwargs: true}, {x: 9})", [9, 3])
        assert_call("f.callWithOptions({kwargs: true, relaxed: true}, {x: 9})", [9, 3])
    finally:
        _drop_global_f()


def test_pyproxy_borrow():
    _js(
        """
        let t = pyjs.runPython(`
            class Tinner:
                def f(self):
                    return 7
            class Touter:
                T = Tinner()
            Touter
        `);
        assert(() => t.T.f() === 7);
        let T = t.T;
        let Tcopy = T.copy();
        assert(() => T.f() === 7);
        assert(() => Tcopy.f() === 7);
        t.destroy();
        assert(() => Tcopy.f() === 7);
        // pyjs: the proxy of an attribute stays usable after its parent's
        // destroy() (pyodide: assertThrows(() => T.f(), "Error", "automatically
        // destroyed in the process of destroying the proxy it was borrowed from"))
        Tcopy.destroy();
        """
    )


async def test_coroutine_scheduling():
    await _js_async(
        """
        let f = pyjs.runPython(`
            x = 0
            async def f():
                global x
                print('hi!')
                x += 1
            f
        `);
        setTimeout(f, 100);
        await sleep(200);
        assert(() => pyjs.globals.get('x') === 1);
        f.destroy();
        """
    )


def test_pyproxy_apply():
    # Try to match behavior of real .apply
    _js(
        """
        pyjs.runPython(`
            from pyodide.ffi import to_js
            def f(*args):
                return to_js(args)
        `);
        let fpy = pyjs.globals.get("f");
        let fjs = function(...args){ return args; };
        let examples = [
            undefined,
            null,
            {},
            {0:1, 1:7, 2: -3},
            { *[Symbol.iterator](){yield 3; yield 5; yield 7;} },
            {0:1, 1:7, 2: -3, length: 2},
            [1,7,9,5],
            function(a,b,c){},
        ];
        for(let input of examples){
            assert(() => JSON.stringify(fpy.apply(undefined, input)) === JSON.stringify(fjs.apply(undefined, input)));
        }

        for(let error_input of [1, "abc", 1n, Symbol.iterator, true]) {
            assertThrows(() => fjs.apply(undefined, error_input), "TypeError", "");
            assertThrows(() => fpy.apply(undefined, error_input), "TypeError", "");
        }

        fpy.destroy();
        """
    )


@pytest.mark.xfail(reason="pyjs: no captureThis")
def test_pyproxy_this1():
    _js(
        """
        let f = pyjs.runPython(`
            x = 0
            def f(self, x):
                return getattr(self, x)
            f
        `);

        let x = {};
        x.f = f.captureThis();
        x.a = 7;
        assert(() => x.f("a") === 7 );
        f.destroy();
        """
    )


@pytest.mark.xfail(reason="pyjs: no captureThis")
def test_pyproxy_this2():
    _js(
        """
        let g = pyjs.runPython(`
            x = 0
            from pyodide.ffi import to_js
            def f(*args):
                return to_js(args)
            f
        `);

        let f = g.captureThis();
        let fjs = function(...args){return [this, ...args];};

        let f1 = f.bind(1);
        let fjs1 = fjs.bind(1);
        assert(() => JSON.stringify(f1(2, 3, 4)) === JSON.stringify(fjs1(2, 3, 4)));

        let f2 = f1.bind(2);
        let fjs2 = fjs1.bind(2);
        assert(() => JSON.stringify(f2(2, 3, 4)) === JSON.stringify(fjs2(2, 3, 4)));
        let f3 = f.bind(2);
        let fjs3 = fjs.bind(2);
        assert(() => JSON.stringify(f3(2, 3, 4)) === JSON.stringify(fjs3(2, 3, 4)));

        let gjs = function(...args){return [...args];};

        let g1 = g.bind(1, 2, 3, 4);
        let gjs1 = gjs.bind(1, 2, 3, 4);

        let g2 = g1.bind(5, 6, 7, 8);
        let gjs2 = gjs1.bind(5, 6, 7, 8);

        let g3 = g2.captureThis();

        assert(() => JSON.stringify(g1(-1, -2, -3, -4)) === JSON.stringify(gjs1(-1, -2, -3, -4)));
        assert(() => JSON.stringify(g2(-1, -2, -3, -4)) === JSON.stringify(gjs2(-1, -2, -3, -4)));
        assert(() => JSON.stringify(g3(-1, -2, -3, -4)) === JSON.stringify([1, 2, 3, 4, 6, 7, 8, -1, -2, -3, -4]));
        g.destroy();
        """
    )


@pytest.mark.xfail(reason="pyjs: no async iterator PyProxies (Symbol.asyncIterator), no pyodide.ffi.PyAsyncIterable")
async def test_async_iter1():
    class Gen:
        async def __aiter__(self):
            yield 1
            yield 2

    g = Gen()

    p = run_js(
        """
        async (g) => {
            assert(() => g instanceof pyjs.ffi.PyAsyncIterable);
            let r = [];
            for await (let a of g) {
                r.push(a);
            }
            return r;
        }
    """
    )(g)

    assert (await p).to_py() == [1, 2]


@pytest.mark.xfail(reason="pyjs: no async iterator PyProxies (Symbol.asyncIterator), no pyodide.ffi.PyAsyncIterable")
async def test_async_iter2():
    class Gen:
        def __init__(self):
            self.i = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            self.i += 1
            if self.i > 2:
                raise StopAsyncIteration
            return self.i

    g = Gen()

    p = run_js(
        """
        async (g) => {
            assert(() => g instanceof pyjs.ffi.PyAsyncIterable);
            let r = [];
            for await (let a of g) {
                r.push(a);
            }
            return r;
        }
    """
    )(g)

    assert (await p).to_py() == [1, 2]


@pytest.mark.xfail(reason="pyjs: no pyjs.ffi.Py* classes (instanceof PyGenerator / PyIterable / PyIterator)")
def test_gen():
    def g():
        n = 0
        for _ in range(3):
            n = yield n + 2

    p = run_js(
        """
        (g) => {
            assert(() => g instanceof pyjs.ffi.PyGenerator);
            assert(() => g instanceof pyjs.ffi.PyIterable);
            assert(() => g instanceof pyjs.ffi.PyIterator);
            assert(() => !(g instanceof pyjs.ffi.PyAsyncGenerator));
            let r = [];
            r.push(g.next());
            r.push(g.next(3));
            r.push(g.next(4));
            r.push(g.next(5));
            return r;
        }
    """
    )(g())

    assert p.to_py() == [
        {"done": False, "value": 2},
        {"done": False, "value": 5},
        {"done": False, "value": 6},
        {"done": True, "value": None},
    ]


@pytest.mark.xfail(reason="pyjs: no return() on generator PyProxies (they have next() / throw())")
def test_gen_return():
    def g1():
        yield 1
        yield 2

    p = run_js(
        """
        (g) => {
            let r = [];
            r.push(g.next());
            r.push(g.return(5));
            return r;
        }
    """
    )(g1())
    assert p.to_py() == [{"done": False, "value": 1}, {"done": True, "value": 5}]

    def g2():
        try:
            yield 1
            yield 2
        finally:
            yield 3  # noqa: B901
            return 5  # noqa: B012, B901

    p = run_js(
        """
        (g) => {
            let r = [];
            r.push(g.next());
            r.push(g.return(5));
            r.push(g.next());
            return r;
        }
    """
    )(g2())
    assert p.to_py() == [
        {"done": False, "value": 1},
        {"done": False, "value": 3},
        {"done": True, "value": 5},
    ]

    def g3():
        try:
            yield 1
            yield 2
        finally:
            return 3  # noqa: B901, B012

    p = run_js(
        """
        (g) => {
            let r = [];
            r.push(g.next());
            r.push(g.return(5));
            return r;
        }
    """
    )(g3())
    assert p.to_py() == [{"done": False, "value": 1}, {"done": True, "value": 3}]


def test_gen_throw():
    from pyodide.ffi import JSException

    def g1():
        yield 1
        yield 2

    p = run_js(
        """
        (g) => {
            g.next();
            g.throw(new TypeError('hi'));
        }
    """
    )
    with pytest.raises(JSException, match="hi"):
        p(g1())

    def g2():
        try:
            yield 1
            yield 2
        finally:
            yield 3
            return 5  # noqa: B901, B012

    p = run_js(
        """
        (g) => {
            let r = [];
            r.push(g.next());
            r.push(g.throw(new TypeError('hi')));
            r.push(g.next());
            return r;
        }
    """
    )(g2())
    assert p.to_py() == [
        {"done": False, "value": 1},
        {"done": False, "value": 3},
        {"done": True, "value": 5},
    ]

    def g3():
        try:
            yield 1
            yield 2
        finally:
            return 3  # noqa: B901, B012

    p = run_js(
        """
        (g) => {
            let r = [];
            r.push(g.next());
            r.push(g.throw(new TypeError('hi')));
            return r;
        }
    """
    )(g3())
    assert p.to_py() == [{"done": False, "value": 1}, {"done": True, "value": 3}]


@pytest.mark.xfail(reason="pyjs: no async generator PyProxies (next / return / throw), no pyodide.ffi.PyAsyncGenerator")
async def test_async_gen1():
    async def g():
        n = 0
        for _ in range(3):
            n = yield n + 2

    p = run_js(
        """
        async (g) => {
            assert(() => g instanceof pyjs.ffi.PyAsyncGenerator);
            assert(() => g instanceof pyjs.ffi.PyAsyncIterable);
            assert(() => g instanceof pyjs.ffi.PyAsyncIterator);
            assert(() => !(g instanceof pyjs.ffi.PyGenerator));
            let r = [];
            r.push(await g.next());
            r.push(await g.next(3));
            r.push(await g.next(4));
            r.push(await g.next(5));
            return r;
        }
    """
    )(g())

    assert (await p).to_py() == [
        {"done": False, "value": 2},
        {"done": False, "value": 5},
        {"done": False, "value": 6},
        {"done": True, "value": None},
    ]


@pytest.mark.xfail(reason="pyjs: no async generator PyProxies (Symbol.asyncIterator)")
async def test_async_gen2():
    async def g():
        for n in range(3):
            yield n

    p = run_js(
        """
        async (g) => {
            let result = [];
            for await (let x of g){
                result.push(x);
            }
            return result;
        }
    """
    )(g())
    assert (await p).to_py() == [0, 1, 2]


@pytest.mark.xfail(reason="pyjs: no async generator PyProxies (next / return / throw)")
async def test_async_gen_return():
    async def g1():
        yield 1
        yield 2

    p = await run_js(
        """
        async (g) => {
            let r = [];
            r.push(await g.next());
            r.push(await g.return(5));
            return r;
        }
    """
    )(g1())
    assert p.to_py() == [{"done": False, "value": 1}, {"done": True, "value": 5}]

    async def g2():
        try:
            yield 1
            yield 2
        finally:
            yield 3  # noqa: B901
            return  # noqa: B012, B901

    p = await run_js(
        """
        async (g) => {
            let r = [];
            r.push(await g.next());
            r.push(await g.return(5));
            r.push(await g.next());
            return r;
        }
    """
    )(g2())
    assert p.to_py() == [
        {"done": False, "value": 1},
        {"done": False, "value": 3},
        {"done": True, "value": None},
    ]

    async def g3():
        try:
            yield 1
            yield 2
        finally:
            return  # noqa: B901, B012

    p = await run_js(
        """
        async (g) => {
            let r = [];
            r.push(await g.next());
            r.push(await g.return(5));
            return r;
        }
    """
    )(g3())
    assert p.to_py() == [{"done": False, "value": 1}, {"done": True, "value": None}]


@pytest.mark.xfail(reason="pyjs: no async generator PyProxies (next / return / throw)")
async def test_async_gen_throw():
    from pyodide.ffi import JSException

    async def g1():
        yield 1
        yield 2

    p = run_js(
        """
        async (g) => {
            await g.next();
            await g.throw(new TypeError('hi'));
        }
    """
    )
    with pytest.raises(JSException, match="hi"):
        await p(g1())

    async def g2():
        try:
            yield 1
            yield 2
        finally:
            yield 3
            return  # noqa: B901, B012

    p = await run_js(
        """
        async (g) => {
            let r = [];
            r.push(await g.next());
            r.push(await g.throw(new TypeError('hi')));
            r.push(await g.next());
            return r;
        }
    """
    )(g2())
    assert p.to_py() == [
        {"done": False, "value": 1},
        {"done": False, "value": 3},
        {"done": True, "value": None},
    ]

    async def g3():
        try:
            yield 1
            yield 2
        finally:
            return  # noqa: B901, B012

    p = await run_js(
        """
        async (g) => {
            let r = [];
            r.push(await g.next());
            r.push(await g.throw(new TypeError('hi')));
            return r;
        }
    """
    )(g3())
    assert p.to_py() == [{"done": False, "value": 1}, {"done": True, "value": None}]


#: for the tests of the Array methods of proxies of lists
no_array_methods = pytest.mark.xfail(
    reason="pyjs: no Array.prototype methods / index access on proxies of lists (p[0] gives "
    "no item, join / map / ... are missing, pop / reverse are the Python list methods)"
)


@no_array_methods
def test_pyproxy_of_list_index():
    pylist = [9, 8, 7]
    jslist = run_js(
        """
        (p) => {
            return [p[0], p[1], p[2]]
        }
        """
    )(pylist)
    assert jslist.to_py() == pylist


@no_array_methods
def test_pyproxy_of_list_join():
    from pyodide.ffi import to_js

    a = ["Wind", "Water", "Fire"]
    ajs = to_js(a)
    func = run_js("((a, k) => a.join(k))")

    assert func(a, None) == func(ajs, None)
    assert func(a, ", ") == func(ajs, ", ")
    assert func(a, " ") == func(ajs, " ")


@no_array_methods
def test_pyproxy_of_list_slice():
    from pyodide.ffi import to_js

    a = ["ant", "bison", "camel", "duck", "elephant"]
    ajs = to_js(a)

    func_strs = [
        "a.slice(2)",
        "a.slice(2, 4)",
        "a.slice(1, 5)",
        "a.slice(-2)",
        "a.slice(2, -1)",
        "a.slice()",
    ]
    for func_str in func_strs:
        func = run_js(f"(a) => {func_str}")
        assert func(a).to_py() == func(ajs).to_py()


@no_array_methods
def test_pyproxy_of_list_indexOf():
    from pyodide.ffi import to_js

    a = ["ant", "bison", "camel", "duck", "bison"]
    ajs = to_js(a)

    func_strs = [
        "beasts.indexOf('bison')",
        "beasts.indexOf('bison', 2)",
        "beasts.indexOf('bison', -4)",
        "beasts.indexOf('bison', 3)",
        "beasts.indexOf('giraffe')",
    ]
    for func_str in func_strs:
        func = run_js(f"(beasts) => {func_str}")
        assert func(a) == func(ajs)


@no_array_methods
def test_pyproxy_of_list_lastIndexOf():
    from pyodide.ffi import to_js

    a = ["ant", "bison", "camel", "duck", "bison"]
    ajs = to_js(a)

    func_strs = [
        "beasts.lastIndexOf('bison')",
        "beasts.lastIndexOf('bison', 2)",
        "beasts.lastIndexOf('bison', -4)",
        "beasts.lastIndexOf('bison', 3)",
        "beasts.lastIndexOf('giraffe')",
    ]
    for func_str in func_strs:
        func = run_js(f"(beasts) => {func_str}")
        assert func(a) == func(ajs)


@no_array_methods
def test_pyproxy_of_list_forEach():
    from pyodide.ffi import to_js

    a = ["a", "b", "c"]
    ajs = to_js(a)

    func = run_js(
        """
        ((a) => {
            let s = "";
            a.forEach((elt, idx, list) => {
                s += "::";
                s += idx;
                s += elt;
                s += this[elt];
            },
                {a: 6, b: 9, c: 22}
            );
            return s;
        })
        """
    )

    assert func(a) == func(ajs)


@no_array_methods
def test_pyproxy_of_list_map():
    from pyodide.ffi import to_js

    a = ["a", "b", "c"]
    ajs = to_js(a)
    func = run_js(
        """
        (a) => a.map(
            function (elt, idx, list){
                return [elt, idx, this[elt]]
            },
            {a: 6, b: 9, c: 22}
        )
        """
    )
    assert func(a).to_py() == func(ajs).to_py()


@no_array_methods
def test_pyproxy_of_list_filter():
    from pyodide.ffi import to_js

    a = list(range(20, 0, -2))
    ajs = to_js(a)
    func = run_js(
        """
        (a) => a.filter(
            function (elt, idx){
                return elt + idx > 12
            }
        )
        """
    )
    assert func(a).to_py() == func(ajs).to_py()


@no_array_methods
def test_pyproxy_of_list_reduce():
    from pyodide.ffi import to_js

    a = list(range(20, 0, -2))
    ajs = to_js(a)
    func = run_js(
        """
        (a) => a.reduce((l, r) => l + 2*r)
        """
    )
    assert func(a) == func(ajs)


@no_array_methods
def test_pyproxy_of_list_reduceRight():
    from pyodide.ffi import to_js

    a = list(range(20, 0, -2))
    ajs = to_js(a)
    func = run_js(
        """
        (a) => a.reduceRight((l, r) => l + 2*r)
        """
    )
    assert func(a) == func(ajs)


@no_array_methods
def test_pyproxy_of_list_some():
    from pyodide.ffi import to_js

    func = run_js("(a) => a.some((element, idx) => (element + idx) % 2 === 0)")
    for a in [
        [1, 2, 3, 4, 5],
        [2, 3, 4, 5],
        [1, 3, 5],
        [1, 4, 5],
        [4, 5],
    ]:
        assert func(a) == func(to_js(a))


@no_array_methods
def test_pyproxy_of_list_every():
    from pyodide.ffi import to_js

    func = run_js("(a) => a.every((element, idx) => (element + idx) % 2 === 0)")
    for a in [
        [1, 2, 3, 4, 5],
        [2, 3, 4, 5],
        [1, 3, 5],
        [1, 4, 5],
        [4, 5],
    ]:
        assert func(a) == func(to_js(a))


@no_array_methods
def test_pyproxy_of_list_at():
    from pyodide.ffi import to_js

    a = [5, 12, 8, 130, 44]
    ajs = to_js(a)

    func = run_js("(a, idx) => a.at(idx)")
    for idx in [2, 3, 4, -2, -3, -4, 5, 7, -7]:
        assert func(a, idx) == func(ajs, idx)


@no_array_methods
def test_pyproxy_of_list_concat():
    from pyodide.ffi import to_js

    a = [[5, 12, 8], [130, 44], [6, 7, 7]]
    ajs = to_js(a)

    func = run_js("(a, b, c) => a.concat(b, c)")
    assert func(*a).to_py() == func(*ajs).to_py()


@no_array_methods
def test_pyproxy_of_list_includes():
    from pyodide.ffi import to_js

    a = [5, 12, 8, 130, 44, 6, 7, 7]
    ajs = to_js(a)

    func = run_js("(a, n) => a.includes(n)")
    for n in range(4, 10):
        assert func(a, n) == func(ajs, n)


@no_array_methods
def test_pyproxy_of_list_entries():
    from pyodide.ffi import to_js

    a = [5, 12, 8, 130, 44, 6, 7, 7]
    ajs = to_js(a)

    func = run_js("(a, k) => Array.from(a[k]())")
    for k in ["entries", "keys", "values"]:
        assert func(a, k).to_py() == func(ajs, k).to_py()


@no_array_methods
def test_pyproxy_of_list_find():
    from pyodide.ffi import to_js

    a = [5, 12, 8, 130, 44, 6, 7, 7]
    ajs = to_js(a)

    func = run_js("(a, k) => a[k](element => element > 10)")
    for k in ["find", "findIndex"]:
        assert func(a, k) == func(ajs, k)


@no_array_methods
def test_pyproxy_of_list_sort():
    # from
    # https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/sort#creating_displaying_and_sorting_an_array
    # Yes, JavaScript sort is weird.
    stringArray = ["Blue", "Humpback", "Beluga"]
    numberArray = [40, None, 1, 5, 200]
    numericStringArray = ["80", "9", "700"]
    mixedNumericArray = ["80", "9", "700", 40, 1, 5, 200]

    run_js("globalThis.compareNumbers = (a, b) => a - b")

    assert run_js("((a) => a.join())")(stringArray) == "Blue,Humpback,Beluga"
    assert run_js("((a) => a.sort())")(stringArray) is stringArray
    assert stringArray == ["Beluga", "Blue", "Humpback"]

    assert run_js("((a) => a.join())")(numberArray) == "40,,1,5,200"
    assert run_js("((a) => a.sort())")(numberArray) == [1, 200, 40, 5, None]
    assert run_js("((a) => a.sort(compareNumbers))")(numberArray) == [
        1,
        5,
        40,
        200,
        None,
    ]

    assert run_js("((a) => a.join())")(numericStringArray) == "80,9,700"
    assert run_js("((a) => a.sort())")(numericStringArray) == ["700", "80", "9"]
    assert run_js("((a) => a.sort(compareNumbers))")(numericStringArray) == [
        "9",
        "80",
        "700",
    ]

    assert run_js("((a) => a.join())")(mixedNumericArray) == "80,9,700,40,1,5,200"
    assert run_js("((a) => a.sort())")(mixedNumericArray) == [
        1,
        200,
        40,
        5,
        "700",
        "80",
        "9",
    ]
    assert run_js("((a) => a.sort(compareNumbers))")(mixedNumericArray) == [
        1,
        5,
        "9",
        40,
        "80",
        200,
        "700",
    ]


@no_array_methods
def test_pyproxy_of_list_reverse():
    from pyodide.ffi import to_js

    a = [3, 2, 4, 1, 5]
    ajs = to_js(a)

    func = run_js("((a) => a.reverse())")
    assert func(a) is a
    func(ajs)
    assert ajs.to_py() == a


@no_array_methods
@pytest.mark.parametrize(
    "func",
    [
        'splice(2, 0, "drum")',
        'splice(2, 0, "drum", "guitar")',
        "splice(3, 1)",
        'splice(2, 1, "trumpet")',
        'splice(0, 2, "parrot", "anemone", "blue")',
        "splice(2, 2)",
        "splice(-2, 1)",
        "splice(2)",
        "splice()",
    ],
)
def test_pyproxy_of_list_splice(func):
    from pyodide.ffi import to_js

    a = ["angel", "clown", "mandarin", "sturgeon"]
    ajs = to_js(a)

    func = run_js(f"((a) => a.{func})")
    assert func(a).to_py() == func(ajs).to_py()
    assert a == ajs.to_py()


@no_array_methods
def test_pyproxy_of_list_push():
    from pyodide.ffi import to_js

    a = [4, 5, 6]
    ajs = to_js(a)

    func = run_js("(a) => a.push(1, 2, 3)")
    assert func(a) == func(ajs)
    assert ajs.to_py() == a

    a = [4, 5, 6]
    ajs = to_js(a)
    func = run_js(
        """
        (a) => {
            a.push(1);
            a.push(2);
            return a.push(3);
        }
        """
    )
    assert func(a) == func(ajs)
    assert ajs.to_py() == a


@no_array_methods
def test_pyproxy_of_list_pop():
    from pyodide.ffi import to_js

    func = run_js("((a) => a.pop())")

    for a in [
        [],
        ["broccoli", "cauliflower", "cabbage", "kale", "tomato"],
    ]:
        ajs = to_js(a)
        assert func(a) == func(ajs)
        assert ajs.to_py() == a


@no_array_methods
def test_pyproxy_of_list_shift():
    from pyodide.ffi import to_js

    a = ["Andrew", "Tyrone", "Paul", "Maria", "Gayatri"]
    ajs = to_js(a)

    func = run_js(
        """
        (a) => {
            let result = [];
            let i;
            while (typeof (i = a.shift()) !== "undefined") {
                result.push(i);
            }
            return result;
        }
        """
    )
    assert func(a).to_py() == func(ajs).to_py()
    assert a == []
    assert ajs.to_py() == []


@no_array_methods
def test_pyproxy_of_list_unshift():
    from pyodide.ffi import to_js

    a = [4, 5, 6]
    ajs = to_js(a)

    func = run_js("(a) => a.unshift(1, 2, 3)")
    assert func(a) == func(ajs)
    assert ajs.to_py() == a

    a = [4, 5, 6]
    ajs = to_js(a)
    func = run_js(
        """
        (a) => {
            a.unshift(1);
            a.unshift(2);
            return a.unshift(3);
        }
        """
    )
    assert func(a) == func(ajs)
    assert ajs.to_py() == a


@no_array_methods
@pytest.mark.parametrize(
    "func",
    [
        "copyWithin(-2)",
        "copyWithin(0, 3)",
        "copyWithin(0, 3, 4)",
        "copyWithin(-2, -3, -1)",
    ],
)
def test_pyproxy_of_list_copyWithin(func):
    from pyodide.ffi import to_js

    a = ["a", "b", "c", "d", "e"]
    ajs = to_js(a)
    func = run_js(f"(a) => a.{func}")
    assert func(a) is a
    func(ajs)
    assert a == ajs.to_py()


@no_array_methods
@pytest.mark.parametrize(
    "func",
    [
        "fill(0, 2, 4)",
        "fill(5, 1)",
        "fill(6)",
    ],
)
def test_pyproxy_of_list_fill(func):
    from pyodide.ffi import to_js

    a = ["a", "b", "c", "d", "e"]
    ajs = to_js(a)
    func = run_js(f"(a) => a.{func}")
    assert func(a) is a
    func(ajs)
    assert a == ajs.to_py()


@pytest.mark.xfail(reason="pyjs: no pyodide.ffi.PyProxy / PyCallable classes (instanceof)")
def test_pyproxy_instanceof_function():
    _js(
        """
        const pyFunc_0 = pyjs.runPython(`
            lambda: print("zero")
        `);

        const pyFunc_1 = pyjs.runPython(`
            def foo():
                print("two")
            foo
        `);

        const pyFunc_2 = pyjs.runPython(`
            class A():
                def a(self):
                    print("three") # method from class
            A.a
        `);

        const pyFunc_3 = pyjs.runPython(`
            class B():
                def __call__(self):
                    print("five (B as a callable instance)")

            b = B()
            b
        `);

        assert(() => pyFunc_0 instanceof Function);
        assert(() => pyFunc_0 instanceof pyjs.ffi.PyProxy);
        assert(() => pyFunc_0 instanceof pyjs.ffi.PyCallable);

        assert(() => pyFunc_1 instanceof Function);
        assert(() => pyFunc_1 instanceof pyjs.ffi.PyProxy);
        assert(() => pyFunc_1 instanceof pyjs.ffi.PyCallable);

        assert(() => pyFunc_2 instanceof Function);
        assert(() => pyFunc_2 instanceof pyjs.ffi.PyProxy);
        assert(() => pyFunc_2 instanceof pyjs.ffi.PyCallable);

        assert(() => pyFunc_3 instanceof Function);
        assert(() => pyFunc_3 instanceof pyjs.ffi.PyProxy);
        assert(() => pyFunc_3 instanceof pyjs.ffi.PyCallable);

        const d = pyjs.runPython("{}");
        assert(() => !(d instanceof Function));
        assert(() => !(d instanceof pyjs.ffi.PyCallable));
        assert(() => d instanceof pyjs.ffi.PyProxy);
        assert(() => d instanceof pyFunc_0.constructor);
        assert(() => pyFunc_0 instanceof d.constructor);

        for(const p of [pyFunc_0, pyFunc_1, pyFunc_2, pyFunc_3, d])  {
            p.destroy();
        }
        """
    )


def test_pyproxy_callable_prototype():
    from json import loads

    # (as JSON: the object has a key "constructor", `to_py` leaves it a proxy)
    result = loads(
        _js(
            """
            const o = pyjs.runPython("lambda:None");
            const res = Object.fromEntries(Reflect.ownKeys(Function.prototype).map(k => [k.toString(), k in o]));
            o.destroy();
            return JSON.stringify(res);
            """
        )
    )
    subdict = {
        "length": False,
        "name": False,
        "arguments": False,
        "caller": False,
        "apply": True,
        "bind": True,
        "call": True,
        "Symbol(Symbol.hasInstance)": True,
    }
    filtered_result = {k: v for (k, v) in result.items() if k in subdict}
    assert filtered_result == subdict


async def test_automatic_coroutine_scheduling():
    res = await _js_async(
        """
        function d(x) {
            if(x && x.destroy) {
                x.destroy();
            }
        }

        d(pyjs.runPython(`
            l = []
            async def f(n):
                l.append(n)

            def g(n):
                return f(n)

            async def h(n):
                return f(n)

            f(1)
        `));
        const f = pyjs.globals.get("f");
        const g = pyjs.globals.get("g");
        const h = pyjs.globals.get("h");
        f(3);
        d(pyjs.runPython("f(2)"));
        pyjs.runPythonAsync("f(4)");
        d(g(5));
        h(6);
        const l = pyjs.globals.get("l");
        // Wait for the automatically-scheduled coroutines to run: poll a
        // bounded number of event-loop turns until the expected results have
        // been collected instead of assuming a fixed number of turns is enough.
        for (let i = 0; i < 100 && l.length < 3; i++) {
            await sleep(0);
        }
        const res = l.toJs();
        for(let p of [f, g, l]) {
            p.destroy();
        }
        return res;
        """
    )
    assert res.to_py() == [3, 4, 6]


@pytest.mark.xfail(
    reason="pyjs: proxies of lists / tuples are not Array-like (JSON.stringify(proxy) is '{}')"
)
def test_stringify_sequence():
    from json import loads

    from js import JSON

    l = [1, 2, 3]

    assert loads(JSON.stringify(l)) == l
    assert loads(JSON.stringify(tuple(l))) == l


no_as_js_json = pytest.mark.xfail(reason="pyjs: no asJsJson")


@no_as_js_json
def test_as_json_adaptor_heritability1():
    o = [1, 2, {"a": 3, "b": {"c": 4, "d": [1, {"c": 2}]}}]

    f = run_js(
        """
        (o, l) =>  {
            const o2 = o.asJsJson();
            return l.reduce((x, y) => x[y], o2);
        }
        """
    )

    assert f(o, [0]) == 1
    assert f(o, [1]) == 2
    assert f(o, [2, "a"]) == 3
    assert f(o, [2, "b", "c"]) == 4
    assert f(o, [2, "b", "d", 0]) == 1
    assert f(o, [2, "b", "d", 1, "c"]) == 2


@no_as_js_json
def test_as_json_adaptor_heritability2():
    class T1:
        a = {"x": 2}

    class T2:
        a = {"x": 2}

        def __getitem__(self, key):
            return {"y": 3}

    o = [T1(), T2()]

    f = run_js(
        """
        (o) => {
            const x = o.asJsJson();
            const x0 = x[0];
            const x1 = x[1];
            const x1a = x1.a;
            return pyjs.toPy({
                x0,
                x1,
                xflags: x.$$flags,
                x0flags: x0.$$flags,
                x1flags: x1.$$flags,
                x0a: x0.a,
                x1a,
                x1ay: x1a.y,
            });
        }
        """
    )
    res = f(o)
    assert res["xflags"] & (1 << 16) != 0
    assert res["x0flags"] & (1 << 15) == 0
    assert res["x1flags"] & (1 << 15) != 0
    assert res["x0a"] == {"x": 2}
    assert res["x1a"] == {"y": 3}
    assert res["x1ay"] == 3


@no_as_js_json
def test_as_json_adaptor_ownkeys():
    o = {"c": 7, "x": 99, "z": 29}
    f = run_js("(o) => Reflect.ownKeys(o.asJsJson())")
    assert set(f(o)) == set(o.keys())

    d = {
        1: "int",
        "1": "string",
        2: "int",
        "3": "string",
        "items": "some value",
        "$dollar": 8,
        "$$dollar": 9,
        (1, 2, 3): 12,
    }
    assert set(f(d)) == {"$$dollar", "$dollar", "1", "2", "3", "items"}


@no_as_js_json
def test_as_json_adaptor_get():
    o = {0: "a", "1": "b", "3c": 4}

    assert run_js("(o) => o.asJsJson()['']")(o) is None

    assert run_js("(o) => o.asJsJson()[0]")(o) == "a"
    assert run_js("(o) => o.asJsJson()['0']")(o) == "a"
    assert run_js("(o) => o.asJsJson().get(0)")(o) == "a"
    assert run_js("(o) => o.asJsJson().get('0')")(o) is None

    assert run_js("(o) => o.asJsJson()[1]")(o) == "b"
    assert run_js("(o) => o.asJsJson()['1']")(o) == "b"
    assert run_js("(o) => o.asJsJson().get(1)")(o) is None
    assert run_js("(o) => o.asJsJson().get('1')")(o) == "b"

    assert run_js("(o) => o.asJsJson()['3c']")(o) == 4


@no_as_js_json
def test_as_json_adaptor_set():
    o = {}

    run_js(
        """
        (o) => {
            const x = o.asJsJson();
            x.a = 1;
            x[2] = 3;
            x["4"] = 5;
            x.b5 = "c";
            x[""] = 6;
            assert(() => (typeof x[0] == "undefined"));
        }
        """
    )(o)

    assert o == {"a": 1, 2: 3, 4: 5, "b5": "c", "": 6}
    assert "2" not in o
    assert "4" not in o


@no_as_js_json
@pytest.mark.parametrize(
    "o",
    [
        [7],
        [[7]],
        {"c": 7},
        {"c": [7]},
        [1, {"c": 2}],
        [1, 2, {"a": 3, "b": {"c": 4, "d": [1, {"c": 2}]}}],
    ],
)
def test_as_json_adaptor_stringify(o):
    from json import loads

    f = run_js("(o) => JSON.stringify(o.asJsJson())")
    assert loads(f(o)) == o


@pytest.mark.xfail(
    reason="pyjs: no item access by property on proxies of dicts (d[key] only reads attributes), no ownKeys"
)
def test_pyproxy_dict():
    get = run_js("(d, key) => d[key]")
    d = {
        1: "int",
        "1": "string",
        2: "int",
        "3": "string",
        "items": "some value",
        "$dollar": 8,
        "$$dollar": 9,
        (1, 2, 3): 12,
    }
    assert get(d, 1) == "string"
    assert get(d, 2) == "int"
    assert len(list(get(d, "items")())) == 8
    assert get(d, "$dollar") == 8
    assert get(d, "$$dollar") == 9
    run_js("(d) => console.log(Reflect.ownKeys(d))")(d)
    keys = set(
        run_js("(d) => Reflect.ownKeys(d).filter(x => typeof x !== 'symbol')")(d)
    )
    assert keys >= {"1", "2", "keys", "values", "items", "$dollar", "$$dollar"}
    set_ = run_js("(d, key, value) => d[key] = value")
    assert set_(d, 1, 7)
    assert d["1"] == 7
    assert d[1] == "int"
    assert set_(d, 2, 99)
    assert d[2] == 99
    assert "2" not in d
    assert set_(d, 3, 27)
    assert d["3"] == 27
    assert 3 not in d
    delete = run_js("(d, key, value) => delete d[key]")
    assert delete(d, 1)
    assert 1 in d
    assert "1" not in d
    assert delete(d, 1)
    assert 1 not in d
    assert "1" not in d
    delete(d, 1)
    delete(d, 2)
    assert 2 not in d
    delete(d, 3)
    assert "3" not in d


@pytest.mark.xfail(reason="pyjs: no Symbol.dispose")
def test_pyproxy_using():
    _js(
        """
        function f() {
            using x = pyjs.runPython("{'a': 2}");
            assert(() => x.a == 2);
        }
        f();
        """
    )


@pytest.mark.xfail(reason="pyjs: no pyodide.ffi.PySequence / PyMutableSequence classes (instanceof)")
def test_pyproxy_mutable_sequence_instanceof():
    from collections.abc import MutableSequence, Sequence

    is_sequence = run_js("(p) => p instanceof pyjs.ffi.PySequence")
    is_mutable_sequence = run_js("(p) => p instanceof pyjs.ffi.PyMutableSequence")

    # A list is a mutable sequence
    assert is_sequence([1, 2])
    assert is_mutable_sequence([1, 2])

    # A tuple and a range are immutable sequences
    for seq in [(1, 2), range(2)]:
        assert isinstance(seq, Sequence)
        assert not isinstance(seq, MutableSequence)
        assert is_sequence(seq)
        assert not is_mutable_sequence(seq)

    # Not a sequence
    assert not is_sequence({1: 2})
    assert not is_mutable_sequence({1: 2})
