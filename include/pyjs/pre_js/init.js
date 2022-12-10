Module._is_initialized = false

Module['init'] = async function() {

    // list of python objects we need to delete when cleaning up
    let py_objects = []
    Module._py_objects = py_objects

    // return empty promise when already initialized
    if(Module["_is_initialized"])
    {
        console.log("INIT ALREADY DONE")

        return Promise.resolve();
    }
    var p = await Module['_wait_run_dependencies']();

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

    Module._is_initialized = true
    return p


}
