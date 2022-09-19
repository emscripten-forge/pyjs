Module["_is_initialized"] = false

Module['init'] = async function() {


    // return empty promise when already initialized
    if(Module["_is_initialized"])
    {
        return Promise.resolve();
    }

    var p = await Module['_wait_run_dependencies']();

    Module["_interpreter"] = new Module["_Interpreter"]()
    var default_scope = Module["main_scope"]()
    Module["default_scope"] = default_scope



    Module['exec'] = function(code, scope=default_scope) {
        let ret = Module._exec(code, scope)
        if (ret.has_err) {
            throw ret
        }
    };

    Module['eval'] = function(code, scope=default_scope) {
        let ret = Module._eval(code, scope)
        if (ret.has_err) {
            throw ret
        } else {
            return ret['ret']
        }
    };

    Module['eval_file'] = function(file, scope=default_scope) {
        let ret = Module._eval_file(file, scope)
        if (ret.has_err) {
            throw ret
        }
    };

    Module['pyobject'].prototype.py_call_async = function(...args) {
        return this.py_apply_async(args)
    };

    Module['pyobject'].prototype.py_apply_async = function(args, kwargs) {
        let py_future = this.py_apply(args, kwargs)

        let p  = new Promise(function(resolve, reject) {
            Module._add_resolve_done_callback.py_call(py_future, resolve, reject)
        });

        p.then(function(value) {
            py_future.delete()
          }, function(reason) {
            py_future.delete()
        });
        return p;
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

    Module['pyobject'].prototype.py_getitem = function(...keys) {


        let types = keys.map(Module['_get_type_string'])
        let ret = this._raw_getitem(keys, types, keys.length)
        if (ret.has_err) {
            throw ret
        } else {
            return ret['ret']
        }
    };

    Module._add_resolve_done_callback = Module.eval("pyjs._add_resolve_done_callback")

    return p
}
