// JSPI (JavaScript Promise Integration) support: `pyjs.run_sync(promise)`.
// One build for all browsers: JSPI is used when the browser supports it
// (WebAssembly.Suspending / WebAssembly.promising), otherwise pyjs behaves as
// without it (`can_run_sync()` is False, `run_sync` raises).
//   - suspend point: the wasm import `pyjs_jspi_await` (src/export_js_proxy.cpp),
//     wrapped in WebAssembly.Suspending before instantiation if supported
//   - entry point: the wasm export `pyjs_raw_apply_promising`
//     (src/export_py_object.cpp), wrapped in WebAssembly.promising below
//
Module['_jspi_state'] = {
    supported: (typeof WebAssembly !== "undefined" &&
                typeof WebAssembly.Suspending === "function" &&
                typeof WebAssembly.promising === "function"),
    disabled: false,     // switched off at runtime (tests), see _jspi_disable
    can_suspend: false,  // innermost JS -> Python entry is a promising one
    suspended: false,    // a Python call stack is suspended in run_sync
    depth: 0             // number of active (not suspended) JS -> wasm entries
};

// JSPI is used (supported by the browser and not disabled)
Module['_jspi_enabled'] = function() {
    const st = Module._jspi_state;
    return st.supported && !st.disabled;
};

// switch JSPI off at runtime: pyjs then behaves like in a browser without JSPI
// (used by the tests to run the same build with and without JSPI)
Module['_jspi_disable'] = function() {
    Module._jspi_state.disabled = true;
};

Module['_jspi_can_run_sync'] = function() {
    const st = Module._jspi_state;
    return Module._jspi_enabled() && st.can_suspend && !st.suspended;
};

// awaited by the suspending import `pyjs_jspi_await` (src/export_js_proxy.cpp)
Module['_jspi_await'] = async function(promise) {
    const st = Module._jspi_state;
    st.suspended = true;
    st.depth -= 1;
    try {
        return _wrap_return_value(await promise);
    } catch (err) {
        return _wrap_catched_error(err);
    } finally {
        // resumed: back on the promising call stack
        st.suspended = false;
        st.depth += 1;
        st.can_suspend = true;
    }
};

Module['_jspi_install'] = function() {
    const st = Module._jspi_state;
    const proto = Module['pyobject'].prototype;

    // every synchronous JS -> Python entry: python must not suspend inside
    const wrap_sync = function(fn) {
        return function(...args) {
            const saved = st.can_suspend;
            st.can_suspend = false;
            st.depth += 1;
            try {
                return fn.apply(this, args);
            } finally {
                st.depth -= 1;
                st.can_suspend = saved;
            }
        };
    };
    const raw_methods = [
        '_raw_apply', '_raw_getitem', '_raw_getattr', '__call__',
        '__usafe_void_void__', '__usafe_void_val__', '__toPrimitive',
        'toString', 'toJSON', 'delete'
    ];
    for (const name of raw_methods) {
        if (typeof proto[name] === 'function') {
            proto[name] = wrap_sync(proto[name]);
        }
    }
    for (const name of ['_exec', '_eval', '_eval_file']) {
        Module[name] = wrap_sync(Module[name]);
    }

    const raw_apply_promising = WebAssembly.promising(wasmExports['pyjs_raw_apply_promising']);
    const raw_apply = proto['_raw_apply'];

    // like py_apply, but python may suspend (run_sync); returns a promise
    proto.py_apply_promising = async function(args = [], kwargs = {}) {
        const args_types = args.map(Module['_get_type_string']);
        const kwargs_keys = Object.keys(kwargs);
        const kwargs_values = Object.values(kwargs);
        const kwargs_values_types = kwargs_values.map(Module['_get_type_string']);
        const call_args = [args, args_types, args.length,
            kwargs_keys, kwargs_values, kwargs_values_types, kwargs_keys.length];

        let ret;
        if (st.disabled || st.depth > 0) {
            // JSPI switched off, or called from JS called from python:
            // no stack switching
            ret = raw_apply.apply(this, call_args);
        } else {
            const saved = st.can_suspend;
            st.can_suspend = true;
            st.depth += 1;
            // [this, ...call_args, result], see pyjs_raw_apply_promising
            const call = [this, ...call_args, undefined];
            let promise;
            try {
                promise = raw_apply_promising(Emval.toHandle(call));
            } finally {
                st.can_suspend = saved;
            }
            try {
                await promise;
            } finally {
                st.depth -= 1;
            }
            ret = call[8];
        }
        if (ret.has_err) {
            throw ret;
        }
        return ret['ret'];
    };
    proto.py_call_promising = function(...args) {
        return this.py_apply_promising(args);
    };
};

// once-callables for the event loop, python may suspend (fire and forget)
Module['_create_once_callable_promising_void_void'] = function(py_object) {
    let already_called = false;
    return function() {
        if (already_called) {
            throw new Error("once_callable can only be called once");
        }
        already_called = true;
        py_object.py_apply_promising([]).catch((err) => {
            console.error("error in python callback", err);
        }).finally(() => py_object.delete());
    };
};
