
function isPromise(p) {
  if (
    p !== null &&
    typeof p === 'object' &&
    typeof p.then === 'function' &&
    typeof p.catch === 'function'
  ) {
    return true;
  }

  return false;
}


Module['_apply_try_catch'] = function(obj, args, is_generated_proxy) {
    try {
        let res = obj(...args);
        if(isPromise(res)){
            res.then((value) => {
                for(let i=0; i<is_generated_proxy.length; ++i)
                {
                    if(is_generated_proxy[i]){
                        console.log("delete generated proxy in future",i)
                        is_generated_proxy[i].delete();
                    }
                }
            });
        }
        else{
            for(let i=0; i<is_generated_proxy.length; ++i)
            {
                if(is_generated_proxy[i]){
                    console.log("delete generated proxy",i)
                    is_generated_proxy[i].delete();
                }
            }
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
        args = JSON.parse(jargs)
        return _wrap_return_value(obj(...args));
    } catch (e) {
        return _wrap_catched_error(e);
    }
}
