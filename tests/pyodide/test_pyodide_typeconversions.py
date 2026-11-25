# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Derived from pyodide (src/tests/test_typeconversions.py, release 314.0.8), modified for pyjs.
#
# Left out (tests of pyodide internals):
# - test_python2js_with_depth: calls pyodide._module._python2js_with_depth / PyProxy_getPtr
# - test_tojs_literalmap: loadPyodide option `toJsLiteralMap` (needs a fresh interpreter)
# - test_buffer_format_string: calls pyodide._module.processBufferFormatString
# - test_converter_copy_refcount: refcounts of the converter objects of _pyodide_core
#
# Notes on the port:
# - The hypothesis tests (`@given`) run on fixed cases (their `@example`s plus
#   a few representative values), see the lists below.
# - Assertions on pyodide internals inside otherwise portable tests
#   (`_hiwire_num_refs`, `_api.pyproxyIsAlive`) are commented out with a
#   `# pyjs:` / `// pyjs:` note.

# See also test_pyproxy, test_jsproxy, and test_python.
import sys
from typing import Any

import pytest

import pyodide_helpers  # noqa: F401  (defines assert / assertThrows in JS)
from pyodide.code import run_js

# what hypothesis' `text()` stands for here (no lone surrogates: they cannot
# be encoded as utf-8)
TEXT_CASES = [
    "﻿",
    "",
    "ascii",
    "pyodid\xe9",
    "碘化物",
    "🐍",
    "a\x00b",
    "\U0010ffff￿\x7f",
]

# stands for `any_equal_to_self_strategy`
EQUAL_TO_SELF_CASES = [
    None,
    True,
    0,
    -7,
    2**70,
    1.5,
    float("inf"),
    "",
    "abc🐍",
    b"bytes",
    [1, "a", [2.5]],
    (1, 2),
    {"a": [1, 2], 3: None},
    {1, 2},
]

# stands for `any_strategy`
ANY_CASES = [
    *EQUAL_TO_SELF_CASES,
    float("nan"),
    complex(1, 2),
    object(),
    range(3),
    int,
    len,
    # (no tuple inside: a set item that becomes an Array is a
    # ConversionError, see test_tojs8)
    frozenset([1, "a", 2.5]),
    [{"a": {1, 2}}, (b"x", [None])],
]


@pytest.mark.parametrize("s", TEXT_CASES)
def test_string_conversion(s):
    sbytes = list(s.encode())

    from pyodide.code import run_js

    run_js("self.encoder = new TextEncoder()")
    run_js("self.decoder = new TextDecoder('utf8', {ignoreBOM: true})")

    spy = bytes(sbytes).decode()
    sjs = run_js(
        """
        (sbytes) => {
            self.sjs = self.decoder.decode(new Uint8Array(sbytes));
            return sjs;
        }
        """
    )(sbytes)
    assert sjs == spy
    assert run_js("(spy) => spy === self.sjs")(spy)


@pytest.mark.xfail(reason="pyjs: no PyProxy.getBuffer")
@pytest.mark.parametrize("s", TEXT_CASES)
def test_string_conversion2(s):
    from pyodide.code import run_js

    run_js("self.encoder = new TextEncoder()")
    run_js("self.decoder = new TextDecoder('utf8', {ignoreBOM: true})")

    s_encoded = s.encode()
    sjs = run_js(
        """
        (s_encoded) => {
            let buf = s_encoded.getBuffer();
            self.sjs = self.decoder.decode(buf.data);
            buf.release();
            return sjs
        }
        """
    )(s_encoded)
    assert sjs == s
    assert run_js("""(spy) => spy === self.sjs""")(s)


def blns():
    import base64
    import json
    from pathlib import Path

    with open(Path(__file__).parent / "blns.base64.json") as f:
        BLNS = json.load(f)
    for s in BLNS:
        yield base64.b64decode(s).decode(errors="ignore")


def test_string_conversion_blns():
    from pyodide.code import run_js
    from pyodide.ffi import to_js

    run_js("self.encoder = new TextEncoder()")
    run_js("self.decoder = new TextDecoder('utf8', {ignoreBOM: true})")

    # pyjs: no PyProxy.getBuffer: the bytes go to JS as Uint8Array (to_js)
    decode = run_js(
        """
        (s_encoded) => {
            self.sjs = self.decoder.decode(s_encoded);
            return sjs
        }
        """
    )
    same = run_js("""(spy) => spy === self.sjs""")

    # (all strings are checked before failing, so that the message lists
    # every string that does not survive)
    n = 0
    failed = []
    for s in blns():
        sjs = decode(to_js(s.encode()))
        if not (sjs == s and same(s)):
            failed.append(s)
        n += 1
    assert n > 100
    assert failed == []


def test_large_string_conversion():
    from pyodide.code import run_js

    longstr = run_js('"ab".repeat(200_000)')
    res = longstr.count("ab")
    assert res == 200_000
    run_js(
        """
        (s) => {
            assert(() => s.length === 40_000);
            for(let n = 0; n < 20_000; n++){
                assert(() => s.slice(2*n, 2*n+2) === "ab");
            }
        }
        """
    )("ab" * 20_000)


def test_js2python_string_codepoints():
    """JS string -> Python str conversion (js2python_string) must handle all
    three Python internal representations (UCS1/UCS2/UCS4) and decode UTF-16
    surrogate pairs into a single astral code point, while passing lone
    surrogates through as their bare code-unit value.
    """
    from pyodide.code import run_js

    # A JS string returned to Python is converted by js2python_string.
    js_string = run_js("(s) => s")

    # UCS1 (<= U+00FF), UCS2 (<= U+FFFF), UCS4 (astral / emoji).
    assert js_string("pyodidé") == "pyodidé"
    assert js_string("碘化物") == "碘化物"
    assert js_string("🐍") == "🐍"
    assert js_string("a😀b漢c") == "a😀b漢c"

    # A surrogate pair built from its two UTF-16 code units must decode to the
    # single astral code point, not two separate characters.
    pair = run_js("() => String.fromCharCode(0xD83D, 0xDE00)")()
    assert pair == "😀"
    assert len(pair) == 1
    assert ord(pair) == 0x1F600

    # Lone surrogates pass through as their bare code-unit value.
    lone_high = run_js("() => String.fromCharCode(0xD83D)")()
    assert len(lone_high) == 1
    assert ord(lone_high) == 0xD83D
    lone_low = run_js("() => String.fromCharCode(0xDE00)")()
    assert len(lone_low) == 1
    assert ord(lone_low) == 0xDE00

    # A high surrogate not followed by a low surrogate stays lone, and the
    # following character is preserved.
    mixed = run_js("() => String.fromCharCode(0xD83D, 0x0041)")()
    assert len(mixed) == 2
    assert ord(mixed[0]) == 0xD83D
    assert mixed[1] == "A"


def test_string_conversion_above_2gb():
    """Regression test for a Python str -> JS string conversion bug that
    fired only when the str's data buffer was allocated above the 2 GB WASM
    heap boundary.

    To trigger we (1) grow the heap past 2 GB and (2) fragment with small
    varied allocations until a fresh str data buffer lands above the
    boundary. UCS2 is forced by including a codepoint > U+00FF.
    """
    import gc

    from pyodide.code import run_js

    inspect = run_js(
        """
        (s) => {
            let nulCount = 0;
            for (let i = 0; i < s.length; i++) {
                if (s.charCodeAt(i) === 0) nulCount++;
            }
            return [s.length, nulCount];
        }
        """
    )

    def check(label):
        s = chr(0x0100) + "x" * 1023
        assert s.count("\x00") == 0, "source str corrupted on Python side"
        length, nul_count = inspect(s).to_py()
        assert length == len(s)
        assert nul_count == 0, (
            f"{label}: Python str -> JS string corruption "
            f"({nul_count}/{length} chars are U+0000); str buffer likely "
            "lives above 2 GB"
        )

    check("baseline (heap < 2 GB)")

    # Grow the heap past 2 GB.
    ballast = []
    for _ in range(21):
        try:
            ballast.append(bytes(100 * 1024 * 1024))
        except MemoryError:
            break
    check("after 2 GB ballast")

    # Fragment with small varied allocations until something lands above the
    # boundary. In practice the bug fires within ~15k iterations.
    small = []
    try:
        for i in range(20000):
            small.append(bytes(1000 + (i % 4000)))
            if i and i % 1000 == 0:
                check(f"during small allocs i={i}")
    finally:
        del small
        del ballast
        gc.collect()


