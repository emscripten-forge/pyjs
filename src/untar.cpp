// from https://github.com/libarchive/libarchive/blob/master/contrib/untar.c
/*
 * This file is in the public domain.  Use it as you see fit.
 */

/*
 * "untar" is an extremely simple tar extractor:
 *  * A single C source file, so it should be easy to compile
 *    and run on any system with a C compiler.
 *  * Extremely portable standard C.  The only non-ANSI function
 *    used is mkdir().
 *  * Reads basic ustar tar archives.
 *  * Does not require libarchive or any other special library.
 *
 * To compile: cc -o untar untar.c
 *
 * Usage:  untar <archive>
 *
 * In particular, this program should be sufficient to extract the
 * distribution for libarchive, allowing people to bootstrap
 * libarchive on systems that do not already have a tar program.
 *
 * To unpack libarchive-x.y.z.tar.gz:
 *    * gunzip libarchive-x.y.z.tar.gz
 *    * untar libarchive-x.y.z.tar
 *
 * Written by Tim Kientzle, March 2009.
 *
 * Released into the public domain.
 */

/* These are all highly standard and portable headers. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <string>
#include <fstream>
#include <iostream>
#include <streambuf>

/* This is for mkdir(); this may need to be changed for some platforms. */
#include <sys/stat.h>  /* For mkdir() */
#include <filesystem>

#include <pyjs/inflate.hpp>
#include <zlib.h>

#include <emscripten/bind.h>

namespace em = emscripten;

namespace pyjs
{



    // function to check if cstring ends with ".so"
    bool is_so_file(const char * cstr){
        std::string str(cstr);
        return str.size() > 3 && str.substr(str.size() - 3) == ".so";
    }



    /* Parse an octal number, ignoring leading and trailing nonsense. */
    static int
    parseoct(const char *p, size_t n)
    {
        int i = 0;

        while ((*p < '0' || *p > '7') && n > 0) {
            ++p;
            --n;
        }
        while (*p >= '0' && *p <= '7' && n > 0) {
            i *= 8;
            i += *p - '0';
            ++p;
            --n;
        }
        return (i);
    }

    /* Returns true if this is 512 zero bytes. */
    static int
    is_end_of_archive(const char *p)
    {
        int n;
        for (n = 511; n >= 0; --n)
            if (p[n] != '\0')
                return (0);
        return (1);
    }

    /* Create a directory, including parent directories as necessary. */
    static void
    create_dir(const char *pathname, int mode, const char * root_dir)
    {
        std::error_code ec;
        if(root_dir != nullptr){

            std::filesystem::path full_path =std::filesystem::path(root_dir) / std::filesystem::path(pathname);
            std::filesystem::create_directories(full_path, ec);
        }
        else{
            std::filesystem::create_directories(pathname, ec);
        }

        if (ec){
            fprintf(stderr, "Could not create directory %s\n", pathname);
            throw std::runtime_error("could not create directory");
        }
    }

    /* Create a file, including parent directory as necessary. */
    static FILE *
    create_file(
        char *pathname_in, int mode,  const char * root_dir
    )
    {

        const auto longlink_path = std::filesystem::path("@LongLink");
        
        std::string pathname(pathname_in);
        std::filesystem::path full_path =std::filesystem::path(root_dir) / std::filesystem::path(pathname);
        pathname = full_path.string();

        if (
            // if this pathname_in isn't @LongLink...
            longlink_path != std::filesystem::path(pathname_in)
            // ... and there exists an @LongLink file
            && std::filesystem::exists(longlink_path)
        ) {

            std::cout << " @LongLink detected" << std::endl;
            std::cout << " Renaming " << pathname_in << " to @LongLink contents";
            std::cout << std::endl;

            // then set the pathname to the contents of @LongLink...
            std::ifstream longlink_stream(longlink_path);
            pathname = std::string(
            std::istreambuf_iterator<char>(longlink_stream),
            std::istreambuf_iterator<char>()
            );
            // ... and delete the @LongLink file
            std::filesystem::remove(longlink_path);
        }

        FILE *f;
        f = fopen(pathname.c_str(), "wb+");
        if (f == NULL) {
            /* Try creating parent dir and then creating file. */
            create_dir(
            std::filesystem::path(pathname).parent_path().c_str(),
            0755,
            nullptr
            );
                f = fopen(pathname.c_str(), "wb+");
        }

        return (f);
    }

