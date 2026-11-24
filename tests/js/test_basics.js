// JavaScript tests of the pyjs Module API (runPython / runPythonAsync /
// pyimport, PyProxy, PythonError). ES module: tests/main.py imports it and
// calls every exported `test_*` function with the initialized pyjs Module.

/** a === b, else throw */
function assert_eq(a,b){
    if (a !== b){
        throw Error(`assert_eq failed: "${a} === ${b}" is violated`)
    }
}

/** a and b are equal as JSON (object keys in any order), else throw */
function assert_deep_json_eq(a,b){
    const replacer = (key, value) =>
    value instanceof Object && !(value instanceof Array) ?
        Object.keys(value)
        .sort()
        .reduce((sorted, key) => {
            sorted[key] = value[key];
            return sorted
        }, {}) :
        value;

    let jsa = JSON.stringify(a, replacer);
    let jsb = JSON.stringify(b, replacer);
    if(jsa !== jsb)
    {
        throw Error(`assert_eq failed: "${a}" and "${b}" are not deeply equal`)
    }
}

/** a is undefined, else throw */
function assert_undefined(a){
    if (a !== undefined){
        throw Error(`assert_undefined failed: "${a} !== undefined" is violated`)
    }
}

/** fn() throws, else throw; returns what it threw */
function assert_throws(fn){
    try {
        fn();
    } catch (e) {
        return e;
    }
    throw Error("assert_throws failed: nothing was thrown");
}

// values that are converted, not proxied
export async function test_run_python_fundamentals(pyjs){
    // string
    assert_eq(pyjs.runPython("'hello world'"), "hello world");
    assert_eq(pyjs.runPython("'1'"), "1");
    // (not ascii)
    assert_eq(pyjs.runPython("'gr\\u00fc\\u00dfe \\U0001f600'"), "grüße \u{1f600}");

    // int
    assert_eq(pyjs.runPython("1"), 1);
    assert_eq(pyjs.runPython("-1"), -1);
    // an int that no JS number can hold is a BigInt
    assert_eq(pyjs.runPython("2 ** 70"), 2n ** 70n);

    // bool
    assert_eq(pyjs.runPython("True"), true);
    assert_eq(pyjs.runPython("False"), false);

    // float
    assert_eq(pyjs.runPython("1.5"), 1.5);

    // None is undefined, jsnull is null
    assert_undefined(pyjs.runPython("None"));
    assert_eq(pyjs.runPython("import pyjs\npyjs.jsnull"), null);
}

// a script: the value of the last line, if it is an expression
export async function test_run_python_script(pyjs){
    const res = pyjs.runPython(
`def fubar():
    return  42
fubar()
`);
    assert_eq(res, 42);
    // ends with a statement: no value
    assert_undefined(pyjs.runPython("z = 1"));
    // the code ran in the globals of __main__
    assert_eq(pyjs.globals.get("z"), 1);
    assert_eq(pyjs.runPython("z + 1"), 2);
    // empty
    assert_undefined(pyjs.runPython(""));
}

export async function test_run_python_namespaces(pyjs){
    // own namespace
    const namespace = pyjs.runPython("dict()");
    pyjs.runPython("y = 5", {globals: namespace});
    assert_eq(namespace.get("y"), 5);
    assert_eq(pyjs.globals.has("y"), false);
    namespace.destroy();
}

export async function test_pyimport(pyjs){
    const math = pyjs.pyimport("math");
    assert_eq(math.floor(2.5), 2);
    assert_eq(math.type, "module");
    math.destroy();
    // the python package of pyjs itself
    const py_pyjs = pyjs.pyimport("pyjs");
    assert_eq(py_pyjs.IN_BROWSER, true);
    py_pyjs.destroy();
    // a missing module is a python error
    const error = assert_throws(() => pyjs.pyimport("no_such_module_xyz"));
    assert_eq(error.type, "ModuleNotFoundError");
}

// the result of calling python is a PyProxy for objects that are not converted
export async function test_pyproxy(pyjs){
    const list = pyjs.runPython("[1, 'two', [3]]");
    assert_eq(list.type, "list");
    assert_eq(list.length, 3);
    assert_eq(list.get(1), "two");
    assert_eq(list.has("two"), true);
    assert_eq(String(list), "[1, 'two', [3]]");
    // iterable
    assert_eq(Array.from(list).length, 3);
    // python attributes are properties, methods are callable
    list.append(4);
    assert_eq(list.length, 4);
    // items: set / delete
    list.set(0, 10);
    assert_eq(list.get(0), 10);
    list.delete(0);
    assert_eq(list.length, 3);
    // a missing attribute is undefined, like for JS objects
    assert_undefined(list.no_such_attribute);
    // a copy has its own lifetime
    const copy = list.copy();
    list.destroy();
    assert_eq(copy.length, 3);
    copy.destroy();
    assert_throws(() => copy.length);
}

