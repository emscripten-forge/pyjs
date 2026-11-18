// Archive extraction for the runtime (pyjs_runtime_browser only, not libpyjs):
// tar / zip archives, compressed with gzip, bzip2 or zstd (detected from the
// content), conda packages (.tar.bz2, .conda), written straight into the
// emscripten file system. Exposed to JS as Module._extract_archive.

#include <archive.h>
#include <archive_entry.h>

#include <emscripten/bind.h>
#include <emscripten/val.h>

#include <sys/stat.h>
#include <utime.h>

#include <algorithm>

#include <cstdio>
#include <cstring>
#include <filesystem>
#include <memory>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace em = emscripten;
namespace fs = std::filesystem;

namespace pyjs
{
    namespace
    {
        // an uncompressed tar written into memory: what an extraction wrote,
        // in its final layout (renamed, no info/), for the "extracted" cache
        // of the npm package (a later install only untars it)
        struct TarWriter
        {
            archive* a;
            std::vector<char> bytes;

            TarWriter()
                : a(archive_write_new())
            {
                archive_write_set_format_pax_restricted(a);
                archive_write_add_filter_none(a);
                archive_write_set_bytes_in_last_block(a, 1);  // no padding to 10 KiB
                archive_write_open(a, this, nullptr, &TarWriter::write, nullptr);
            }

            ~TarWriter()
            {
                archive_write_free(a);
            }

            static la_ssize_t write(archive*, void* self, const void* buffer, size_t length)
            {
                auto& bytes = static_cast<TarWriter*>(self)->bytes;
                bytes.insert(bytes.end(), static_cast<const char*>(buffer), static_cast<const char*>(buffer) + length);
                return static_cast<la_ssize_t>(length);
            }

            // an entry (its data follows with add_data)
            void add(archive_entry* entry, const std::string& path, la_int64_t size)
            {
                archive_entry* copy = archive_entry_clone(entry);
                archive_entry_set_pathname(copy, path.c_str());
                archive_entry_set_size(copy, size);
                archive_entry_sparse_clear(copy);
                if (archive_write_header(a, copy) != ARCHIVE_OK)
                {
                    archive_entry_free(copy);
                    throw std::runtime_error(std::string("writing the extracted tar: ") + archive_error_string(a));
                }
                archive_entry_free(copy);
            }

            void add_data(const void* data, size_t size)
            {
                if (size > 0 && archive_write_data(a, data, size) < 0)
                {
                    throw std::runtime_error(std::string("writing the extracted tar: ") + archive_error_string(a));
                }
            }

            std::vector<char>& finish()
            {
                archive_write_close(a);
                return bytes;
            }
        };

        // what to do with the entries of an archive
        struct ExtractOptions
        {
            // also record what is written into this tar (paths relative to dest)
            TarWriter* tar = nullptr;
            std::string dest = "/";
            // a conda package: info/ (and the info-*.tar.zst of a .conda) is not
            // written, only the requested `meta` members are kept
            bool conda = false;
            // archive members returned as bytes instead of written, e.g. "info/paths.json"
            std::set<std::string> meta;
            // path prefixes renamed while writing, e.g. "site-packages/" ->
            // "lib/python3.14/site-packages/" (noarch python packages)
            std::vector<std::pair<std::string, std::string>> rename;
            // write nothing (only collect `meta`): the info part of a .conda
            bool meta_only = false;
        };

        // what was extracted
        struct ExtractResult
        {
            std::vector<std::string> files;
            std::vector<std::string> shared_libs;
            std::vector<std::pair<std::string, std::vector<char>>> meta;
        };

        // an error with libarchive's message
        [[noreturn]] void fail(archive* a, const std::string& what)
        {
            const char* msg = archive_error_string(a);
            throw std::runtime_error(what + (msg ? std::string(": ") + msg : std::string()));
        }

        // a reader for archives in memory: tar / zip, gzip / bzip2 / zstd (no xz:
        // this libarchive is built without lzma; no xar etc.: no libxml2)
        struct Reader
        {
            archive* a;