@pytest.mark.parametrize(
    "n",
    [
        2**53,
        2**53 - 1,
        2**53 + 1,
        -(2**53),
        -(2**53) - 1,
        -(2**53) + 1,
        0,
        -1,
        2**64,
        1.5,
        -0.0,
        1e300,
        float("inf"),
        float("-inf"),
    ],
)
def test_number_conversions(n):
    import json

    from pyodide.code import run_js

    x_js = run_js("(s) => self.x_js = eval(s)")(json.dumps(n))
    run_js("(x_py) => Number(x_py) === x_js")(n)

    if isinstance(x_js, float):
        assert x_js == float(n)
    else:
        assert x_js == n


@pytest.mark.parametrize(
    "n",
    [
        0.0,
        -0.0,
        1.5,
        1e300,
        5e-324,
        2.0**53,
        2.0**53 - 1,
        -(2.0**53),
        float("inf"),
        float("-inf"),
        float("nan"),
    ],
)
def test_number_conversions_2(n):
    from pyodide.code import run_js

    assert run_js("(n) => typeof n")(n) == "number"
    from math import isinf, isnan

    if isnan(n):
        return
    import json

    n_js = run_js("(s) => eval(s)")(json.dumps(n))
    if not isinf(n) and float(int(n)) == n and -(2**53) < n < 2**53:
        assert isinstance(n_js, int)
    else:
        assert isinstance(n_js, float)


@pytest.mark.parametrize(
    "n",
    [
        2**53,
        2**53 - 1,
        2**53 + 1,
        -(2**53),
        -(2**53) - 1,
        -(2**53) + 1,
        0,
        -1,
        2**31,
        2**64,
        -(2**100),
    ],
)
def test_number_conversions_3(n):
    from pyodide.code import run_js

    jsty = run_js("(n) => typeof n")(n)
    if -(2**53) < n < 2**53:
        assert jsty == "number"
    else:
        assert jsty == "bigint"
    import json

    n_js = run_js("(s) => eval(s)")(json.dumps(n))
    if -(2**53) < n < 2**53:
        assert isinstance(n_js, int)
    else:
        assert isinstance(n_js, float)


def test_nan_conversions():
    from pyodide.code import run_js

    jsnan = run_js("NaN")
    from math import isnan

    assert isnan(jsnan)
    assert run_js(
        """
        let mathmod = pyjs.pyimport("math");
        const res = Number.isNaN(mathmod.nan);
        mathmod.destroy();
        res
        """
    )


@pytest.mark.parametrize(
    "n",
    [0, 1, -1, 2**53 - 1, 2**53, 2**53 + 1, -(2**53), 2**64, -(2**100), 12345678901234567890123],
)
def test_bigint_conversions1(n):
    h = hex(n)
    run_js(f"self.h = {h!r};")
    run_js(
        """
        (() => {
            let negative = false;
            let h2 = h;
            if(h2.startsWith('-')){
                h2 = h2.slice(1);
                negative = true;
            }
            self.n = BigInt(h2);
            if(negative){
                self.n = -n;
            }
            pyjs.runPython(`
from js import n, h
from pyodide.ffi import JSBigInt

assert isinstance(n, JSBigInt)
n2 = int(h, 16)
assert n == n2
            `);
            let n2 = pyjs.globals.get("n2");
            let n3 = Number(n2);
            let n4 = pyjs.globals.get("n");
            if(Number.isSafeInteger(n3)){
                assert(() => typeof n2 === "number");
                assert(() => n2 === Number(n));
            } else {
                assert(() => typeof n2 === "bigint");
                assert(() => n2 === n);
            }
            assert(() => typeof n4 === "bigint");
            assert(() => n4 === n);
        })()
        """
    )


@pytest.mark.parametrize(
    "n",
    [2**53 + 1, 2**53 + 2, 2**64, 2**200 + 12345, -(2**53) - 1, -(2**64), -(2**200) - 1],
)
def test_bigint_conversions2(n):
    import json

    from pyodide.code import run_js

    s = json.dumps(n)

    x_py = json.loads(s)
    x_js, check = run_js(
        """
        (s, x_py) => {
            let x_js = eval(s + 'n');

            return [x_js, x_py === x_js];
        }
        """
    )(s, x_py)
    assert check
    assert x_js == x_py


@pytest.mark.parametrize(
    "n, exp",
    [
        (0, 1),
        (5, 1),
        (1, 2),
        (-7, 2),
        (12345, 10),
        (-(2**60), 1),
        (2**32 - 1, 1),
        (2**32 + 17, 1),
        (2**70, 3),
    ],
)
def test_bigint_conversions3(n, exp):
    import json

    from pyodide.code import run_js
    from pyodide.ffi import JSBigInt

    val = 2 ** (32 * exp) - n
    s = json.dumps(val)

    x_py = json.loads(s)
    x_js = run_js(
        f"""
        self.x_js = eval('{s}n'); // JSON.parse apparently doesn't work
        """
    )
    [x1, x2] = run_js(
        """
        (x_py) => [x_py.toString(), x_js.toString()]
        """
    )(x_py)
    assert x1 == x2

    x_py_rt = run_js("(x) => x")(x_py)
    assert x_py_rt == x_py
    if x_py > 2**53:
        assert isinstance(x_py_rt, JSBigInt)
    else:
        assert isinstance(x_py_rt, int)

    check = run_js(
        """
        (x) => {
            const [a, b] = x.toJs();
            return a === b;
        }
        """
    )([str(x_js), str(x_py)])
    assert check


@pytest.mark.parametrize(
    "n, js_type",
    [
        (2**31, "number"),
        (-(2**31) - 1, "number"),
        (2**53 - 1, "number"),
        (-(2**53 - 1), "number"),
        (2**53, "bigint"),
        (-(2**53), "bigint"),
    ],
)
def test_python_int_to_js_safe_integer_bound(n, js_type):
    # Python ints that fit in a safe integer (Number.isSafeInteger) are
    # converted to a JS number, larger ones to a BigInt.
    from pyodide.code import run_js

    [result_type, result_str] = run_js("(x) => [typeof x, x.toString()]")(n)
    assert result_type == js_type
    assert result_str == str(n)


@pytest.mark.parametrize("obj", EQUAL_TO_SELF_CASES)
def test_hyp_py2js2py(obj):
    import __main__
    from pyodide.code import run_js

    __main__.obj = obj

    try:
        run_js('self.obj2 = pyjs.globals.get("obj"); 0;')
        from js import obj2  # type:ignore[attr-defined]

        assert obj2 == obj
        run_js(
            """
            if(self.obj2 && self.obj2.destroy){
                self.obj2.destroy();
            }
            delete self.obj2
            """
        )
    finally:
        del __main__.obj


@pytest.mark.parametrize("obj", EQUAL_TO_SELF_CASES)
def test_hyp_py2js2py_2(obj):
    import __main__
    from pyodide.code import run_js

    __main__.o = obj
    try:
        assert obj == run_js("pyjs.globals.get('o')")
    finally:
        del __main__.o


@pytest.mark.parametrize("a", [9992361673228537, -9992361673228537])
def test_big_integer_py2js2py(a):
    import __main__
    from pyodide.code import run_js

    __main__.a = a
    try:
        b = run_js("pyjs.globals.get('a')")
        assert a == b
    finally:
        del __main__.a


# Generate an object of any type
@pytest.mark.parametrize("obj", ANY_CASES)
def test_hyp_tojs_no_crash(obj):
    import __main__
    from pyodide.code import run_js

    __main__.x = obj
    try:
        run_js(
            """
            let x = pyjs.globals.get("x");
            if(x && x.toJs){
                x.toJs();
            }
            """
        )
    finally:
        del __main__.x


@pytest.mark.parametrize(
    "obj",
    [
        # length is too big to fit in ssize_t
        pytest.param(
            range(0, 2147483648),
            id="range(0, 2147483648)",
        ),
        *ANY_CASES,
    ],
)
def test_hypothesis(obj):
    from pyodide.ffi import to_js

    to_js(obj)


@pytest.mark.parametrize(
    "py,js",
    [
        (None, "undefined"),
        (True, "true"),
        (False, "false"),
        (42, "42"),
        (3.14, "3.14"),
        # Need to test all three internal string representations in Python:
        # UCS1, UCS2 and UCS4
        ("ascii", "'ascii'"),
        ("ιωδιούχο", "'ιωδιούχο'"),
        ("碘化物", "'碘化物'"),
        ("🐍", "'🐍'"),
    ],
)
def test_python2js1(py, js):
    from pyodide.code import run_js

    assert run_js(
        f"""
        (py) => py === {js}
        """
    )(py)


