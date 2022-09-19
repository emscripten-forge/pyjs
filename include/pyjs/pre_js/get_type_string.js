function _get_type_string(instance) {
    if (instance === null) {
        return _NULL
    } else if (instance === undefined) {
        return _UNDEFINED
    } else {
        const type = typeof instance;

        if (type === "object") {
            const constructor = instance.constructor;
            if (constructor !== undefined) {
                return constructor.name
            }
            return _OBJECT
        } else if (type === "string") {
            return _STR
        } else if (type === "number") {
            if (Number.isInteger(instance)) {
                return _INT
            } else {
                return _FLOAT
            }
        } else if (type === "boolean") {
            return _BOOL
        } else if (type === "function") {
            return _FUNCTION
        } else {
            console.log(instance, "is unhandled type")
            throw Error("internal error -- this should be unreachable")
        }
    }
}

Module['_get_type_string'] = _get_type_string
