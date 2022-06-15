#include <pyjs/export_py_object.hpp>


#include <pybind11/embed.h> 
#include <emscripten/bind.h>



namespace pyjs
{
namespace em = emscripten;


int n_unfinished()
{
    try{
        py::object scope = py::module_::import("__main__").attr("__dict__");
        py::module_ asyncio = py::module_::import("asyncio");
        return asyncio.attr("get_event_loop")().attr("_n_unfinished").cast<int>();
    }
    catch (py::error_already_set& e)
    {
        std::cout<<"error: "<<e.what()<<"\n";
        return 0;
    }
}




void export_js_module()
{
    export_py_object();

    em::function("cout", 
        em::select_overload<void(const std::string &)>(
            [](const std::string & val )
            {
               std::cout<<val;
            }
        )
    );
    
    em::function("n_unfinished", &n_unfinished);






}

}