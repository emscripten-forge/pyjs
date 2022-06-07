// public functions


//  private functions
function _make_error(e){
    const err_obj = {
        __pyjs__error__: e
    }
    return err_obj
}


Module['_apply_try_catch'] =  function(val, self, args){
    try {

        return val.apply( self, args)
    }
    catch(e)
    {
        return _make_error(e)
    }
}


Module['_getattr_try_catch'] =  function(obj, property_name){
    try {

        return obj[property_name]
    }
    catch(e)
    {
        return _make_error(e)
    }
}


Module['_setattr_try_catch'] =  function(obj, property_name, value){
    try {

        return obj[property_name] = value
    }
    catch(e)
    {
        return _make_error(e)
    }
}


Module['_new'] = function(cls, ...args){
    return new cls(... args);
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


Module['_instanceof'] = function(instance, cls){
    return (instance instanceof cls);
}


Module["__len__"] = function(instance){
    return instance.length || instance.size
}


Module["__contains__"] = function(instance, query){
    var _has = false;
    var _includes = false;
    try{
      _has  = instance.has(query);
    }
    catch(e){
    }
    try{
      _has  = instance.includes(query);
    }
    catch(e){
    }
    return _has  || _includes;
}


Module["__eq__"] = function(a, b){
    return a === b;
}


Module['_dir'] = function dir(x) {
  let result = [];
  do {
    result.push(...Object.getOwnPropertyNames(x));
  } while ((x = Object.getPrototypeOf(x)));
  return result;
}


Module['_iter'] = function dir(x) {
    return x[Symbol.iterator]()
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
        let ret = py_object.__callme__(... args);
        
        // delete
        py_object.delete()

        console.log("return")

        return ret;
    }
    return once_callable
}


Module["_typeof"] = function(x){
    return typeof x;
}


Module["_delete"] = function(x,key){
    delete x[key];
}


Module["_delitem"] = function(x,key){
    delete x[key];
}


Module['_IS_NODE'] = (typeof process === "object" && typeof require === "function") 


Module['_IS_BROWSER_WORKER_THREAD'] = (typeof importScripts === "function")


Module['_IS_BROWSER_MAIN_THREAD'] = (typeof window === "object")