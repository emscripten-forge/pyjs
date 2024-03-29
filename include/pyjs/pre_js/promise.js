
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

Module['_future_to_promise'] = function(py_future){
    let p  = new Promise(function(resolve, reject) {
        Module._add_resolve_done_callback.py_call(py_future, resolve, reject)
    });

    p.then(function(value) {
        py_future.delete()
      }, function(reason) {
        py_future.delete()
    });
    return p;
}