            Reader(const char* data, std::size_t size)
                : a(archive_read_new())
            {
                archive_read_support_filter_gzip(a);
                archive_read_support_filter_bzip2(a);
                archive_read_support_filter_zstd(a);
                archive_read_support_format_tar(a);
                archive_read_support_format_zip(a);
                if (archive_read_open_memory(a, data, size) != ARCHIVE_OK)
                {
                    fail(a, "not a supported archive (tar / zip, gzip / bzip2 / zstd)");
                }
            }

            ~Reader()
            {
                archive_read_free(a);
            }
        };

        // "./a/b" -> "a/b"; "" for the archive root
        std::string clean_member_path(std::string p)
        {
            while (p.rfind("./", 0) == 0)
            {
                p = p.substr(2);
            }
            while (!p.empty() && p.back() == '/')
            {
                p.pop_back();
            }
            return p == "." ? std::string() : p;
        }

        // the member path relative to `dest`, renamed; throws for paths leaving `dest`
        std::string renamed_path(const ExtractOptions& opt, const std::string& member)
        {
            fs::path rel(member);
            if (rel.is_absolute())
            {
                throw std::runtime_error("absolute path in archive: " + member);
            }
            for (const auto& part : rel)
            {
                if (part == "..")
                {
                    throw std::runtime_error("path leaving the destination in archive: " + member);
                }
            }
            std::string renamed = member;
            for (const auto& [from, to] : opt.rename)
            {
                if (renamed.rfind(from, 0) == 0)
                {
                    renamed = to + renamed.substr(from.size());
                    break;
                }
            }
            return renamed;
        }

        // the member path below `dest` (renamed)
        fs::path target_path(const ExtractOptions& opt, const std::string& member)
        {
            return fs::path(opt.dest) / renamed_path(opt, member);
        }

        // a wasm shared library: *.so / *.so.* starting with the wasm magic
        bool is_shared_lib(const fs::path& path)
        {
            const std::string name = path.filename().string();
            const bool so_name = (name.size() > 3 && name.compare(name.size() - 3, 3, ".so") == 0)
                                 || name.find(".so.") != std::string::npos;
            if (!so_name)
            {
                return false;
            }
            FILE* f = std::fopen(path.c_str(), "rb");
            if (!f)
            {
                return false;
            }
            char magic[4] = { 0, 0, 0, 0 };
            const bool ok = std::fread(magic, 1, 4, f) == 4 && std::memcmp(magic, "\0asm", 4) == 0;
            std::fclose(f);
            return ok;
        }

        // the data of the current entry, in memory
        std::vector<char> read_entry_data(archive* a)
        {
            std::vector<char> data;
            const void* block;
            size_t size;
            la_int64_t offset;
            int r;
            while ((r = archive_read_data_block(a, &block, &size, &offset)) == ARCHIVE_OK)
            {
                if (static_cast<std::size_t>(offset) + size > data.size())
                {
                    data.resize(static_cast<std::size_t>(offset) + size);  // sparse: holes stay 0
                }
                std::memcpy(data.data() + offset, block, size);
            }
            if (r != ARCHIVE_EOF)
            {
                fail(a, "reading an archive member");
            }
            return data;
        }

        // write the data of the current entry to `path` (sparse holes are skipped;
        // in `tar` they are written as zeros)
        void write_entry_data(archive* a, const fs::path& path, TarWriter* tar)
        {
            FILE* f = std::fopen(path.c_str(), "wb");
            if (!f)
            {
                throw std::runtime_error("cannot write " + path.string());
            }
            static const std::vector<char> zeros(65536, 0);
            const void* block;
            size_t size;
            la_int64_t offset;
            la_int64_t end = 0;
            int r;
            while ((r = archive_read_data_block(a, &block, &size, &offset)) == ARCHIVE_OK)
            {
                if (offset != end && std::fseek(f, static_cast<long>(offset), SEEK_SET) != 0)
                {
                    std::fclose(f);
                    throw std::runtime_error("cannot seek in " + path.string());
                }
                if (size > 0 && std::fwrite(block, 1, size, f) != size)
                {
                    std::fclose(f);
                    throw std::runtime_error("cannot write " + path.string());
                }
                if (tar)
                {
                    for (la_int64_t gap = offset - end; gap > 0;)
                    {
                        const size_t n = static_cast<size_t>(std::min<la_int64_t>(gap, zeros.size()));
                        tar->add_data(zeros.data(), n);
                        gap -= static_cast<la_int64_t>(n);
                    }
                    tar->add_data(block, size);
                }
                end = offset + static_cast<la_int64_t>(size);
            }
            std::fclose(f);
            if (r != ARCHIVE_EOF)
            {
                fail(a, "reading " + path.string());
            }
        }

