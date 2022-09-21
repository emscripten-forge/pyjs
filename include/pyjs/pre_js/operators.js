Module['_async_import_javascript'] = async function(import_str){
    return import(import_str);
}

Module["__eq__"] = function(a, b) {
    return a === b;
}

Module['_new'] = function(cls, ...args) {
    return new cls(...args);
}

Module['_instanceof'] = function(instance, cls) {
    return (instance instanceof cls);
}

Module["_typeof"] = function(x) {
    return typeof x;
}

Module["_delete"] = function(x, key) {
    delete x[key];
}
