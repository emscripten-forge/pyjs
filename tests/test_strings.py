"""Strings and arguments from JavaScript to Python (src/js/codec.ts).

When JavaScript calls Python (or returns a value to it), strings are written
as utf8 into wasm memory: into the scratch region (64 KiB, used like a
stack) if they fit, else into memory from malloc that the C side frees
(OWNED). The argument slots go the same way. These tests cover both paths,
the ASCII fast path of the encoder and its fallback for other characters,
and nested calls (JS -> Python -> JS -> Python), where an inner call must
not overwrite what an outer one still uses.
"""

import pytest

import pyjs
from pyjs import js

# a JavaScript function that calls the Python callable `f` with the given
# arguments and returns what it returns
_call = js.Function("f", "...args", "return f(...args);")
# the string a JavaScript expression evaluates to (built in JavaScript, so
# that it really comes from JavaScript)
_js_eval = js.Function("source", "return (0, eval)(source);")

SCRATCH_SIZE = 64 * 1024

STRINGS = [
    "",
    "a",
    "short ascii",
    "a longer ascii string, longer than the 24 bytes of the short path",
    "é",
    "éa",
    "aé",
    "ascii then non-ascii: é",
    "日本語",
    "emoji 😀 (two UTF-16 code units)",
    "﻿starts with a byte order mark",
    "nul \x00 inside",
]


@pytest.mark.parametrize("text", STRINGS)
def test_string_argument_and_result(text):
    """a string as argument of a Python function called from JavaScript, and
    as result of a JavaScript function called from Python"""
    got = []
    result = _call(lambda s: got.append(s) or s, text)
    assert got == [text]
    assert result == text


def test_lone_surrogate_from_javascript():
    """a lone surrogate (invalid UTF-16, but a valid JS string) arrives as the
    same code point (decoded with "surrogatepass")"""
    assert _js_eval('"\\ud800x"') == "\ud800x"


@pytest.mark.parametrize("char", ["a", "é", "日", "😀"])
def test_string_larger_than_the_scratch_region(char):
    """a string that does not fit into the scratch region goes through
    malloc (and is freed by the C side): as argument and as result"""
    text = char * (SCRATCH_SIZE // len(char.encode()) + 1000)
    got = []
    result = _call(lambda s: got.append(s) or s, text)
    assert got[0] == text
    assert result == text


def test_many_arguments():
    """more argument slots than fit into the scratch region (16 bytes each):
    the slots go through malloc"""
    n = SCRATCH_SIZE // 16 + 100
    args = [f"arg{i}" for i in range(n)]
    got = _call(lambda *a: list(a), *args)
    assert got == args


def test_arguments_fill_the_scratch_region():
    """several arguments that together overflow the region: the first ones
    in the scratch region, the rest through malloc, all arrive intact"""
    big = "x" * (SCRATCH_SIZE // 3)
    args = [big + str(i) for i in range(6)]
    got = _call(lambda *a: list(a), *args)
    assert got == args


def test_nested_calls_do_not_overwrite_each_other():
    """JS -> Python -> JS -> Python, each level with large strings: an inner
    call starts above the data of the outer one in the scratch region and
    gives it back before the outer continues"""
    big = "é" * (SCRATCH_SIZE // 8)

    def inner(s, depth):
        if depth == 0:
            return s
        # calls JavaScript, which calls inner again with a new string
        return _call(inner, s + str(depth), depth - 1)

    def outer(a, b, c):
        nested = inner(big, 5)
        # the outer arguments are still what they were
        return [a, b, c, nested]

    a, b, c = "first", big, "third é"
    assert _call(outer, a, b, c) == [a, b, c, big + "54321"]
