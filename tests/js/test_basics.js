// JavaScript tests of the pyjs Module API (eval / exec / exec_eval /
// async_exec_eval / py_call ...). ES module: tests/main.py imports it and
// calls every exported `test_*` function with the initialized pyjs Module.
function assert_eq(a,b){
    if (a !== b){
        throw Error(`assert_eq failed: "${a} === ${b}" is violated`)
    }
}

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

function assert_feq(v1, v2, epsilon) {
  if (epsilon == null) {
    epsilon = 0.000001;
  }
  if (!(Math.abs(v1 - v2) < epsilon)) {
    throw Error(`assert_feq failed: "${v1} ~= ${v2}" is violated`)
  }
};

function assert_undefined(a){
    if (a !== undefined){
        throw Error(`assert_undefined failed: "${a} !== undefined" is violated`)
    }
}

export async function test_eval_fundamentals(pyjs){

    // string
    let hello_world = pyjs.eval("'hello world'");
    assert_eq(hello_world, "hello world")
    let string_one = pyjs.eval("'1'");
    assert_eq(string_one, "1")

    // int
    let one = pyjs.eval("1");
    assert_eq(one, 1);
    let neg_one = pyjs.eval("-1");
    assert_eq(neg_one, -1);

    // bool
    let trueval = pyjs.eval("True");
    assert_eq(trueval, true);
    let falseval = pyjs.eval("False");
    assert_eq(falseval, false);


    // float
    let fone = pyjs.eval("1.0");
    assert_eq(fone, 1.0);

    // none
    let none = pyjs.eval("None");
    assert_undefined(none);
}

export async function test_eval_nested(pyjs){
    assert_deep_json_eq(pyjs.to_js(pyjs.eval("[False,1,[1,2,'three']]")),[false,1,[1,2,'three']])
    assert_deep_json_eq(Object.fromEntries(pyjs.to_js(pyjs.eval("{'k':[1,2,3]}"))),{'k':[1,2,3]})
}

export async function test_import_pyjs(pyjs){
    pyjs.exec("import pyjs");
}

export async function test_eval_exec(pyjs){
    let res = pyjs.exec_eval(
`import pyjs
def fubar():
    return  42
fubar()
`);
    assert_eq(res, 42);
}


export async function test_async_call_simple(pyjs){

    let asleep = pyjs.exec_eval(`
import asyncio
async def fubar(arg):
    await asyncio.sleep(0.5)
    return arg * 2
fubar
    `)
    let res = await asleep.py_call(21)
    assert_eq(res, 42);
}


export async function test_async_eval_exec(pyjs){
    let res = await pyjs.async_exec_eval(`
await asyncio.sleep(0.5)
42
`);
    assert_eq(res, 42);
}

// `await` probes the result for `.then`: a python object (no `then`
// attribute) must arrive as the object itself, not as an AttributeError
export async function test_async_exec_eval_returns_python_object(pyjs){
    let res = await pyjs.async_exec_eval(`
import fractions
fractions.Fraction(1, 3)
`);
    // toString: python's str() (String(res) would be the number, toPrimitive)
    assert_eq(res.toString(), "1/3");
    assert_undefined(res.then);
    // owned by JavaScript, like the result of exec_eval
    res.delete();
}
