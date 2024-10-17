
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <string>
#include <fstream>
#include <iostream>
#include <streambuf>

/* This is for mkdir(); this may need to be changed for some platforms. */
#include <sys/stat.h> /* For mkdir() */
#include <filesystem>

#include <pyjs/inflate.hpp>
#include <pyjs/untar.hpp>
#include <zstd.h>

#include <emscripten/bind.h>

namespace em = emscripten;

namespace pyjs
{

    bool decompressZstdStream(const std::string& inputFile, const std::string& outputFile)
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
        std::vector<char> inBuffer(CHUNK_SIZE);
        std::vector<char> outBuffer(CHUNK_SIZE);

        size_t readBytes = 0;
        size_t result = 0;

        // Decompress the file chunk by chunk
        while (fin.read(inBuffer.data(), CHUNK_SIZE) || fin.gcount() > 0)
        {
            readBytes = fin.gcount();  // How many bytes were actually read
            const char* src = inBuffer.data();

            // Stream decompression
            while (readBytes > 0)
            {
                ZSTD_inBuffer input = { src, readBytes, 0 };
                ZSTD_outBuffer output = { outBuffer.data(), outBuffer.size(), 0 };

                result = ZSTD_decompressStream(dctx, &output, &input);

                if (ZSTD_isError(result))
                {
                    std::cerr << "Decompression error: " << ZSTD_getErrorName(result) << std::endl;
                    ZSTD_freeDCtx(dctx);
                    return false;
                }

                // Write the decompressed data to the output file
                fout.write(outBuffer.data(), output.pos);

                // Move input pointer forward by how much was consumed
                readBytes -= input.pos;
                src += input.pos;
            }
        }

        // Clean up
        ZSTD_freeDCtx(dctx);
        std::cout << "Streaming decompression completed!" << std::endl;
        return true;
    }

    em::val unzstd(const std::string& zstd_path, const std::string& path)
    {
        auto output = em::val::array();
        std::string outputFile = "/conda_packages/ipyflex/pkg.tar";

        std::cout << " PROCESSING IN CPP " << zstd_path << std::endl;


        bool res = decompressZstdStream(zstd_path, outputFile);
        std::cout << " File created " << outputFile << std::endl;


        return output;
    }
}