def test_python2js2():
    from pyodide.code import run_js

    assert list(
        run_js(
            """
                (x) => {
                    x = x.toJs();
                    return [x.constructor.name, x.length, x[0]];
                }
                """
        )(b"bytes")
    ) == ["Uint8Array", 5, 98]


def test_python2js3():
    from pyodide.code import run_js

    l = [7, 9, 13]
    result = run_js(
        """
        (proxy) => {
            x = proxy.toJs();
            return [proxy.type, x.constructor.name, x.length, x[0], x[1], x[2]]
        }
        """
    )(l)
    assert list(result) == ["list", "Array", 3, *l]


def test_python2js4():
    from pyodide.code import run_js

    assert list(
        run_js(
            """
                (proxy) => {
                    let typename = proxy.type;
                    let x = proxy.toJs();
                    return [proxy.type, x.constructor.name, x[42]];
                }
                """
        )({42: 64})
    ) == ["dict", "Object", 64]


def test_python2js5():
    from pyodide.code import run_js

    assert run_js("(x) => x.tell()")(open("/foo.txt", "wb")) == 0

    from tempfile import TemporaryFile

    with TemporaryFile(mode="w+") as f:
        contents = ["a\n", "b\n", "hello there!\n"]
        f.writelines(contents)
        assert run_js("(f) => f.tell()")(f) == 17

        assert (
            run_js(
                """
                (f) => {
                    f.seek(0);
                    return [f.readline(), f.readline(), f.readline()];
                }
                """
            )(f).to_py()
            == contents
        )


def test_python2js_track_proxies():
    run_js(
        """
        (() => {
            let x = pyjs.runPython(`
class T:
    pass
[[T()],[T()], [[[T()],[T()]],[T(), [], [[T()]], T()], T(), T()], T()]
            `);
            let proxies = [];
            let result = x.toJs({ pyproxies : proxies });
            assert(() => proxies.length === 10);
            for(let x of proxies){
                x.destroy();
            }
            // pyjs: the check that the proxies inside `result` are destroyed
            // is left out (pyodide.ffi.PyProxy / pyodide._api.pyproxyIsAlive)
            assertThrows(() => x.toJs({create_pyproxies : false}), "PythonError", "ConversionError");
            x.destroy();
        })()
        """
    )


def test_wrong_way_track_proxies():
    # pyjs: `checkDestroyed` (pyodide.ffi.PyProxy / pyodide._api.pyproxyIsAlive)
    # is left out
    from unittest import TestCase

    from js import Array, Object
    from pyodide.ffi import ConversionError, destroy_proxies, to_js

    raises = TestCase().assertRaises

    class T:
        pass

    x = [[T()], [T()], [[[T()], [T()]], [T(), [], [[T()]], T()], T(), T()], T()]
    proxylist = Array.new()
    r = to_js(x, pyproxies=proxylist)  # noqa: F841
    assert len(proxylist) == 10
    destroy_proxies(proxylist)
    with raises(TypeError):
        to_js(x, pyproxies=[])  # type:ignore[call-overload]
    with raises(TypeError):
        to_js(x, pyproxies=Object.new())
    with raises(ConversionError):
        to_js(x, create_pyproxies=False)


def test_wrong_way_conversions1():
    run_js(
        """
        (() => {
            assert(() => pyjs.toPy(5) === 5);
            assert(() => pyjs.toPy(5n) === 5n);
            assert(() => pyjs.toPy("abc") === "abc");
            class Test {};
            let t = new Test();
            assert(() => pyjs.toPy(t) === t);

            self.a1 = [1,2,3];
            self.b1 = pyjs.toPy(a1);
            self.a2 = { a : 1, b : 2, c : 3};
            self.b2 = pyjs.toPy(a2);
            pyjs.runPython(`
from js import a1, b1, a2, b2
assert a1.to_py() == b1
assert a2.to_py() == b2
            `);
            self.b1.destroy();
            self.b2.destroy();
        })()
        """
    )


def test_wrong_way_conversions2():
    from pyodide.code import run_js
    from pyodide.ffi import to_js

    [astr, bstr] = run_js(
        """
        (a) => {
            b = [1,2,3];
            return [JSON.stringify(a), JSON.stringify(b)]
        }
        """
    )(to_js([1, 2, 3]))
    assert astr == bstr


def test_wrong_way_conversions3():
    from pyodide.code import run_js
    from pyodide.ffi import to_js

    class Test:
        pass

    t1 = Test()
    t2 = to_js(t1)
    t3 = run_js("(t2) => t2.copy()")(t2)

    assert t1 is t3
    t2.destroy()


def test_wrong_way_conversions4():
    from pyodide.ffi import to_js

    s = "avafhjpa"
    t = 55
    assert to_js(s) is s
    assert to_js(t) is t


def test_dict_converter1():
    import json

    from pyodide.code import run_js
    from pyodide.ffi import to_js

    arrayFrom = run_js("Array.from")
    d = {x: x + 2 for x in range(5)}
    res = to_js(d, dict_converter=arrayFrom)
    constructor, serialized = run_js(
        """
        (res) => {
            return [res.constructor.name, JSON.stringify(res)];
        }
        """
    )(res)

    assert constructor == "Array"
    assert json.loads(serialized) == [list(x) for x in d.items()]


def test_dict_converter2():
    import json

    from pyodide.code import run_js

    d = {x: x + 2 for x in range(5)}
    constructor, serialized = run_js(
        """
        (d) => {
            const res = d.toJs({dict_converter : Array.from});
            return [res.constructor.name, JSON.stringify(res)];
        }
        """
    )(d)

    assert constructor == "Array"
    assert json.loads(serialized) == [list(x) for x in d.items()]


def test_dict_converter3():
    import json

    from js import Object
    from pyodide.code import run_js
    from pyodide.ffi import to_js

    d = {x: x + 2 for x in range(5)}

    res = to_js(d, dict_converter=Object.fromEntries)
    constructor, serialized = run_js(
        """
        (res) => [res.constructor.name, JSON.stringify(res)]
        """
    )(res)

    assert constructor == "Object"
    assert json.loads(serialized) == {str(k): v for k, v in d.items()}


def test_dict_converter4():
    import json

    from pyodide.code import run_js

    d = {x: x + 2 for x in range(5)}

    constructor, serialized = run_js(
        """
        (px) => {
            let res = px.toJs({dict_converter : Object.fromEntries});
            return [res.constructor.name, JSON.stringify(res)];
        }
        """
    )(d)

    assert constructor == "Object"
    assert json.loads(serialized) == {str(k): v for k, v in d.items()}


@pytest.mark.parametrize(
    "formula",
    ["2**30", "2**31", "2**30 - 1 + 2**30", "2**32 / 2**4", "-2**30", "-2**31"],
)
def test_python2js_long_ints(formula):
    assert run_js("(code) => pyjs.runPython(code)")(formula) == eval(formula)


def test_python2js_long_ints2():
    from pyodide.code import run_js

    assert run_js(
        """
        (x) => x === 2n**64n;
        """
    )(2**64)

    assert run_js(
        """
        (x) => x === -(2n**64n);
        """
    )(-(2**64))


def test_pythonexc2js():
    msg = "ZeroDivisionError"
    run_js("""(msg) => assertThrows(() => pyjs.runPython("5 / 0"), "PythonError", msg)""")(msg)


def test_js2python_null():
    from pyodide.code import run_js
    from pyodide.ffi import jsnull

    assert run_js("null") is jsnull
    assert run_js("[null]")[0] is jsnull
    assert run_js("() => null")() is jsnull
    assert run_js("({a: null})").a is jsnull
    assert run_js("new Map([['a', null]])")["a"] is jsnull
    assert run_js("[null, null, null]").to_py() == [jsnull, jsnull, jsnull]
    assert run_js("new Map([['a', null]])").to_py() == {"a": jsnull}


@pytest.mark.xfail(
    reason="pyjs differs: json.dumps(jsnull) gives 'null', but jsnull as a dict key "
    "raises TypeError (keys must be str, int, float, bool or None, not JSNull); "
    "pyodide gives the key 'null'"
)
def test_json_dumps_null():
    import json

    from pyodide.ffi import jsnull

    assert json.dumps(jsnull) == "null"
    assert (
        json.dumps([jsnull, jsnull, {jsnull: 1, 1: jsnull}])
        == '[null, null, {"null": 1, "1": null}]'
    )


