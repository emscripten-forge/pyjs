Module['_is_null'] = function(value) {
    return value === null;
}

Module['_is_undefined'] = function(value) {
    return value === undefined;
}

Module['_is_undefined_or_null'] = function(value) {
    return value === undefined || value === null;
}

Module["__len__"] = function(instance) {
    return instance.length || instance.size
}

Module["__contains__"] = function(instance, query) {
    let _has = false;
    let _includes = false;
    try {
        _has = instance.has(query);
    } catch (e) {}
    try {
        _has = instance.includes(query);
    } catch (e) {}
    return _has || _includes;
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
