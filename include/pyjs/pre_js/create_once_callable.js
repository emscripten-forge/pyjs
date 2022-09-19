
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
