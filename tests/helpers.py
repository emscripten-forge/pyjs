"""Small helpers shared by the tests."""

import json

import pyjs

# `a === b` in JavaScript, for two values passed from python
js_assert_eq = pyjs.js.Function(
    "output",
    "expected_output",
    """
    let eq = output === expected_output;
    if(!eq){
        console.log("assertion failed:", output,"!=",expected_output)
    }
    return eq
""",
)


def to_js_to_py(x):
    """a python value converted to JavaScript and back"""
    return pyjs.to_py(pyjs.to_js(x))


def eval_jsfunc(body):
    """the value of a JavaScript expression"""
    return pyjs.js.Function("return " + body)()


def ensure_js(val):
    """a str is a JavaScript expression: its value; anything else as it is"""
    if isinstance(val, str):
        return eval_jsfunc(val)
    return val


def nested_eq(x, should):
    """two nested structures of lists / dicts are equal (compared as JSON,
    which ignores the order of dict keys)"""
    x_string = json.dumps(x, sort_keys=True, indent=2)
    should_string = json.dumps(should, sort_keys=True, indent=2)
    return x_string == should_string
