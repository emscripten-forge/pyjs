#pragma once

#include <emscripten/bind.h>

namespace pyjs{
   
    em::val unzstd(const std::string &zstd_path, const std::string &path);

}