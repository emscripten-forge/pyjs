Module['make_proxy'] = function(py_object) {
    const handler = {
        get(target, property, receiver) {
            var ret = target[property]
            if (ret !== undefined) {
                return ret
            }
            // python attribute names are strings, so symbols cannot be passed to _getattr
            if (typeof property === 'symbol') {
                if (property === Symbol.iterator && Module._py_is_iterable.py_call(target)) {
                    return function() {
                        return Module._py_object_iterator(target)
                    }
                }
                return undefined
            }
            return target._getattr(property);
        }
    };

    return new Proxy(py_object, handler);
}

// JavaScript iterator over an iterable python object
Module['_py_object_iterator'] = function(py_object) {
    // returned by _py_next when the python iterator is exhausted
    const done = {}
    let py_iter = Module._py_iter.py_call(py_object)
    return {
        next() {
            if (py_iter === null) {
                return { done: true, value: undefined }
            }
            const value = Module._py_next.py_call(py_iter, done)
            if (value === done) {
                py_iter.delete()
                py_iter = null
                return { done: true, value: undefined }
            }
            return { done: false, value: value }
        },
        [Symbol.iterator]() {
            return this
        }
    }
}
