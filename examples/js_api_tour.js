// %% [markdown]
// # pyjs JavaScript API Tour
// Welcome to the tour of the pyjs JavaScript API. This notebook demonstrates how to use the PYJS JavaScript API to run Python code in the browser.

// %% [markdown]
// # Loading the pyjs module

// %% [code]
// load the pyjs runtime by importing the pyjs_runtime_browser.js file
// the url differs depending on the deployment
importScripts("../../../../xeus/bin/pyjs_runtime_browser.js");

// the locateFile function is used to locate the wasm file
// which sits next to the pyjs_runtime_browser.js file 
// in thism deployment
let locateFile = function(filename){
    if(filename.endsWith('pyjs_runtime_browser.wasm')){
        return `../../../../xeus/bin/pyjs_runtime_browser.wasm`;
    }
};

// the createModule function in from the pyjs runtime
// is used to create the pyjs module
let pyjs = await createModule({locateFile:locateFile});

// load the python packages (includung the python standard library)
// from the empack environment 
packages_json_url = "../../../../xeus/kernels/xpython/empack_env_meta.json"
package_tarballs_root_url = "../../../../xeus/kernel_packages/"          
await pyjs.bootstrap_from_empack_packed_environment(
    packages_json_url,
    package_tarballs_root_url
);


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