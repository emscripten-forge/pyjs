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


Module['_create_once_callable'] = function(py_object){

    let already_called = false;

    var once_callable = function(... args){
        if (already_called) {
            throw new Error("once_callable can only be called once");
        }
        already_called = true;
        // make the call
        let ret = py_object.__call__(... args);
        
        // delete
        py_object.delete()

        return ret;
    }
    return once_callable
}