        // the modification time of the archive member (python validates its
        // bytecode caches against the mtime of the source: it must not change
        // between two extractions of the same package)
        void set_mtime(archive_entry* entry, const fs::path& path)
        {
            if (archive_entry_mtime_is_set(entry))
            {
                struct utimbuf times;
                times.actime = times.modtime = static_cast<time_t>(archive_entry_mtime(entry));
                utime(path.c_str(), &times);
            }
        }

        // the content of a file in the file system (hard link copies into the tar)
        std::vector<char> read_file(const fs::path& path)
        {
            std::vector<char> data(fs::file_size(path));
            FILE* f = std::fopen(path.c_str(), "rb");
            if (!f || std::fread(data.data(), 1, data.size(), f) != data.size())
            {
                if (f)
                {
                    std::fclose(f);
                }
                throw std::runtime_error("cannot read " + path.string());
            }
            std::fclose(f);
            return data;
        }

        void extract_into(const char* data, std::size_t size, const ExtractOptions& opt, ExtractResult& out);

        // the members of a .conda (zip): pkg-*.tar.zst is extracted, info-*.tar.zst
        // only gives `meta`; nothing else (metadata.json) is used
        void extract_conda_zip(archive* a, const ExtractOptions& opt, ExtractResult& out)
        {
            archive_entry* entry;
            int r;
            while ((r = archive_read_next_header(a, &entry)) == ARCHIVE_OK)
            {
                const std::string name = clean_member_path(archive_entry_pathname(entry));
                const bool pkg = name.rfind("pkg-", 0) == 0;
                const bool info = name.rfind("info-", 0) == 0;
                if (!pkg && !info)
                {
                    archive_read_data_skip(a);
                    continue;
                }
                const std::vector<char> inner = read_entry_data(a);
                ExtractOptions inner_opt = opt;
                inner_opt.conda = true;
                inner_opt.meta_only = info;
                if (info)
                {
                    // the members of info-*.tar.zst are named without "info/"
                    inner_opt.meta.clear();
                    for (const auto& m : opt.meta)
                    {
                        if (m.rfind("info/", 0) == 0)
                        {
                            inner_opt.meta.insert(m.substr(5));
                        }
                    }
                }
                ExtractResult inner_out;
                extract_into(inner.data(), inner.size(), inner_opt, inner_out);
                for (auto& f : inner_out.files)
                {
                    out.files.push_back(std::move(f));
                }
                for (auto& s : inner_out.shared_libs)
                {
                    out.shared_libs.push_back(std::move(s));
                }
                for (auto& [m, bytes] : inner_out.meta)
                {
                    out.meta.emplace_back(info ? "info/" + m : m, std::move(bytes));
                }
            }
            if (r != ARCHIVE_EOF)
            {
                fail(a, "reading a .conda package");
            }
        }