def test_js2python_basic():
    from pyodide.code import run_js
    from pyodide.ffi import jsnull

    t = run_js(
        """
        ({
            jsstring_ucs1 : "pyodidé",
            jsstring_ucs2 : "碘化物",
            jsstring_ucs4 : "🐍",
            jsnumber0 : 42,
            jsnumber1 : 42.5,
            jsundefined : undefined,
            jsnull : null,
            jstrue : true,
            jsfalse : false,
            jsarray0 : [],
            jsarray1 : [1, 2, 3],
            jspython : pyjs.globals.get("open"),
            jsbytes : new Uint8Array([1, 2, 3]),
            jsfloats : new Float32Array([1, 2, 3]),
            jsobject : new TextDecoder(),
        });
        """
    )
    assert t.jsstring_ucs1 == "pyodidé"
    assert t.jsstring_ucs2 == "碘化物"
    assert t.jsstring_ucs4 == "🐍"
    assert t.jsnumber0 == 42 and isinstance(t.jsnumber0, int)
    assert t.jsnumber1 == 42.5 and isinstance(t.jsnumber1, float)
    assert t.jsundefined is None
    assert t.jsnull is jsnull
    assert t.jstrue is True
    assert t.jsfalse is False
    assert t.jspython is open

    jsbytes = t.jsbytes.to_py()
    assert (jsbytes.tolist() == [1, 2, 3]) and (jsbytes.tobytes() == b"\x01\x02\x03")

    jsfloats = t.jsfloats.to_py()
    import struct

    expected = struct.pack("fff", 1, 2, 3)
    assert (jsfloats.tolist() == [1, 2, 3]) and (jsfloats.tobytes() == expected)
    assert str(t.jsobject) == "[object TextDecoder]"
    assert bool(t.jsobject) is True
    assert bool(t.jsarray0) is False
    assert bool(t.jsarray1) is True
    run_js("(t) => t.jspython.destroy()")(t)


@pytest.mark.parametrize(
    "jsval, is_truthy",
    [
        ("()=>{}", True),
        ("new Map()", False),
        ("new Map([[0, 1]])", True),
        ("new Set()", False),
        ("new Set([0])", True),
    ],
)
def test_js2python_bool(jsval, is_truthy):
    from pyodide.code import run_js

    assert bool(run_js(jsval)) is is_truthy


@pytest.mark.parametrize(
    "jstype, pytype",
    (
        ("Int8Array", "b"),
        ("Uint8Array", "B"),
        ("Uint8ClampedArray", "B"),
        ("Int16Array", "h"),
        ("Uint16Array", "H"),
        ("Int32Array", "i"),
        ("Uint32Array", "I"),
        ("Float32Array", "f"),
        ("Float64Array", "d"),
    ),
)
def test_typed_arrays(jstype, pytype):
    from pyodide.code import run_js

    array = run_js(f"new {jstype}([1, 2, 3, 4]);").to_py()
    print(array.format, array.tolist(), array.tobytes())
    assert array.format == pytype
    assert array.tolist() == [1, 2, 3, 4]
    import struct

    assert array.tobytes() == struct.pack(pytype * 4, 1, 2, 3, 4)


def test_array_buffer():
    from pyodide.code import run_js

    array = run_js("new ArrayBuffer(100);").to_py()
    assert len(array.tobytes()) == 100


def assert_js_to_py_to_js(name):
    import __main__

    run_js(f"self.obj = {name};")
    exec("from js import obj", __main__.__dict__)
    assert run_js(
        """
        (() => {
            let pyobj = pyjs.globals.get("obj");
            return pyobj === obj;
        })()
        """
    )


def assert_py_to_js_to_py(name):
    run_js(
        f"""
        (() => {{
            self.obj = pyjs.runPython('{name}');
            pyjs.runPython(`
from js import obj
assert obj is {name}
            `);
            obj.destroy();
        }})()
        """
    )


def test_recursive_list_to_js():
    x: Any = []
    x.append(x)
    from pyodide.ffi import to_js

    to_js(x)


def test_recursive_dict_to_js():
    x: Any = {}
    x[0] = x
    from pyodide.ffi import to_js

    to_js(x)


def test_recursive_dict_in_list_to_js():
    # A list item that refers to a dict that is still being converted is filled
    # in at the end of the conversion. Check that it goes to the right index.
    from pyodide.code import run_js
    from pyodide.ffi import to_js

    x: Any = {}
    x["l"] = [x, 1]
    check = run_js(
        """
        (res) => {
            const l = res instanceof Map ? res.get("l") : res.l;
            return l.length === 2 && l[0] === res && l[1] === 1;
        }
        """
    )
    assert check(to_js(x))
    assert check(to_js(x, dict_converter=run_js("Object.fromEntries")))
    assert check(to_js(x, dict_converter=run_js("(entries) => new Map(entries)")))


def test_dict_subclass_to_js():
    """See issue #4636"""
    from collections import ChainMap

    from pyodide.code import run_js

    j = run_js(
        """
        (d) => JSON.stringify(d.toJs({ dict_converter: Object.fromEntries }))
        """
    )

    class D1(ChainMap, dict):  # type: ignore[misc, type-arg]
        pass

    class D2(dict, ChainMap):  # type: ignore[misc, type-arg]
        pass

    d = {"a": "b"}
    assert eval(j(D1({"a": "b"}))) == d
    assert eval(j(D2({"a": "b"}))) == d


def test_list_js2py2js():
    run_js("self.x = [1,2,3];")
    assert_js_to_py_to_js("x")


def test_dict_js2py2js():
    run_js("self.x = { a : 1, b : 2, 0 : 3 };")
    assert_js_to_py_to_js("x")


def test_error_js2py2js():
    run_js("self.err = new Error('hello there?');")
    assert_js_to_py_to_js("err")
    run_js("self.err = new DOMException('hello there?');")
    assert_js_to_py_to_js("err")


def test_error_py2js2py():
    import __main__

    __main__.err = Exception("hello there?")
    assert_py_to_js_to_py("err")


def test_list_py2js2py():
    import __main__

    __main__.x = ["a", "b"]
    assert_py_to_js_to_py("x")


def test_dict_py2js2py():
    import __main__

    __main__.x = {"a": 5, "b": 1}
    assert_py_to_js_to_py("x")


def test_jsproxy_attribute_error():
    import pytest

    from pyodide.code import run_js

    point = run_js(
        """
        class Point {
            constructor(x, y) {
                this.x = x;
                this.y = y;
            }
        }
        new Point(42, 43);
        """
    )
    assert point.y == 43

    with pytest.raises(AttributeError, match="z"):
        point.z  # noqa: B018

    del point.y
    with pytest.raises(AttributeError, match="y"):
        point.y  # noqa: B018

    assert run_js("(point) => point.y;")(point) is None


def test_javascript_error():
    msg = "JSException: Error: This is a js error"
    run_js(
        """
        (msg) => assertThrows(() => pyjs.runPython(`
from js import Error
err = Error.new("This is a js error")
err2 = Error.new("This is another js error")
raise err
        `), "PythonError", msg)
        """
    )(msg)


def test_javascript_error_back_to_js():
    from pyodide.code import run_js

    err = run_js('self.err = new Error("This is a js error"); err')
    assert type(err).__name__ == "JSException"
    assert run_js(
        """
        (py_err) => py_err === err;
        """
    )(err)


def test_memoryview_conversion():
    import __main__

    exec(
        """
import array
a = array.array("Q", [1,2,3])
b = array.array("u", "123")
""",
        __main__.__dict__,
    )
    run_js(
        """
        pyjs.runPython("a").destroy()
        // Implicit assertion: this doesn't leave python error indicator set
        """
    )

    run_js(
        """
        pyjs.runPython("b").destroy()
        // Implicit assertion: this doesn't leave python error indicator set
        """
    )


@pytest.mark.parametrize("shape", [[4], [3, 4], [2, 3, 4]])
def test_buffer_suboffsets_conversion(shape):
    pytest.importorskip("_testbuffer")
    from _testbuffer import ND_PIL, ndarray
    from math import prod

    from pyodide.code import run_js
    from pyodide.ffi import to_js

    nd = ndarray(list(range(prod(shape))), shape=shape, format="i", flags=ND_PIL)
    suboffsets = memoryview(nd).suboffsets
    assert suboffsets and suboffsets[0] >= 0

    to_list = run_js(
        """
        const toList = (x) =>
          ArrayBuffer.isView(x) ? Array.from(x) : Array.from(x, toList);
        toList
        """
    )
    assert to_list(to_js(nd)).to_py() == memoryview(nd).tolist()


@pytest.mark.parametrize("ty", [list, tuple])
def test_tojs1(ty):
    import json

    from pyodide.code import run_js

    l = [1, 2, 3]
    x = ty(l)
    assert run_js("x => Array.isArray(x.toJs())")(x)
    serialized = run_js("x => JSON.stringify(x.toJs())")(x)
    assert l == json.loads(serialized)


