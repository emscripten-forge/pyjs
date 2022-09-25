
Module['cleanup'] = function()
{
    if(Module["_is_initialized"])
    {
        Module['_py_objects'].forEach(pyobject => pyobject.delete())
        Module["_is_initialized"] = false
    }
}
