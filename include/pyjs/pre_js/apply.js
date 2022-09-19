
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
