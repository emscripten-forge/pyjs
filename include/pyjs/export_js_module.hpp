#include <pyjs/export_py_object.hpp>

namespace pyjs
{
namespace em = emscripten;

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

}

}