def test_tojs2():
    import json

    from pyodide.code import run_js

    o = [(1, 2), (3, 4), [5, 6], {"a": 1, 2: 3, 4: 9}]

    assert run_js("(o) => Array.isArray(o.toJs())")(o)
    serialized = run_js("(o) => JSON.stringify(o.toJs())")(o)
    assert json.loads(serialized) == [[1, 2], [3, 4], [5, 6], {"a": 1, "2": 3, "4": 9}]
    serialized = run_js(
        "(o) => JSON.stringify(Array.from(Object.entries(o.toJs()[3])))"
    )(o)
    assert sorted(json.loads(serialized)) == [["2", 3], ["4", 9], ["a", 1]]


def test_tojs4():
    run_js(
        """
        (() => {
            let a = pyjs.runPython("[1,[2,[3,[4,[5,[6,[7]]]]]]]")
            for(let i=0; i < 7; i++){
                let x = a.toJs({depth : i});
                for(let j=0; j < i; j++){
                    assert(() => Array.isArray(x), `i: ${i}, j: ${j}`);
                    x = x[1];
                }
                // pyjs: no pyjs.ffi.PyProxy class in JS
                // assert(() => x instanceof pyjs.ffi.PyProxy, `i: ${i}, j: ${i}`);
                assert(() => x.type === "list", `i: ${i}, j: ${i}`);
                x.destroy();
            }
            a.destroy()
        })()
        """
    )


def test_tojs5():
    run_js(
        """
        (() => {
            let a = pyjs.runPython("[1, (2, (3, [4, (5, (6, [7]))]))]")
            for(let i=0; i < 7; i++){
                let x = a.toJs({depth : i});
                for(let j=0; j < i; j++){
                    assert(() => Array.isArray(x), `i: ${i}, j: ${j}`);
                    x = x[1];
                }
                // pyjs: no pyjs.ffi.PyProxy class in JS
                // assert(() => x instanceof pyjs.ffi.PyProxy, `i: ${i}, j: ${i}`);
                assert(() => ["list", "tuple"].includes(x.type), `i: ${i}, j: ${i}`);
                x.destroy();
            }
            a.destroy()
        })()
        """
    )


def test_tojs6():
    from pyodide.code import run_js

    a = [1, 2, 3, 4, 5]
    b = [a, a, a, a, a]
    respy = [b, b, b, b, b]

    # pyjs: the assertion on pyodide._module._hiwire_num_refs() is left out
    run_js(
        """
        (respy) => {
            let res = respy.toJs();
            assert(() => res[0] === res[1]);
            assert(() => res[0][0] === res[1][1]);
            assert(() => res[4][0] === res[1][4]);
        }
        """
    )(respy)


def test_tojs7():
    from typing import Any

    from pyodide.code import run_js

    # Create complex recursive structure with mixed types
    a: list[Any] = [["b"]]
    b: list[Any] = [1, 2, 3, a[0]]
    a[0].append(b)
    a.append(b)
    respy = a

    # pyjs: the assertion on pyodide._module._hiwire_num_refs() is left out
    run_js(
        """
        (respy) => {
            let res = respy.toJs();
            assert(() => res[0][0] === "b");
            assert(() => res[1][2] === 3);
            assert(() => res[1][3] === res[0]);
            assert(() => res[0][1] === res[1]);
        }
        """
    )(respy)


def test_tojs8():
    import pytest

    from pyodide.ffi import ConversionError, to_js

    msg = r"Cannot use \(2, 2\) as a key for a Javascript"
    with pytest.raises(ConversionError, match=msg):
        to_js({(2, 2): 0})

    with pytest.raises(ConversionError, match=msg):
        to_js({(2, 2)})


def test_tojs9():
    import pytest

    from pyodide.code import run_js
    from pyodide.ffi import ConversionError, to_js

    result1 = to_js({1, "1"})
    assert set(run_js("(x) => Array.from(x.values())")(result1)) == {1, "1"}

    msg = "Key collision when converting Python dictionary to JavaScript. Key: '1'"
    with pytest.raises(ConversionError, match=msg):
        to_js({1: 7, "1": 9})


def test_to_py1():
    from pyodide.code import run_js

    a = run_js(
        """
        let a = new Map([[1, [1,2,new Set([1,2,3])]], [2, new Map([[1,2],[2,7]])]]);
        a.get(2).set("a", a);
        a;
        """
    )
    result = [repr(a.to_py(depth=i)) for i in range(4)]
    assert result == [
        "[object Map]",
        "{1: 1,2,[object Set], 2: [object Map]}",
        "{1: [1, 2, [object Set]], 2: {1: 2, 2: 7, 'a': [object Map]}}",
        "{1: [1, 2, {1, 2, 3}], 2: {1: 2, 2: 7, 'a': {...}}}",
    ]


def test_to_py2():
    from pyodide.code import run_js

    a = run_js(
        """
        let a = { "x" : 2, "y" : 7, "z" : [1,2] };
        a.z.push(a);
        a
        """
    )
    result = [repr(a.to_py(depth=i)) for i in range(4)]
    assert result == [
        "[object Object]",
        "{'x': 2, 'y': 7, 'z': 1,2,[object Object]}",
        "{'x': 2, 'y': 7, 'z': [1, 2, [object Object]]}",
        "{'x': 2, 'y': 7, 'z': [1, 2, {...}]}",
    ]


def test_to_py3():
    from pyodide.code import run_js

    a = run_js(
        """
        class Temp {
            constructor(){
                this.x = 2;
                this.y = 7;
            }
        }
        new Temp();
        """
    )
    # (pyodide: "<class 'pyodide.ffi.JsProxy'>")
    assert repr(type(a.to_py())) == "<class 'pyjs_core.JSProxy'>"


@pytest.mark.parametrize(
    "obj, msg",
    [
        ("Map([[[1,1], 2]])", "Cannot use key of type Array as a key to a Python dict"),
        ("Set([[1,1]])", "Cannot use key of type Array as a key to a Python set"),
        ("Map([[0, 2], [false, 3]])", "contains both 0 and false"),
        ("Set([0, false])", "contains both 0 and false"),
        ("Map([[1, 2], [true, 3]])", "contains both 1 and true"),
        ("Set([1, true])", "contains both 1 and true"),
    ],
)
def test_to_py4(obj, msg):
    import pytest

    from pyodide.code import run_js
    from pyodide.ffi import ConversionError, JSException

    a = run_js(f"new {obj}")

    with pytest.raises((ConversionError, JSException), match=msg):
        a.to_py()

    with pytest.raises((ConversionError, JSException), match=msg):
        a = run_js(f"pyjs.toPy(new {obj})")


@pytest.mark.skipif(not hasattr(run_js("globalThis"), "document"), reason="No document object")
def test_to_py_dom_collections():
    from pyodide.code import run_js

    run_js(
        """
        const div = document.createElement("div");
        div.id = "to-py-dom-collections";
        div.innerHTML = "<span></span><span></span><span></span>";
        document.body.appendChild(div);
        """
    )
    try:
        node_list = run_js('document.querySelectorAll("#to-py-dom-collections > span")')
        html_collection = run_js(
            'document.getElementById("to-py-dom-collections").children'
        )
        for collection in [node_list, html_collection]:
            result = collection.to_py()
            assert isinstance(result, list)
            assert [el.tagName for el in result] == ["SPAN", "SPAN", "SPAN"]
    finally:
        run_js('document.getElementById("to-py-dom-collections").remove()')


def test_to_py_default_converter():
    from pyodide.code import run_js

    [r1, r2] = run_js(
        """
        class Pair {
            constructor(first, second){
                this.first = first;
                this.second = second;
            }
        }
        let l = [1,2,3];
        const r1 = new Pair(l, [l]);
        const r2 = new Pair(l, [l]);
        r2.first = r2;
        const opts = {defaultConverter(value, converter, cache){
            if(value.constructor.name !== "Pair"){
                return value;
            }
            let list = pyjs.globals.get("list");
            l = list();
            list.destroy();
            cache(value, l);
            const first = converter(value.first);
            const second = converter(value.second);
            l.append(first);
            l.append(second);
            first.destroy();
            second.destroy();
            return l;
        }};
        pyjs.toPy([r1, r2], opts);
        """
    )

    assert isinstance(r1, list)
    assert r1[0] is r1[1][0]
    assert r1[0] == [1, 2, 3]
    assert r2[0] is r2


