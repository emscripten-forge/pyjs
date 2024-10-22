
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <string>
#include <fstream>
#include <iostream>

#include <filesystem>

#include <pyjs/inflate.hpp>
#include <pyjs/untar.hpp>
#include <zstd.h>

#include <emscripten/bind.h>

namespace em = emscripten;
namespace fs = std::filesystem;
namespace pyjs
{

    bool decompress_zstd(const fs::path& inputFile, const fs::path& outputFile)
    {
        const int CHUNK_SIZE = 16384;
        // Open input and output files
        std::ifstream fin(inputFile, std::ios::binary);
        std::ofstream fout(outputFile, std::ios::binary);

        if (!fin.is_open() || !fout.is_open())
        {
            std::cerr << "Failed to open input or output file!" << std::endl;
            return false;
        }

        // Create a Zstd decompression context
        ZSTD_DCtx* dctx = ZSTD_createDCtx();
        if (!dctx)
        {
            std::cerr << "Failed to create ZSTD decompression context!" << std::endl;
            return false;
        }

        // Allocate buffers for input and output
        std::vector<char> in_buffer(CHUNK_SIZE);
        std::vector<char> out_buffer(CHUNK_SIZE);

        size_t read_bytes = 0;
        size_t result = 0;

        // Decompress the file chunk by chunk
        while (fin.read(in_buffer.data(), CHUNK_SIZE) || fin.gcount() > 0)
        {
            read_bytes = fin.gcount();
            const char* src = in_buffer.data();

            // Stream decompression
            while (read_bytes > 0)
            {
                ZSTD_inBuffer input = { src, read_bytes, 0 };
                ZSTD_outBuffer output = { out_buffer.data(), out_buffer.size(), 0 };

                result = ZSTD_decompressStream(dctx, &output, &input);

                if (ZSTD_isError(result))
                {
                    std::cerr << "Decompression error: " << ZSTD_getErrorName(result) << std::endl;
                    ZSTD_freeDCtx(dctx);
                    return false;
                }

                fout.write(out_buffer.data(), output.pos);
                read_bytes -= input.pos;
                src += input.pos;
            }
        }

        // Clean up
        ZSTD_freeDCtx(dctx);
        return true;
    }

    bool merge_directories(fs::path& source_path, fs::path& destination_path)
    {
        try
        {
            if (!fs::exists(source_path) || !fs::is_directory(source_path))
            {
                return false;
            }

            // Create the destination directory if it doesn't exist
            if (!fs::exists(destination_path))
            {
                fs::create_directories(destination_path);
            }

            // Iterate through the source directory recursively
            for (const auto& entry : fs::recursive_directory_iterator(source_path))
            {
                const fs::path& source_entry_path = entry.path();
                fs::path destination_entry_path
                    = destination_path / fs::relative(source_entry_path, source_path);

                if (fs::is_directory(source_entry_path))
                {
                    // Create directories in the destination if they don't exist
                    if (!fs::exists(destination_entry_path))
                    {
                        fs::create_directory(destination_entry_path);
                    }
                }
                else if (fs::is_regular_file(source_entry_path))
                {
                    // Copy/replace files from source to destination
                    fs::copy_file(source_entry_path,
                                  destination_entry_path,
                                  fs::copy_options::overwrite_existing);
                }
            }

            fs::remove_all(source_path);

            return true;
        }
        catch (const fs::filesystem_error& e)
        {
            std::cerr << "Filesystem error: " << e.what() << std::endl;
            return false;
        }
    }


    em::val install_conda_file(const std::string& zstd_file_path,
                               const std::string& working_dir,
                               const std::string& prefix)
    {
        auto output = em::val::array();
        fs::path output_dir(working_dir);
        fs::path zstd_path(zstd_file_path);
        fs::path output_file = output_dir / "pkg.tar";

        bool success = decompress_zstd(zstd_path, output_file);
        if (!success)
        {
            return output;
        }
        FILE* output_file_ptr = fopen(output_file.c_str(), "r");

        untar_impl(output_file_ptr, output_dir.c_str(), output);

        std::vector<std::string> dir_names = { "etc", "share" };
        for (size_t i = 0; i < dir_names.size(); i++)
        {
            auto source_dir_path = output_dir / fs::path(dir_names[i]);
            auto dest_dir_path = fs::path(dir_names[i]);
            merge_directories(source_dir_path, dest_dir_path);
        }

        auto site_packages_dir_path = output_dir / "site-packages";
        if (fs::exists(site_packages_dir_path))
        {
            auto site_packages_dest = fs::path(prefix) / "lib/python3.11/site-packages";
            bool check = merge_directories(site_packages_dir_path, site_packages_dest);
            if (!check)
            {
                std::cerr << " Failed to copy package to site-packages directory: "
                          << site_packages_dir_path << std::endl;
            }
        }
        std::fclose(output_file_ptr);
        fs::remove_all(output_dir);
        return output;
    }
}