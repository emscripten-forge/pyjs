// public functions


//  private functions
function _make_error(e) {
	const err_obj = {
		__pyjs__error__: e
	}
	return err_obj
}

const _NULL = "0"
const _UNDEFINED = "1"
const _OBJECT = "2"
const _STR = "3"
const _INT = "4"
const _FLOAT = "5"
const _BOOL = "6"
const _FUNCTION = "7"




Module['py_apply'] = function(py_object, args, kwargs) {

}


Module['make_proxy'] = function(py_object) {
	// return py_object;
	const handler = {
		get(target, property, receiver) {
			var ret = target[property]
			if (ret !== undefined) {
				return ret
			}
			return target._getattr(property);
		}
	};

	return new Proxy(py_object, handler);
}


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
		ret = Module._exec(code, scope)
		if (ret.has_err) {
			throw ret
		}
	};

	Module['eval'] = function(code, scope=default_scope) {
		ret = Module._eval(code, scope)
		if (ret.has_err) {
			throw ret
		} else {
			return ret['ret']
		}
	};

	Module['eval_file'] = function(file, scope=default_scope) {
		ret = Module._eval_file(file, scope)
		if (ret.has_err) {
			throw ret
		}
	};



    Module['pyobject'].prototype.py_call_async = function(...args) {
        return this.py_apply_async(args)
    };


    Module['pyobject'].prototype.py_apply_async = function(args, kwargs) {
        var afut0 = this.py_apply(args, kwargs)
        var fensure_future = Module.eval("asyncio.ensure_future")
        var afut1 = fensure_future.py_call(afut0)
        var add_done_cb = Module.eval("pyjs._add_resolve_done_callback")


        p  = new Promise(function(resolve, reject) {
            add_done_cb.py_call(afut1, resolve, reject)
        });

        p.then(function(value) {
            afut0.delete()
            fensure_future.delete()
            afut1.delete()
            add_done_cb.delete()
          }, function(reason) {
            afut0.delete()
            fensure_future.delete()
            afut1.delete()
            add_done_cb.delete()
        });
        return p;
    };


	Module['pyobject'].prototype._getattr = function(attr_name) {
		ret = this._raw_getattr(attr_name)
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
			args = []
			var args_types = []
		}
		else
		{
			var args_types = args.map(Module['_get_type_string'])
		}

		if (kwargs === undefined) {
			kwargs = {}
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



		ret = this._raw_apply(args, args_types, args.length,
			kwargs_keys, kwargs_values, kwarg_values_types, kwargs_keys.length
		)
		if (ret.has_err) {
			throw ret
		} else {
			return ret['ret']
		}
	};

	Module['pyobject'].prototype.py_getitem = function(...keys) {


		types = keys.map(Module['_get_type_string'])
		ret = this._raw_getitem(keys, types, keys.length)
		if (ret.has_err) {
			throw ret
		} else {
			return ret['ret']
		}
	};

	return p
}

Module['cleanup'] = function()
{
	if(Module["_is_initialized"])
	{
		Module['default_scope'].delete()
		Module['_interpreter'].delete()
		Module["_is_initialized"] = false
	}
}




function _get_type_string(instance) {
	if (instance === null) {
		return _NULL
	} else if (instance === undefined) {
		return _UNDEFINED
	} else {
		const type = typeof instance;

		if (type === "object") {
			const constructor = instance.constructor;
			if (constructor !== undefined) {
				return constructor.name
			}
			return _OBJECT
		} else if (type === "string") {
			return _STR
		} else if (type === "number") {
			if (Number.isInteger(instance)) {
				return _INT
			} else {
				return _FLOAT
			}
		} else if (type === "boolean") {
			return _BOOL
		} else if (type === "function") {
			return _FUNCTION
		} else {
			console.log(instance, "is unhandled type")
			throw Error("internal error -- this should be unreachable")
		}
	}
}


function _wrap_void_result() {
	return {
		has_err: false,
		has_ret: false
	}
}

function _wrap_return_value(raw_ret) {
	const is_none = (raw_ret === undefined || raw_ret === null);
	let wret = {
		ret: raw_ret,
		has_err: false,
		has_ret: !is_none,
		type_string: _get_type_string(raw_ret)
	}
	return wret;
}


function _wrap_jreturn_value(raw_ret) {
	if (raw_ret === undefined) {
		return {
			ret: "",
			has_err: false
		}
	} else {
		return {
			ret: JSON.stringify(raw_ret),
			has_err: false
		}
	}
}





function _wrap_catched_error(err) {
	return {
		err: err,
		has_err: true,
		has_ret: false
	}
}


