
Module['cleanup'] = function()
{
    if(Module["_is_initialized"])
    {
        Module['default_scope'].delete()
        Module['_interpreter'].delete()
        Module._add_resolve_done_callback .delete()
        Module["_is_initialized"] = false
    }
}