        void extract_into(const char* data, std::size_t size, const ExtractOptions& opt, ExtractResult& out)
        {
            Reader reader(data, size);
            archive* a = reader.a;
            archive_entry* entry;
            int r = archive_read_next_header(a, &entry);
            if (r == ARCHIVE_EOF)
            {
                return;  // an empty archive
            }
            if (r != ARCHIVE_OK && r != ARCHIVE_WARN)
            {
                fail(a, "reading an archive");
            }
            if (archive_format(a) == ARCHIVE_FORMAT_ZIP && opt.conda)
            {
                // a .conda: start over with the zip reader on its members
                Reader zip(data, size);
                extract_conda_zip(zip.a, opt, out);
                return;
            }

            // directories / symlinks created by this archive: nothing is written
            // through a symlink of the archive (it could point outside dest)
            std::set<std::string> symlinks;
            do
            {
                if (r != ARCHIVE_OK && r != ARCHIVE_WARN)
                {
                    fail(a, "reading an archive");
                }
                const std::string member = clean_member_path(archive_entry_pathname(entry));
                if (member.empty())
                {
                    continue;
                }
                if (opt.meta.count(member))
                {
                    out.meta.emplace_back(member, read_entry_data(a));
                    continue;
                }
                if (opt.meta_only || (opt.conda && member.rfind("info/", 0) == 0))
                {
                    continue;
                }
                const std::string rel = renamed_path(opt, member);
                const fs::path path = fs::path(opt.dest) / rel;
                for (fs::path parent = path.parent_path(); parent != parent.root_path() && !parent.empty();
                     parent = parent.parent_path())
                {
                    if (symlinks.count(parent.string()))
                    {
                        throw std::runtime_error("archive writes through its own symlink: " + member);
                    }
                }
                fs::create_directories(path.parent_path());

                const auto type = archive_entry_filetype(entry);
                const char* hardlink = archive_entry_hardlink(entry);
                std::error_code ec;
                if (type == AE_IFDIR)
                {
                    fs::create_directories(path);
                    if (opt.tar)
                    {
                        opt.tar->add(entry, rel, 0);
                    }
                }
                else if (type == AE_IFLNK)
                {
                    fs::remove(path, ec);
                    fs::create_symlink(archive_entry_symlink(entry), path);
                    symlinks.insert(path.string());
                    out.files.push_back(path.string());
                    if (opt.tar)
                    {
                        opt.tar->add(entry, rel, 0);
                    }
                }
                else if (hardlink != nullptr)
                {
                    // MEMFS has no hard links: a copy of the linked file
                    const fs::path source = target_path(opt, clean_member_path(hardlink));
                    fs::remove(path, ec);
                    fs::copy_file(source, path);
                    set_mtime(entry, path);
                    out.files.push_back(path.string());
                    if (is_shared_lib(path))
                    {
                        out.shared_libs.push_back(path.string());
                    }
                    if (opt.tar)
                    {
                        // (a regular file in the tar: the copy)
                        const std::vector<char> content = read_file(path);
                        archive_entry* file = archive_entry_clone(entry);
                        archive_entry_set_hardlink(file, nullptr);
                        archive_entry_set_filetype(file, AE_IFREG);
                        opt.tar->add(file, rel, static_cast<la_int64_t>(content.size()));
                        archive_entry_free(file);
                        opt.tar->add_data(content.data(), content.size());
                    }
                }
                else if (type == AE_IFREG)
                {
                    fs::remove(path, ec);
                    if (opt.tar)
                    {
                        opt.tar->add(entry, rel, archive_entry_size(entry));
                    }
                    write_entry_data(a, path, opt.tar);
                    set_mtime(entry, path);
                    out.files.push_back(path.string());
                    if (is_shared_lib(path))
                    {
                        out.shared_libs.push_back(path.string());
                    }
                }
                // (devices, fifos, sockets: not in packages, skipped)
            } while ((r = archive_read_next_header(a, &entry)) != ARCHIVE_EOF);
        }

        // JS array of strings -> std::vector<std::string>
        std::vector<std::string> string_list(const em::val& v)
        {
            std::vector<std::string> out;
            if (v.isUndefined() || v.isNull())
            {
                return out;
            }
            const unsigned n = v["length"].as<unsigned>();
            for (unsigned i = 0; i < n; ++i)
            {
                out.push_back(v[i].as<std::string>());
            }
            return out;
        }

        em::val to_js(const std::vector<std::string>& v)
        {
            em::val arr = em::val::array();
            for (const auto& s : v)
            {
                arr.call<void>("push", s);
            }
            return arr;
        }