// toJs: a deep copy as JS value
export async function test_pyproxy_to_js(pyjs){
    const list = pyjs.runPython("[False, 1, [1, 2, 'three']]");
    assert_deep_json_eq(list.toJs(), [false, 1, [1, 2, "three"]]);
    // with options: only one level deep, the inner list stays a proxy
    const shallow = list.toJs({depth: 1});
    assert_eq(Array.isArray(shallow), true);
    assert_eq(Array.isArray(shallow[2]), false);
    assert_eq(shallow[2].type, "list");
    shallow[2].destroy();
    list.destroy();
    // a dict becomes a plain object
    const dict = pyjs.runPython("{'k': [1, 2, 3]}");
    assert_deep_json_eq(dict.toJs(), {k: [1, 2, 3]});
    dict.destroy();
}

export async function test_call_python(pyjs){
    const f = pyjs.runPython("lambda a, b=10, *, c=100: a + b + c");
    // callable like a JS function
    assert_eq(typeof f, "function");
    assert_eq(f(1), 111);
    assert_eq(f(1, 2), 103);
    // keyword arguments: one object, the last argument of callKwargs
    assert_eq(f.callKwargs(1, {c: 3}), 14);
    assert_eq(f.callKwargs(1, {b: 2, c: 3}), 6);
    f.destroy();
    // an object that is not callable is no function
    const list = pyjs.runPython("[]");
    assert_eq(typeof list, "object");
    list.destroy();
}

// JS values passed to python: objects arrive as proxies and come back as themselves
export async function test_js_objects_in_python(pyjs){
    const identity = pyjs.runPython("lambda x: x");
    const obj = {a: 1};
    assert_eq(identity(obj), obj);
    assert_eq(identity(null), null);
    assert_undefined(identity(undefined));
    const read = pyjs.runPython("lambda obj: obj.a + len(obj.items)");
    assert_eq(read({a: 1, items: [1, 2, 3]}), 4);
    // a python object passed through JS comes back as the same python object
    const is_same = pyjs.runPython("lambda a, b: a is b");
    const py_list = pyjs.runPython("[]");
    assert_eq(is_same(py_list, py_list), true);
    for (const proxy of [identity, read, is_same, py_list]) {
        proxy.destroy();
    }
}

export async function test_python_error(pyjs){
    const error = assert_throws(() => pyjs.runPython("raise ValueError('from python')"));
    assert_eq(error instanceof pyjs.PythonError, true);
    assert_eq(error instanceof Error, true);
    assert_eq(error.name, "PythonError");
    assert_eq(error.type, "ValueError");
    assert_eq(error.message.includes("from python"), true);
    // the traceback is part of the message
    assert_eq(error.message.includes("Traceback"), true);
    // a syntax error too
    assert_eq(assert_throws(() => pyjs.runPython("this is no python")).type, "SyntaxError");
}

// calling an `async def` gives an awaitable proxy
export async function test_async_call_simple(pyjs){
    const asleep = pyjs.runPython(`
import asyncio
async def fubar(arg):
    await asyncio.sleep(0.05)
    return arg * 2
fubar
    `)
    const coroutine = asleep(21);
    assert_eq(await coroutine, 42);
    coroutine.destroy();
    asleep.destroy();
}

export async function test_run_python_async(pyjs){
    const res = await pyjs.runPythonAsync(`
import asyncio
await asyncio.sleep(0.05)
42
`);
    assert_eq(res, 42);
}

export async function test_run_python_async_error(pyjs){
    let error = null;
    try {
        await pyjs.runPythonAsync("import asyncio\nawait asyncio.sleep(0)\nraise KeyError('async')");
    } catch (e) {
        error = e;
    }
    assert_eq(String(error).includes("KeyError"), true);
}

// `await` probes the result for `.then`: a python object (no `then`
// attribute) must arrive as the object itself, not as an AttributeError
export async function test_run_python_async_returns_python_object(pyjs){
    const res = await pyjs.runPythonAsync(`
import fractions
fractions.Fraction(1, 3)
`);
    // a live python object: usable when passed back to python
    const py_str = pyjs.runPython("str");
    assert_eq(py_str(res), "1/3");
    py_str.destroy();
    assert_undefined(res.then);
    // owned by JavaScript, like the result of runPython
    res.destroy();
}
