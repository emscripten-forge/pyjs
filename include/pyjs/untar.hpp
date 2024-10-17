#pragma once

#include <emscripten/bind.h>

namespace pyjs{
   
    em::val untar(const std::string &tar_path, const std::string &path);
    void untar_impl(FILE *a, const char *path, em::val & shared_libraraies);
}