Module['_apply_try_catch'] = function(obj, args) {
	try {
		return _wrap_return_value(obj(...args));
	} catch (e) {
		return _wrap_catched_error(e);
	}
}



Module['_gapply_try_catch'] = function(obj, args, jin, jout) {
	try {
		if (jin) {
			args = JSON.parse(args)
		}
		if (jout) {
			return _wrap_jreturn_value(obj(...args));
		} else {
			return _wrap_return_value(obj(...args));
		}
	} catch (e) {
		return _wrap_catched_error(e);
	}
}




Module['_japply_try_catch'] = function(obj, jargs) {
	try {
		args = JSON.parse(jargs)
		return _wrap_return_value(obj(...args));
	} catch (e) {
		return _wrap_catched_error(e);
	}
}


Module['_getattr_try_catch'] = function(obj, property_name) {
	try {
		let ret = obj[property_name]
		if (typeof ret === "function") {
			return _wrap_return_value(ret.bind(obj))
		} else {
			return _wrap_return_value(ret)
		}
	} catch (e) {
		return _wrap_catched_error(e)
	}
}
Module['_setattr_try_catch'] = function(obj, property_name, value) {
	try {

		obj[property_name] = value
		return _wrap_void_result()
	} catch (e) {
		return _wrap_catched_error(e)
	}
}



Module['_new'] = function(cls, ...args) {
	return new cls(...args);
}


Module['_call_py_object_variadic'] = function(py_val, ...args) {
	return py_val['__call_variadic__'](args);
}


Module['_is_null'] = function(value) {
	return value === null;
}


Module['_is_undefined'] = function(value) {
	return value === undefined;
}


Module['_is_undefined_or_null'] = function(value) {
	return value === undefined || value === null;
}


Module['_instanceof'] = function(instance, cls) {
	return (instance instanceof cls);
}


Module["__len__"] = function(instance) {
	return instance.length || instance.size
}


Module["__contains__"] = function(instance, query) {
	var _has = false;
	var _includes = false;
	try {
		_has = instance.has(query);
	} catch (e) {}
	try {
		_has = instance.includes(query);
	} catch (e) {}
	return _has || _includes;
}


Module["__eq__"] = function(a, b) {
	return a === b;
}


Module['_dir'] = function dir(x) {
	let result = [];
	do {
		result.push(...Object.getOwnPropertyNames(x));
	} while ((x = Object.getPrototypeOf(x)));
	return result;
}


Module['_iter'] = function dir(x) {
	return x[Symbol.iterator]()
}

Module['_get_type_string'] = _get_type_string



Module['_create_once_callable'] = function(py_object) {

	let already_called = false;

	var once_callable = function(...args) {
		if (already_called) {
			throw new Error("once_callable can only be called once");
		}
		already_called = true;

		// make the call
		ret = py_object.__call__(...args);

		// delete
		py_object.delete()

		console.log("return")

		return ret;
	}
	return once_callable
}

Module['_set_promise_then_catch'] = function(promise, py_object_then, py_object_catch) {

	let already_called = false;

	var callable_then = function(v) {

		py_object_then.__usafe_void_val__(v);

		// delete
		py_object_then.delete()
		py_object_catch.delete()
	}
	var callable_catch = function(err) {

		str_err = JSON.stringify(err, Object.getOwnPropertyNames(err))
		py_object_catch.__usafe_void_val__(str_err);

		// delete
		py_object_then.delete()
		py_object_catch.delete()
	}
	promise.then(callable_then).catch(callable_catch)
}

Module['_create_once_callable_unsave_void_void'] = function(py_object) {

	let already_called = false;

	var once_callable = function() {
		if (already_called) {
			throw new Error("once_callable can only be called once");
		}
		already_called = true;

		// make the call
		py_object.__usafe_void_void__();

		// delete
		py_object.delete()
	}
	return once_callable
}

Module["_typeof"] = function(x) {
	return typeof x;
}

Module["_delete"] = function(x, key) {
	delete x[key];
}

Module['_IS_NODE'] = (typeof process === "object" && typeof require === "function")

Module['_IS_BROWSER_WORKER_THREAD'] = (typeof importScripts === "function")

Module['_IS_BROWSER_MAIN_THREAD'] = (typeof window === "object")


function _wait_run_dependencies() {
	const promise = new Promise((r) => {
		Module.monitorRunDependencies = (n) => {
			if (n === 0) {
				r();
			}
		};
	});
	Module.addRunDependency("dummy");
	Module.removeRunDependency("dummy");
	return promise;
}

Module['_wait_run_dependencies'] = _wait_run_dependencies