def test_to_py_default_converter2():
    from typing import Any

    from pyodide.code import run_js

    [p1, p2] = run_js(
        """
        class Pair {
            constructor(first, second){
                this.first = first;
                this.second = second;
            }
        }
        const l = [1,2,3];
        const r1 = new Pair(l, [l]);
        const r2 = new Pair(l, [l]);
        r2.first = r2;
        [r1, r2]
        """
    )

    def default_converter(value, converter, cache):
        if value.constructor.name != "Pair":
            return value
        l: list[Any] = []
        cache(value, l)
        l.append(converter(value.first))
        l.append(converter(value.second))
        return l

    r1 = p1.to_py(default_converter=default_converter)
    assert isinstance(r1, list)
    assert r1[0] is r1[1][0]
    assert r1[0] == [1, 2, 3]

    r2 = p2.to_py(default_converter=default_converter)
    assert r2[0] is r2


def test_to_js_default_converter():
    run_js(
        """
        (() => {
            let p = pyjs.runPython(`
class Pair:
    def __init__(self, first, second):
        self.first = first
        self.second = second
p = Pair(1,2)
p
            `);
            let res = p.toJs({ default_converter(x, convert, cacheConversion){
                let result = [];
                cacheConversion(x, result);
                result.push(convert(x.first));
                result.push(convert(x.second));
                return result;
            }});
            assert(() => res[0] === 1);
            assert(() => res[1] === 2);
            p.first = p;
            let res2 = p.toJs({ default_converter(x, convert, cacheConversion){
                let result = [];
                cacheConversion(x, result);
                result.push(convert(x.first));
                result.push(convert(x.second));
                return result;
            }});
            assert(() => res2[0] === res2);
            assert(() => res2[1] === 2);
            p.destroy();
        })()
        """
    )


def test_to_js_default_converter2():
    import json

    import pytest

    from js import JSON, Array
    from pyodide.code import run_js
    from pyodide.ffi import JSException, to_js

    class Pair:
        __slots__ = ("first", "second")

        def __init__(self, first, second):
            self.first = first
            self.second = second

    p1 = Pair(1, 2)
    p2 = Pair(1, 2)
    p2.first = p2

    def default_converter(value, convert, cacheConversion):
        result = Array.new()
        cacheConversion(value, result)
        result.push(convert(value.first))
        result.push(convert(value.second))
        return result

    p1js = to_js(p1, default_converter=default_converter)
    p2js = to_js(p2, default_converter=default_converter)

    assert json.loads(JSON.stringify(p1js)) == [1, 2]

    # (pyodide: `match="TypeError"`; the text of a pyjs JSException is only
    # the message, the kind of error is its `name`)
    with pytest.raises(JSException) as excinfo:
        JSON.stringify(p2js)
    assert excinfo.value.name == "TypeError"

    assert run_js("(x) => x[0] === x")(p2js)
    assert run_js("(x) => x[1] === 2")(p2js)


def test_to_js_eager_converter():
    import pytest

    from js import Array
    from pyodide.ffi import ConversionError, destroy_proxies, to_js

    recursive_list: Any = []
    recursive_list.append(recursive_list)

    recursive_dict: Any = {}
    recursive_dict[0] = recursive_dict

    a_thing = [{1: 2}, (2, 4, 6)]

    def normal(value, convert, cacheConversion):
        return convert(value)

    def reject_tuples(value, convert, cacheConversion):
        if isinstance(value, tuple):
            raise ConversionError("We don't convert tuples!")
        return convert(value)

    def proxy_tuples(value, convert, cacheConversion):
        if isinstance(value, tuple):
            return value
        return convert(value)

    to_js(recursive_list, eager_converter=normal)
    to_js(recursive_dict, eager_converter=normal)
    to_js(a_thing, eager_converter=normal)

    to_js(recursive_list, eager_converter=reject_tuples)
    to_js(recursive_dict, eager_converter=reject_tuples)
    with pytest.raises(ConversionError, match="We don't convert tuples"):
        to_js(a_thing, eager_converter=reject_tuples)

    to_js(recursive_list, eager_converter=proxy_tuples)
    to_js(recursive_dict, eager_converter=proxy_tuples)
    proxylist = Array.new()
    res = to_js(a_thing, eager_converter=proxy_tuples, pyproxies=proxylist)
    assert res[-1] == (2, 4, 6)
    assert len(proxylist) == 1
    destroy_proxies(proxylist)


def test_dict_converter_cache1():
    run_js(
        """
        (() => {
            let d1 = pyjs.runPython('d={0: {1: 2}}; d[1]=d[0]; d');
            let d = d1.toJs({dict_converter: Object.fromEntries});
            d1.destroy();
            assert(() => d[0] === d[1]);
        })()
        """
    )


@pytest.mark.xfail(
    reason="TODO: Fix me (xfail in pyodide as well; pyjs too: d[2] !== d with a "
    "dict_converter)"
)
def test_dict_converter_cache2():
    run_js(
        """
        (() => {
            let d1 = pyjs.runPython('d={0: {1: 2}}; d[1]=d[0]; d[2] = d; d');
            let d = d1.toJs({dict_converter: Object.fromEntries});
            assert(() => d[2] === d);
        })()
        """
    )


def test_dict_and_default_converter():
    from js import Object
    from pyodide.ffi import to_js

    def default_converter(_obj, c, _):
        return c({"a": 2})

    class A:
        pass

    res = to_js(
        A, dict_converter=Object.fromEntries, default_converter=default_converter
    )
    assert res.a == 2


NO_BIND = pytest.mark.xfail(reason="pyjs: no bind_sig / bind_class (typed signatures, _pyodide.jsbind)")


@NO_BIND
def test_bind_attrs():
    from typing import Annotated

    from _pyodide.jsbind import BindClass, Deep
    from pyodide.code import run_js
    from pyodide.ffi import JSProxy

    class A(BindClass):
        x: int
        y: Annotated[list[int], Deep]

    a_px: JSProxy = run_js(
        """
        ({
            x: 7,
            y: [1,2,3],
        })
        """
    )
    a = a_px.bind_sig(A)
    assert a.x == 7
    assert a.y == [1, 2, 3]


@NO_BIND
def test_bind_call_convert():
    from typing import Annotated

    from _pyodide.jsbind import Deep, Json
    from pyodide.code import run_js

    def fsig(
        a: dict[str, int],
        b: Annotated[dict[str, int], Json],
        c: Annotated[dict[str, int], Deep],
        /,
    ) -> Annotated[list[int], Deep]:
        raise NotImplementedError

    f = run_js(
        """
        (function f(x, y, z) {
            return [x.get("a"), y.b, z.c]
        })
        """
    ).bind_sig(fsig)

    x = {"a": 2}
    y = {"b": 4}
    z = {"c": 6}
    assert f(x, y, z) == [2, 4, 6]


@NO_BIND
def test_bind_call_bind_return_value():
    from typing import Annotated

    from _pyodide.jsbind import BindClass, Deep
    from pyodide.code import run_js

    class A(BindClass):
        x: Annotated[list[int], Deep]

    def fsig() -> A:
        raise NotImplementedError

    f = run_js(
        """
        (function f() {
            return {x: [77, 1]};
        })
        """
    ).bind_sig(fsig)

    assert f().x == [77, 1]


@NO_BIND
async def test_bind_future_convert_result():
    from asyncio import Future
    from typing import Annotated

    from _pyodide.jsbind import Deep
    from pyodide.code import run_js

    def f1() -> Future[Annotated[list[int], Deep]]:
        raise NotImplementedError

    async def f2() -> Annotated[list[int], Deep]:
        raise NotImplementedError

    jsfunc = run_js(
        """
        (async function() {
            return [1,2,3];
        })
        """
    )
    f1 = jsfunc.bind_sig(f1)
    f2 = jsfunc.bind_sig(f2)
    assert await f1() == [1, 2, 3]
    assert await f2() == [1, 2, 3]


@NO_BIND
async def test_bind_future_bind_result():
    from asyncio import Future
    from typing import Annotated

    from _pyodide.jsbind import BindClass, Deep
    from pyodide.code import run_js

    class A(BindClass):
        x: Annotated[list[int], Deep]

    def f1() -> Future[A]:
        raise NotImplementedError

    async def f2() -> A:
        raise NotImplementedError

    jsfunc = run_js(
        """
        async function f() {
            return {x: [77, 1]};
        };
        f
        """
    )
    f1 = jsfunc.bind_sig(f1)
    f2 = jsfunc.bind_sig(f2)
    assert (await f1()).x == [77, 1]
    assert (await f2()).x == [77, 1]


