Module._is_initialized = false



Module['init'] = async function(prefix, python_version) {

    let version_str = `${python_version[0]}.${python_version[1]}`;

    // list of python objects we need to delete when cleaning up
    let py_objects = []
    Module._py_objects = py_objects

    // return empty promise when already initialized
    if(Module["_is_initialized"])
    {
        return Promise.resolve();
    }
    var p = await Module['_wait_run_dependencies']();

    if(prefix == "/"){
        Module.setenv("PYTHONHOME", `/`);
        Module.setenv("PYTHONPATH", `/lib/python${version_str}/site-packages:/usr/lib/python${version_str}`);

        var side_path = `/lib/python${version_str}/site-packages`;
    }
    else{
        Module.setenv("PYTHONHOME", prefix);
        Module.setenv("PYTHONPATH", `${prefix}/lib/python${version_str}/site-packages:/usr/lib/python${version_str}`);
        var side_path = `${prefix}/lib/python${version_str}/site-packages`;
    }

    console.log('Module  is', Module)
    console.log('Module FS is', Module.FS)

    //if(!Module.FS.isDir(side_path)){
        Module.FS.mkdir(side_path);
   //}

    Module["_interpreter"] = new Module["_Interpreter"]()
    var default_scope = Module["main_scope"]()
    Module["default_scope"] = default_scope;

    Module['_py_objects'].push(Module["default_scope"]);
    Module['_py_objects'].push(Module["_interpreter"]);



    Module['exec'] = function(code, globals=default_scope, locals=default_scope) {
        let ret = Module._exec(code, globals, locals)
        if (ret.has_err) {
            throw ret
        }
    };



    Module['eval'] = function(code, globals=default_scope, locals=default_scope) {
        let ret = Module._eval(code, globals, locals)
        if (ret.has_err) {
            throw ret
        } else {
            return ret['ret']
        }
    };

    Module['eval_file'] = function(file, globals=default_scope, locals=default_scope) {
        let ret = Module._eval_file(file, globals, locals)
        if (ret.has_err) {
            throw ret
        }
    };

    Module['pyobject'].prototype._getattr = function(attr_name) {
        let ret = this._raw_getattr(attr_name)
        if (ret.has_err) {
            throw ret
        } else {
            return ret['ret']
        }
    };

    Module['pyobject'].prototype.py_call = function(...args) {
        return this.py_apply(args)
    };

    Module['pyobject'].prototype.py_apply = function(args, kwargs) {

        if (args === undefined) {
            var args = []
            var args_types = []
        }
        else
        {
            var args_types = args.map(Module['_get_type_string'])
        }

        if (kwargs === undefined) {
            var kwargs = {}
            var kwargs_keys = []
            var kwargs_values = []
            var kwarg_values_types = []
        }
        else
        {
            var kwargs_keys = Object.keys(kwargs)
            var kwargs_values = Object.values(kwargs)
            var kwarg_values_types = kwargs_values.map(Module['_get_type_string'])
        }

        let ret = this._raw_apply(args, args_types, args.length,
            kwargs_keys, kwargs_values, kwarg_values_types, kwargs_keys.length
        )
        if (ret.has_err) {
            throw ret
        } else {
            return ret['ret']
        }
    };






    Module['pyobject'].prototype.get = function(...keys) {


        let types = keys.map(Module['_get_type_string'])
        let ret = this._raw_getitem(keys, types, keys.length)
        if (ret.has_err) {
            throw ret
        } else {
            return ret['ret']
        }
    };



    // make the python pyjs module easy available
    Module.exec("import pyjs");
    Module.py_pyjs = Module.eval("pyjs")
    py_objects.push(Module.py_pyjs);


    // execute a script and return the value of the last expression
    Module._py_exec_eval = Module.eval("pyjs.exec_eval")
    py_objects.push(Module._py_exec_eval)
    Module.exec_eval = function(script, globals=default_scope, locals=default_scope){
        return Module._py_exec_eval.py_call(script, globals, locals)
    }

    // ansync execute a script and return the value of the last expression
    Module._py_async_exec_eval = Module.eval("pyjs.async_exec_eval")
    py_objects.push(Module._py_async_exec_eval)
    Module.async_exec_eval = async function(script, globals=default_scope, locals=default_scope){
        return await Module._py_async_exec_eval.py_call(script, globals, locals)
    }

    Module._add_resolve_done_callback  = Module.exec_eval(`
import asyncio
def _add_resolve_done_callback(future, resolve, reject):
    ensured_future = asyncio.ensure_future(future)
    def done(f):
        try:
            resolve(f.result())
        except Exception as err:
            reject(repr(err))

    ensured_future.add_done_callback(done)
_add_resolve_done_callback
    `)
    py_objects.push(Module._add_resolve_done_callback);



    Module._py_to_js = Module.eval("pyjs.to_js")
    py_objects.push(Module._py_to_js);

    Module["to_js"] = function(obj){
        return Module._py_to_js.py_call(obj)
    }

    Module._is_initialized = true;

    // Mock some system libraries
    Module.exec(`
import sys
import types
import time

sys.modules["fcntl"] = types.ModuleType("fcntl")
sys.modules["pexpect"] = types.ModuleType("pexpect")
sys.modules["resource"] = types.ModuleType("resource")

def _mock_time_sleep():
    def sleep(seconds):
        """Delay execution for a given number of seconds.  The argument may be
        a floating point number for subsecond precision.
        """
        start = now = time.time()
        while now - start < seconds:
            now = time.time()

    time.sleep = sleep
_mock_time_sleep()
del _mock_time_sleep

def _mock_termios():
    termios_mock = types.ModuleType("termios")
    termios_mock.TCSAFLUSH = 2
    sys.modules["termios"] = termios_mock
_mock_termios()
del _mock_termios

def _mock_webbrowser():
    def open(url, new=0, autoraise=True):
        pass
    def open_new(url):
        return open(url, 1)
    def open_new_tab(url):
        return open(url, 2)

    webbrowser_mock = types.ModuleType("webbrowser")
    webbrowser_mock.open = open
    webbrowser_mock.open_new = open_new
    webbrowser_mock.open_new_tab = open_new_tab

    sys.modules["webbrowser"] = webbrowser_mock
_mock_webbrowser()
del _mock_webbrowser
`);

    return p;
}
