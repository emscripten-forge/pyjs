Module['make_proxy'] = function(py_object) {
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
