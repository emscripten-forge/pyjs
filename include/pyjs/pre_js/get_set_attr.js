
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
