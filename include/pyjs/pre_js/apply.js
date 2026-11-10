
function isPromise(p) {
  try{
    if (
        p !== null &&
        typeof p === 'object' &&
        typeof p.then === 'function' &&
        typeof p.catch === 'function'
    ) {
        return true;
    }
  } catch (e) {
  }
  return false;
}



Module['_apply_try_catch'] = function(obj, args, is_generated_proxy) {
    // delete the argument proxies pyjs created for this call
    const delete_generated_proxies = () => {
        for (let i = 0; i < is_generated_proxy.length; ++i) {
            if (is_generated_proxy[i]) {
                args[i].delete();
            }
        }
    };
    try {
        let res = obj(...args);
        if (isPromise(res)) {
            // the arguments may be used until the promise settles. Both cases:
            // a fulfillment-only then() leaked them on rejection and created a
            // derived promise whose rejection nobody handled (an
            // `unhandledrejection` for every rejected promise, also awaited ones)
            res.then(delete_generated_proxies, delete_generated_proxies);
        } else {
            delete_generated_proxies();
        }
        return _wrap_return_value(res);
    } catch (e) {
        return _wrap_catched_error(e);
    }
}



Module['_gapply_try_catch'] = function(obj, args, is_generated_proxy, jin, jout) {
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
        const args = JSON.parse(jargs)
        return _wrap_return_value(obj(...args));
    } catch (e) {
        return _wrap_catched_error(e);
    }
}
