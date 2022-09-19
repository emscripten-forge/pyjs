
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
