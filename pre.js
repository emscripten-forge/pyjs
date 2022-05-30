Module['_apply_try_catch'] =  function(val, self, args){
    try {

        return val.apply( self, args)
    }
    catch(e)
    {
        const err_obj = {
            __pyjs__error__: e
        }
        return err_obj
    }
}

Module['_getattr_try_catch'] =  function(obj, property_name){
    try {

        return obj[property_name]
    }
    catch(e)
    {
        const err_obj = {
            __pyjs__error__: e
        }
        return err_obj
    }
}


Module['_setattr_try_catch'] =  function(obj, property_name, value){
    try {

        return obj[property_name] = value
    }
    catch(e)
    {
        const err_obj = {
            __pyjs__error__: e
        }
        return err_obj
    }
}

Module['_call_py_object_variadic'] = function(py_val, ...args){
    return py_val['__call_variadic__'](args);
} 

Module['_is_null'] = function(value){
    return value === null;
}

Module['_is_undefined'] = function(value){
    return value === undefined;
}

Module['_is_undefined_or_null'] = function(value){
    return value === undefined || value === null;
}

Module['_is_object'] = function(value){
    return typeof value === 'object' && value !== null;
}

Module['_is_array'] = function(value){
    return Array.isArray(value);
}

Module['_is_number'] = function(value){
    return typeof value === 'number'
}

Module['_is_integer'] = function(value){
    if(value === undefined || value === null)
    {
        return False;
    }
    else{
        return  Number.isInteger(value);
    }
}
Module['_is_boolean'] = function(value){
    return typeof value === 'boolean'
}

Module['_is_string'] = function(value){
    return typeof value === 'string'
}

Module['_instanceof'] = function(instance, cls){
    return (instance instanceof cls);
}

Module['_is_typed_array'] = function(instance){
    return ArrayBuffer.isView(instance) && !(instance instanceof DataView)
}




Module['_get_type_string'] = function(instance){
    if(instance === null){
        return "null"
    }
    else if(instance === undefined){
        return "undefined"
    }
    else
    {
        const type = typeof instance;
        
        if( type === "object")
        {   
            const constructor = instance.constructor;
            if( constructor !== undefined)
            {
                return constructor.name
            }
            return "object"
        }
        else if(type === "string")
        {
            return "string"
        }
        else if(type === "number")
        {
            if(Number.isInteger(instance))
            {
                return "integer"
            }
            else
            {
                return "float"
            }
        }
        else if(type === "boolean")
        {
            return "boolean"
        }
        else if(type === "function")
        {
            return "function"
        }
        else
        {
            return "__error__unkown_type__" + type;
        }
    }
}


/**
 * This function allow you to modify a JS Promise by adding some status properties.
 * Based on: http://stackoverflow.com/questions/21485545/is-there-a-way-to-tell-if-an-es6-promise-is-fulfilled-rejected-resolved
 * But modified according to the specs of promises : https://promisesaplus.com/
 */
Module['_MakeQuerablePromise'] = function(promise) {
    // Don't modify any promise that has been already modified.
    if (promise.isFulfilled) return promise;

    // Set initial state
    var isPending = true;
    var isRejected = false;
    var isFulfilled = false;

    // Observe the promise, saving the fulfillment in a closure scope.
    var result = promise.then(
        function(v) {
            isFulfilled = true;
            isPending = false;
            return v; 
        }, 
        function(e) {
            isRejected = true;
            isPending = false;
            throw e; 
        }
    );

    result.isFulfilled = function() { return isFulfilled; };
    result.isPending = function() { return isPending; };
    result.isRejected = function() { return isRejected; };
    return result;
}


Module["_parseGetAllResponseHeaders"] = function(request){
    var allResponseHeaders = request.getAllResponseHeaders()
    var arr = allResponseHeaders.split("\r\n");
    var headers = {};
    allResponseHeaders
      .trim()
      .split(/[\r\n]+/)
      .map(value => value.split(/: /))
      .forEach(keyValue => {
        headers[keyValue[0].trim()] = keyValue[1].trim();
      });
    return headers
}