    /* Verify the tar checksum. */
    static int
    verify_checksum(const char *p)
    {
        int n, u = 0;
        for (n = 0; n < 512; ++n) {
            if (n < 148 || n > 155)
                /* Standard tar checksum adds unsigned bytes. */
                u += ((unsigned char *)p)[n];
            else
                u += 0x20;

        }
        return (u == parseoct(p + 148, 8));
    }

    /* Extract a tar archive. */
    void untar_impl(FILE *a, const char *path, em::val & shared_libraraies)
    {


        std::filesystem::path root_dir(path);


        char buff[512];
        FILE *f = NULL;
        size_t bytes_read;
        int filesize;

        //printf("Extracting from %s\n", path);

        for (std::size_t iter=0; ;++iter) {
            bytes_read = fread(buff, 1, 512, a);
            if (bytes_read < 512) {
                fprintf(stderr,
                    "Short read on %s: expected 512, got %d\n",
                    path, (int)bytes_read);
                throw std::runtime_error("untar error: short read error: expected 512");
            }
            if (is_end_of_archive(buff)) {
                return   ;
            }
            if (!verify_checksum(buff)) {
                fprintf(stderr, "Checksum failure\n");
                throw std::runtime_error("checksum failure");
            }
            filesize = parseoct(buff + 124, 12);
            switch (buff[156]) {
            case '1':
                //printf(" Ignoring hardlink %s\n", buff);
                break;
            case '2':
                //printf(" Ignoring symlink %s\n", buff);
                break;
            case '3':
                //printf(" Ignoring character device %s\n", buff);
                break;
            case '4':
                //printf(" Ignoring block device %s\n", buff);
                break;
            case '5':
                //printf(" Extracting dir %s\n", buff);
                create_dir(buff, parseoct(buff + 100, 8), path);
                filesize = 0;
                break;
            case '6':
                //printf(" Ignoring FIFO %s\n", buff);
                break;
            default:

                //std::cout<<"considering file: "<<buff<<std::endl;
                // check if fname ends with .so
                if(is_so_file(buff)){
                    // append to emscripten::val::array

                    std::filesystem::path so_path = root_dir / std::filesystem::path(buff);


                    shared_libraraies.call<void>("push", em::val(so_path.string()));
                }

                f = create_file(buff, parseoct(buff + 100, 8), path);
                break;
            }
            while (filesize > 0) {
                bytes_read = fread(buff, 1, 512, a);
                if (bytes_read < 512) {
                    fprintf(stderr,
                        "Short read on %s: Expected 512, got %d\n",
                        path, (int)bytes_read);
                    throw std::runtime_error("untar error: short read error: expected 512");
                }
                if (filesize < 512)
                    bytes_read = filesize;
                if (f != NULL) {
                    if (fwrite(buff, 1, bytes_read, f)
                        != bytes_read)
                    {
                        fprintf(stderr, "Failed write\n");
                        fclose(f);
                        f = NULL;
                        throw std::runtime_error("failed write");
                    }
                }
                filesize -= bytes_read;
            }
            if (f != NULL) {
                fclose(f);
                f = NULL;
            }
        }
    }










    em::val untar(const std::string &tar_path, const std::string &path){

        auto shared_libraraies = em::val::array();


        auto file = gzopen(tar_path.c_str(), "rb");
        auto decompressed_tmp_file = std::tmpfile();


        // unzip into temporary file
        //std::cout<<"inflate "<<tar_path<<" into tempdir"<<std::endl;
        inflate(file, decompressed_tmp_file);
        gzclose(file);
        std::rewind(decompressed_tmp_file);

        //std::cout<<"decompress  into "<<path<<std::endl;
        // untar into present working directory
        untar_impl(decompressed_tmp_file, path.c_str(),shared_libraraies);

        // deletes temporary file
        std::fclose(decompressed_tmp_file);

        return shared_libraraies;
    }
}