@NO_BIND
def test_bind3():
    from pyodide.code import run_js

    o = run_js(
        """
        ({
            f(x, y, z) {
                return [x.get("a"), y.b, z.c]
            },
            x: [1,2,3],
            y: {
                g(x) {
                    return x.a;
                },
                c: [1,2,3]
            }
        })
        """
    )
    from typing import Annotated

    from _pyodide.jsbind import BindClass, Deep, Json

    class B(BindClass):
        @staticmethod
        def g(x: Annotated[dict[str, int], Json], /) -> int:
            raise NotImplementedError

        c: Annotated[list[int], Deep]

    class A(BindClass):
        @staticmethod
        def f(
            a: dict[str, int],
            b: Annotated[dict[str, int], Json],
            c: Annotated[dict[str, int], Deep],
            /,
        ) -> Annotated[list[int], Deep]:
            raise NotImplementedError

        x: Annotated[list[int], Deep]
        y: B

    o2: A = o.bind_sig(A)
    f1 = o2.f
    f2 = o.f.bind_sig(A.f)

    x = {"a": 2}
    y = {"b": 4}
    z = {"c": 6}
    assert o2.f(x, y, z) == [2, 4, 6]
    assert f1(x, y, z) == [2, 4, 6]
    assert f2(x, y, z) == [2, 4, 6]
    assert o2.y.g({"a": 7}) == 7


@NO_BIND
async def test_bind_async1():
    from asyncio import Future
    from typing import Annotated

    from _pyodide.jsbind import BindClass, Deep
    from pyodide.code import run_js

    class A(BindClass):
        x: Future[Annotated[list[int], Deep]]

    a: A = run_js(
        """
        ({
            x: (async function () {
                return [1, 2, 3]
            })()
        })
        """
    ).bind_sig(A)

    assert await a.x == [1, 2, 3]


@NO_BIND
async def test_bind_async2():
    from asyncio import Future
    from typing import Annotated

    from _pyodide.jsbind import Deep
    from pyodide.code import run_js
    from pyodide.ffi import JSProxy

    jsfunc: JSProxy = run_js(
        """
        (async function () {
            return [1, 2, 3]
        });
        """
    )

    async def f1() -> Annotated[list[int], Deep]:
        raise NotImplementedError

    def f2() -> Future[Annotated[list[int], Deep]]:
        raise NotImplementedError

    f1 = jsfunc.bind_sig(f1)
    f2 = jsfunc.bind_sig(f2)

    assert await f1() == [1, 2, 3]
    assert await f2() == [1, 2, 3]


@NO_BIND
async def test_bind_async3():
    from asyncio import Future
    from typing import Annotated

    from _pyodide.jsbind import BindClass, Deep
    from pyodide.code import run_js
    from pyodide.ffi import JSProxy

    class A(BindClass):
        x: Annotated[list[int], Deep]

    async def f1() -> A:
        raise NotImplementedError

    def f2() -> Future[A]:
        raise NotImplementedError

    jsfunc: JSProxy = run_js(
        """
        (async function() {
            return {
                x : [1,2,3]
            };
        })
        """
    )

    f1 = jsfunc.bind_sig(f1)
    f2 = jsfunc.bind_sig(f2)

    assert (await f1()).x == [1, 2, 3]
    assert (await f2()).x == [1, 2, 3]


@NO_BIND
def test_bind_pre_convert():
    from typing import Annotated, _caches  # type:ignore[attr-defined]

    from _pyodide.jsbind import Deep, Py2JsConverterMeta
    from js import Headers  # type:ignore[attr-defined]
    from pyodide.code import run_js
    from pyodide.ffi import JSProxy

    ajs: JSProxy = run_js("(x) => [x.toString(), JSON.stringify(Array.from(x))]")

    class ToHeaders(metaclass=Py2JsConverterMeta):
        @staticmethod
        def pre_convert(value):
            return Headers.new(value.items())

    def a(
        x: Annotated[dict[str, str] | None, ToHeaders], /
    ) -> Annotated[list[str], Deep]:
        return []

    abound = ajs.bind_sig(a)
    assert abound({"x": "y"}) == ["[object Headers]", '[["x","y"]]']
    _caches[Annotated._getitem.__wrapped__].cache_clear()  # type:ignore[attr-defined]


@NO_BIND
def test_bind_construct():
    from typing import Annotated, Any, NotRequired, TypedDict

    from _pyodide.jsbind import Default, Json
    from pyodide.code import run_js
    from pyodide.ffi import JSProxy

    class Inner(TypedDict):
        b: int
        c: NotRequired[str]

    class Outer(TypedDict):
        a: list[Inner]
        x: int

    ajs: JSProxy = run_js("(x) => x")

    def a_shape(x: Annotated[Any, Default], /) -> Annotated[Outer, Json]:
        raise NotImplementedError

    # pyright infers abound has same type as a_shape,
    a = ajs.bind_sig(a_shape)
    o = run_js("({x: 7, a : [{b: 1, c: 'xyz'},{b: 2},{b: 3}]})")

    res = a(o)
    assert res["x"] == 7
    res["x"] = 9
    assert o.x == 9
    assert res["a"][0]["b"] == 1
    assert res["a"][0]["c"]
    assert "c" in res["a"][0]
    assert res["a"][0]["c"] == "xyz"
    assert res["a"][1]["b"] == 2
    assert "c" not in res["a"][1]
    res["a"][1]["c"] = "s"
    assert o.a[1].c == "s"


@NO_BIND
def test_bind_py_json():
    from pyodide.code import run_js
    from pyodide.ffi import JSProxy

    A: JSProxy = run_js("(class {x = 7})")

    class A_sig:
        x: int

    Abound = A.bind_class(A_sig)

    res = Abound()
    assert res.x == 7


@NO_BIND
def test_bind_class():
    from typing import Annotated

    from _pyodide.jsbind import BindClass, Deep
    from pyodide.code import run_js
    from pyodide.ffi import JSProxy

    A_px: JSProxy = run_js("(class {x = [1,2,3]; f() { return [1]; }})")
    a_px: JSProxy = run_js("(A) => new A()")(A_px)

    class A_sig(BindClass):
        x: Annotated[list[int], Deep]

        def __init__(self, /): ...

        def f(self, /) -> Annotated[list[int], Deep]:
            return []

    A = A_px.bind_class(A_sig)
    res = A()
    assert isinstance(res.x, list)
    assert isinstance(res.f(), list)
    a = a_px.bind_sig(A_sig)
    assert isinstance(a.x, list)
    assert isinstance(a.f(), list)


@NO_BIND
def test_bind__call__():
    from typing import Annotated

    from _pyodide.jsbind import BindClass, Deep, Json
    from pyodide.code import run_js
    from pyodide.ffi import JSProxy

    class FuncType(BindClass):
        def __call__(
            self,
            a: dict[str, int],
            b: Annotated[dict[str, int], Json],
            c: Annotated[dict[str, int], Deep],
            /,
        ) -> Annotated[list[int], Deep]:
            return []

    f_px: JSProxy = run_js(
        """
        (function f(x, y, z) {
            return [x.get("a"), y.b, z.c]
        })
        """
    )
    f = f_px.bind_sig(FuncType)

    assert f({"a": 7}, {"b": 9}, {"c": 11}) == [7, 9, 11]


@NO_BIND
def test_bind_getattr():
    from typing import Annotated

    from _pyodide.jsbind import BindClass, Deep, Json
    from pyodide.code import run_js
    from pyodide.ffi import JSProxy

    class FuncType(BindClass):
        def __call__(
            self,
            a: dict[str, int],
            b: Annotated[dict[str, int], Json],
            c: Annotated[dict[str, int], Deep],
            /,
        ) -> Annotated[list[int], Deep]:
            return []

    class T:
        def __getattr__(self, name: str) -> FuncType:
            raise NotImplementedError

    t_px: JSProxy = run_js(
        """
        ({
            f(x, y, z) {
                return [x.get("a"), y.b, z.c]
            },
            g() {
                return [1, 2, 3];
            }
        })
        """
    )
    t = t_px.bind_sig(T)

    assert t.f({"a": 7}, {"b": 9}, {"c": 11}) == [7, 9, 11]
    assert t.g({"a": 7}, {"b": 9}, {"c": 11}) == [1, 2, 3]


def test_to_js_no_leak():
    from js import Object
    from pyodide.ffi import to_js

    d = {"key": Object()}
    to_js(d)


def test_js_callable_not_function():
    from pyodide.code import run_js

    o = run_js(
        """
        function nonFuncCallable (...params) {
            console.log(this);
            return [this, ...params]
        }
        Object.setPrototypeOf(nonFuncCallable, {})
        const o = {nonFuncCallable};
        o
        """
    )
    assert list(o.nonFuncCallable(1, 2, 3)) == [o, 1, 2, 3]