        // Module._extract_archive(bytes: Uint8Array, dest: string, options?) ->
        // {files: string[], sharedLibs: string[], meta: {member: Uint8Array}, tar?: Uint8Array}.
        // options: {conda: bool, meta: string[], rename: [[from, to], ...],
        // tar: bool (also return what was written as an uncompressed tar,
        // paths relative to dest: extracting it gives the same files)}.
        // Throws a JS Error for unsupported / broken archives and unsafe paths.
        em::val extract_archive(em::val bytes, const std::string& dest, em::val options)
        {
            ExtractOptions opt;
            opt.dest = dest.empty() ? "/" : dest;
            std::unique_ptr<TarWriter> tar;
            if (!options.isUndefined() && !options.isNull())
            {
                if (options["conda"].as<bool>())
                {
                    opt.conda = true;
                }
                if (options["tar"].as<bool>())
                {
                    tar = std::make_unique<TarWriter>();
                    opt.tar = tar.get();
                }
                for (auto& m : string_list(options["meta"]))
                {
                    opt.meta.insert(std::move(m));
                }
                const em::val rename = options["rename"];
                if (!rename.isUndefined() && !rename.isNull())
                {
                    const unsigned n = rename["length"].as<unsigned>();
                    for (unsigned i = 0; i < n; ++i)
                    {
                        opt.rename.emplace_back(rename[i][0].as<std::string>(),
                                                rename[i][1].as<std::string>());
                    }
                }
            }

            // the bytes into the wasm memory (one copy)
            const std::size_t size = bytes["length"].as<std::size_t>();
            std::vector<char> data(size);
            em::val(em::typed_memory_view(size, data.data())).call<void>("set", bytes);

            ExtractResult out;
            try
            {
                extract_into(data.data(), data.size(), opt, out);
            }
            catch (const std::exception& e)
            {
                em::val::global("Error").new_(std::string("pyjs: extracting failed: ") + e.what()).throw_();
            }

            em::val meta = em::val::object();
            for (const auto& [name, content] : out.meta)
            {
                em::val view(em::typed_memory_view(content.size(), content.data()));
                meta.set(name, em::val::global("Uint8Array").new_(view));  // a copy
            }
            em::val result = em::val::object();
            result.set("files", to_js(out.files));
            result.set("sharedLibs", to_js(out.shared_libs));
            result.set("meta", meta);
            if (tar)
            {
                const std::vector<char>& bytes_out = tar->finish();
                em::val view(em::typed_memory_view(bytes_out.size(), bytes_out.data()));
                result.set("tar", em::val::global("Uint8Array").new_(view));  // a copy
            }
            return result;
        }

        // Module._tar_files(paths: string[]) -> Uint8Array: an uncompressed tar
        // of these regular files (absolute paths, stored relative to "/", with
        // their modification times; missing files are skipped). The npm
        // package keeps python's bytecode caches with it.
        em::val tar_files(em::val paths)
        {
            TarWriter tar;
            try
            {
                for (const auto& path : string_list(paths))
                {
                    struct stat st;
                    if (stat(path.c_str(), &st) != 0 || !S_ISREG(st.st_mode))
                    {
                        continue;
                    }
                    const std::vector<char> content = read_file(path);
                    archive_entry* entry = archive_entry_new();
                    archive_entry_copy_stat(entry, &st);
                    tar.add(entry, path.substr(path.find_first_not_of('/')), static_cast<la_int64_t>(content.size()));
                    archive_entry_free(entry);
                    tar.add_data(content.data(), content.size());
                }
            }
            catch (const std::exception& e)
            {
                em::val::global("Error").new_(std::string("pyjs: writing a tar failed: ") + e.what()).throw_();
            }
            const std::vector<char>& bytes = tar.finish();
            em::val view(em::typed_memory_view(bytes.size(), bytes.data()));
            return em::val::global("Uint8Array").new_(view);  // a copy
        }
    }
}

EMSCRIPTEN_BINDINGS(pyjs_extract)
{
    em::function("_extract_archive", &pyjs::extract_archive);
    em::function("_tar_files", &pyjs::tar_files);
}
