// %% [markdown]
// # pyjs JavaScript API Tour
// Welcome to the tour of the pyjs JavaScript API. This notebook demonstrates how to use the PYJS JavaScript API to run Python code in the browser.

// %% [markdown]
// # Loading the pyjs module
// In this deployment, the pyjs runtime (`pyjs_runtime_browser.js` / `.wasm`) and a
// packed environment (python, numpy, ...) are deployed next to the JupyterLite,
// in `pyjs-runtime/wasm32/` and `pyjs-runtime/wasm64/`. The wasm64 build is used
// when the browser supports 64 bit memory (memory64), it can use more than 4 GB.
// This works with both JavaScript kernels: the IFrame kernel (code runs in an
// iframe of the JupyterLite page) and the Web Worker kernel (code runs in a
// worker started from the kernel extension in `lite/extensions/`).

// %% [code]
// locate the JupyterLite root and the pyjs runtime next to it
const liteRoot = globalThis.document
    // IFrame kernel: the iframe has the url of the JupyterLite page (lite/<app>/index.html)
    ? new URL("../", document.baseURI).href
    // Web Worker kernel: the worker script lives in lite/extensions/...
    : location.href.slice(0, location.href.indexOf("/extensions/") + 1);
// wasm64 if the browser supports memory64 (a module with a 64 bit memory validates)
const memory64 = WebAssembly.validate(new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0, 5, 3, 1, 4, 0]));
const wasmType = globalThis.PYJS_WASM ?? (memory64 ? "wasm64" : "wasm32");
console.log("pyjs runtime:", wasmType);
const pyjsRuntimeUrl = new URL(`../pyjs-runtime/${wasmType}/`, liteRoot).href;

// pyjs_runtime_browser.js is a classic script (not an ES module):
// evaluate it in the global scope, which defines `createModule`
const runtimeSource = await (await fetch(pyjsRuntimeUrl + "pyjs_runtime_browser.js")).text();
(0, eval)(runtimeSource);

// create the pyjs module, the wasm file sits next to the js file
const pyjs = await createModule({
    locateFile: (filename) => pyjsRuntimeUrl + filename,
});

// load the python packages (including the python standard library)
// from the packed environment
await pyjs.bootstrap_from_empack_packed_environment(
    pyjsRuntimeUrl + "empack_env_meta.json", // the environment meta data
    pyjsRuntimeUrl                           // where the package tarballs are
);
globalThis.pyjs = pyjs;
"pyjs is ready";

// %% [markdown]
// # Evaluating Python expressions:
// From now on, you can use the pyjs module to run python code.
// Here we use "eval" to evaluate a python expression

// %% [code]
pyjs.eval("print('hello world')");

// %% [markdown]
// # Executing Python code
// Here we execute a python code block using "exec" function

// %% [code]
pyjs.exec(`
import numpy
print(numpy.random.rand(3))
`);

// %% [markdown]
// # Executing Python code and returning the last expression
// Here we execute a python code block using "exec" function and return the last expression.


// %% [code]
let rand_arr = pyjs.exec_eval(`
import numpy
numpy.random.rand(2,4,3)
`);
rand_arr.delete()

// %% [markdown]

// # Using the pyobject class
// When a python object is returned, it is wrapped in a pyobject class. 
// This class provides methods to interact with the python object.
// Any created instance of the pyobject class needs to be deleted using the "delete" method.

// %% [code]
//  create a numpy array with [0,1,2,3] as value
let arr = pyjs.exec_eval(`
import numpy
numpy.arange(0,4)
`);

// get the shape
let arr_shape = arr.shape

// get the square function
const square_func = pyjs.eval('numpy.square')

// any function call / __call__ like operator on the python side
// is called via "py_call" 
const res = square_func.py_call(arr)

// print the result
console.log(res)

// delete all the created pyobjects
res.delete()
square_func.delete()
arr_shape.delete()
arr.delete()

// %% [markdown]
// # Type Conversion
// pyjs provides methods to convert between JavaScript and Python types.
// ## Explicit conversion

// %% [code]
// python list to javascript array
const py_list = pyjs.eval("[1,2,3]")
const js_arr = pyjs.to_js(py_list)
py_list.delete()
console.log(js_arr)

// python dict to js map
const py_dict = pyjs.eval("dict(a=1, b='fobar')")
const js_map = pyjs.to_js(py_dict)
py_dict.delete()

// values
console.log(Array.from(js_map.keys()))
// keys
console.log(Array.from(js_map.values()))

// %% [markdown]
// ## Implicit conversion
// Fundamental types are automatically converted between Python and JavaScript.
// This includes numbers, strings, booleans and null. 

// %% [code]
//  sum is a plain javascript number
const sum = pyjs.eval("sum([i for i in range(0,101)])")
sum

// %% [code]
// is_true is a plain javascript boolean
const is_true = pyjs.eval("sum([i for i in range(0,101)]) == 5050")
is_true

// %% [code]
// none will be undefined
let none = pyjs.eval('None')
console.log(none)

// %% [markdown]
// # Asynchronous execution
// The pyjs module provides a way to run python code asynchronously using the "exec_async" function.

// %% [code]
const py_code = `
import asyncio
await asyncio.sleep(2)
sum([i for i in range(100)])
`
result = await pyjs.async_exec_eval(py_code)
console.log(result);