def test_js_bigint():
    from pytest import raises

    from pyodide.ffi import JSBigInt

    m1 = JSBigInt(-1)
    p1 = JSBigInt(1)
    p13 = JSBigInt(13)
    p21 = JSBigInt(21)
    p31 = JSBigInt(31)

    # Unary ops
    # abs
    assert isinstance(abs(m1), JSBigInt)
    assert isinstance(abs(p1), JSBigInt)
    assert m1 == -1
    assert abs(m1) == 1
    assert abs(p1) == 1

    # plus
    assert isinstance(+m1, JSBigInt)
    assert +m1 == m1
    assert +m1 == -1

    # minus
    assert isinstance(-m1, JSBigInt)
    assert -m1 == p1
    assert -m1 == 1

    # invert
    assert isinstance(~p21, JSBigInt)
    assert ~p21 == ~21

    # Binary ops
    # comparison
    assert m1 < p1
    assert -1 < p1
    assert 0.8 < p1
    assert p1 < 2
    assert p1 < 2.1

    assert m1 <= p1
    assert -1 <= p1
    assert 0.8 <= p1
    assert p1 <= 2
    assert p1 <= 2.1
    assert not (m1 > p1)
    assert p1 == 1.0

    # plus
    assert isinstance(m1 + p1, JSBigInt)
    assert isinstance((-1) + p1, int)
    assert isinstance(m1 + 1, int)
    assert m1 + p1 == 0
    assert (-1) + p1 == 0
    assert m1 + 1 == 0

    assert isinstance(m1 + 0.3, float)
    assert isinstance(0.3 + m1, float)
    assert m1 + 0.3 == (-1) + 0.3
    assert 0.3 + m1 == 0.3 + (-1)

    # minus
    assert isinstance(m1 - p1, JSBigInt)
    assert isinstance((-1) - p1, int)
    assert isinstance(m1 - 1, int)
    assert m1 - p1 == -2
    assert (-1) - p1 == -2
    assert m1 - 1 == -2

    assert isinstance(m1 - 0.3, float)
    assert isinstance(0.3 - m1, float)
    assert m1 - 0.3 == (-1) - 0.3
    assert 0.3 - m1 == 0.3 - (-1)

    # bitwise and
    assert isinstance(p13 & p21, JSBigInt)
    assert isinstance(p13 & 21, int)
    assert isinstance(13 & p21, int)
    assert p13 & p21 == 5
    assert p13 & 21 == 5
    assert 13 & p21 == 5

    with raises(TypeError, match="'JSBigInt' and 'float'"):
        p13 & 0.2  # type: ignore[operator]

    with raises(TypeError, match="'float' and 'JSBigInt'"):
        0.2 & p13  # type: ignore[operator]

    # bitwise or
    assert isinstance(p21 | p13, JSBigInt)
    assert isinstance(p21 | 13, int)
    assert isinstance(21 | p13, int)
    assert p21 | p13 == 29
    assert p21 | 13 == 29
    assert 21 | p13 == 29

    with raises(TypeError, match="'JSBigInt' and 'float'"):
        p13 | 0.2  # type: ignore[operator]

    with raises(TypeError, match="'float' and 'JSBigInt'"):
        0.2 | p13  # type: ignore[operator]

    # bitwise xor
    assert isinstance(p21 ^ p13, JSBigInt)
    assert isinstance(p21 ^ 13, int)
    assert isinstance(21 ^ p13, int)
    assert p21 ^ p13 == 24
    assert p21 ^ 13 == 24
    assert 21 ^ p13 == 24

    with raises(TypeError, match="'JSBigInt' and 'float'"):
        p13 ^ 0.2  # type: ignore[operator]

    with raises(TypeError, match="'float' and 'JSBigInt'"):
        0.2 ^ p13  # type: ignore[operator]

    # left shift
    assert isinstance(p21 << p13, JSBigInt)
    assert isinstance(p21 << 13, JSBigInt)
    assert isinstance(21 << p13, int)
    assert p21 << p13 == 21 << 13
    assert p21 << 13 == 21 << 13
    assert 21 << p13 == 21 << 13

    with raises(TypeError, match="'JSBigInt' and 'float'"):
        p13 << 0.2  # type: ignore[operator]

    with raises(TypeError, match="'float' and 'JSBigInt'"):
        0.2 << p13  # type: ignore[operator]

    # right shift
    assert isinstance(p21 >> p13, JSBigInt)
    assert isinstance(p21 >> 13, JSBigInt)
    assert isinstance(21 >> p13, int)
    assert p21 >> p13 == 21 >> 13
    assert p21 >> 13 == 21 >> 13
    assert 21 >> p13 == 21 >> 13

    with raises(TypeError, match="'JSBigInt' and 'float'"):
        p13 >> 0.2  # type: ignore[operator]

    with raises(TypeError, match="'float' and 'JSBigInt'"):
        0.2 >> p13  # type: ignore[operator]

    # floor division
    assert isinstance(p21 // p13, JSBigInt)
    assert isinstance(21 // p13, int)
    assert isinstance(p21 // 13, JSBigInt)
    assert p21 // p13 == 1
    assert 21 // p13 == 1
    assert p21 // 13 == 1

    # Surprisingly, 21 // 1.2 is a float even though floordiv always returns an
    # int.
    assert isinstance(p21 // 1.2, float)
    assert p21 // 1.2 == 21 // 1.2

    assert isinstance(29.7 // p13, float)
    assert 29.7 // p13 == 29.7 // 13

    # Division
    assert isinstance(p21 / p13, float)
    assert isinstance(p21 / 13, float)
    assert isinstance(21 / p13, float)
    assert p21 / p13 == 21 / 13
    assert p21 / 13 == 21 / 13
    assert 21 / p13 == 21 / 13

    assert isinstance(p21 / 1.2, float)
    assert p21 / 1.2 == 21 / 1.2

    assert isinstance(29.7 / p13, float)
    assert 29.7 / p13 == 29.7 / 13

    # Modulus
    assert isinstance(p21 % p13, JSBigInt)
    assert isinstance(21 % p13, int)
    assert isinstance(p21 % 13, JSBigInt)
    assert p21 % p13 == 8
    assert 21 % p13 == 8
    assert p21 % 13 == 8

    assert isinstance(p21 % 0.57, float)
    assert p21 % 0.57 == 21 % 0.57

    assert isinstance(49.3 % p21, float)
    assert 49.3 % p21 == 49.3 % 21

    # Power
    assert isinstance(p21**p13, JSBigInt)
    assert isinstance(p21**13, JSBigInt)
    assert isinstance(21**p13, int)
    assert p21**p13 == 21**13
    assert p21**13 == 21**13
    assert 21**p13 == 21**13

    assert isinstance(p21**m1, float)
    assert isinstance(p21**-1, float)
    assert isinstance(21**m1, float)
    assert p21**m1 == 21**-1
    assert p21**-1 == 21**-1
    assert 21**m1 == 21**-1

    assert isinstance(1.9**p21, float)
    assert 1.9**p21 == 1.9**21
    assert isinstance(p21**1.9, float)
    assert p21**1.9 == 21**1.9

    # Ternary power
    assert isinstance(pow(p21, m1, p31), JSBigInt)
    assert isinstance(pow(p21, m1, 31), JSBigInt)
    assert isinstance(pow(p21, -1, p31), JSBigInt)
    assert isinstance(pow(p21, -1, 31), JSBigInt)

    assert isinstance(pow(21, m1, p31), int)
    assert isinstance(pow(21, m1, 31), int)
    assert isinstance(pow(21, -1, p31), int)

    assert pow(p21, m1, p31) == pow(21, -1, 31)
    assert pow(p21, m1, 31) == pow(21, -1, 31)
    assert pow(p21, -1, p31) == pow(21, -1, 31)
    assert pow(p21, -1, 31) == pow(21, -1, 31)
    assert pow(21, m1, p31) == pow(21, -1, 31)
    assert pow(21, m1, 31) == pow(21, -1, 31)
    assert pow(21, -1, p31) == pow(21, -1, 31)

    msg = r"pow\(\) 3rd argument not allowed unless all arguments are integers"
    with raises(TypeError, match=msg):
        pow(p21, 0.5, p31)  # type:ignore[misc]


def test_js_bigint_construct_typed_array():
    from js import BigInt64Array
    from pyodide.ffi import JSBigInt

    # Without JsBigInt we can't construct a BigInt64Array
    a = BigInt64Array.new([JSBigInt(x) for x in range(1, 10, 2)])
    assert list(a) == list(range(1, 10, 2))
