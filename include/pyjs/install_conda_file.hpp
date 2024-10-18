#pragma once

#include <emscripten/bind.h>

namespace pyjs
{

    em::val install_conda_file(const std::string& zstd_file_path,
                               const std::string& working_dir,
                               const std::string& path);

}