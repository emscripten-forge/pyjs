Module["mkdirs"] = function (dirname) {
    // get all partent directories
    let parent_dirs = []
    let parent_dir = dirname
    while (parent_dir != "") {
        parent_dirs.push(parent_dir)
        parent_dir = parent_dir.split("/").slice(0, -1).join("/")
    }
    console.log(parent_dirs)
    // make directories
    parent_dirs = parent_dirs.reverse()
    for (let parent_dir of parent_dirs) {
        if (!Module.FS.isDir(parent_dir)) {
            Module.FS.mkdir(parent_dir)
        }
    }
}


function untar_from_python(tarball_path, target_dir = "") {
    let shared_libs = Module.exec_eval(`
import tarfile
import json
import pyjs
from pathlib import Path
import tempfile
import shutil
import os
import sys

target_dir = "${target_dir}"
if target_dir == "":
    target_dir = sys.prefix
try:
    with tarfile.open("${tarball_path}") as tar:
        files = tar.getmembers()
        shared_libs = []
        for file in files:
            if file.name.endswith(".so"):
            
                if target_dir == "/":
                    shared_libs.append(f"/{file.name}")
                else:
                    shared_libs.append(f"{target_dir}/{file.name}")

        tar.extractall(target_dir)
        s = json.dumps(shared_libs)
except Exception as e:
    print("ERROR",e)
    raise e
s
`)
    return JSON.parse(shared_libs)
}

Module["_untar_from_python"] = untar_from_python

async function bootstrap_python(prefix, package_tarballs_root_url, python_package) {
    // fetch python package
    let python_package_url = `${package_tarballs_root_url}/${python_package.filename}`

    console.log(`fetching python package from ${python_package_url}`)
    let byte_array = await fetchByteArray(python_package_url)


    const python_tarball_path = `/package_tarballs/${python_package.filename}`;
    console.log(`extract ${python_tarball_path} (${byte_array.length} bytes)`)
    Module.FS.writeFile(python_tarball_path, byte_array);
    Module._untar(python_tarball_path, prefix);


    // split version string into major and minor and patch version
    let version = python_package.version.split(".").map(x => parseInt(x));



    await Module.init(prefix, version);
}




Module["bootstrap_from_empack_packed_environment"] = async function
    (   
        packages_json_url,
        package_tarballs_root_url,
        verbose = false
    ) {




    function splitPackages(packages) {
        // find package with name "python" and remove it from the list
        let python_package = undefined
        for (let i = 0; i < packages.length; i++) {
            if (packages[i].name == "python") {
                python_package = packages[i]
                packages.splice(i, 1)
                break
            }
        }
        if (python_package == undefined) {
            throw new Error("no python package found in package.json")
        }
        return { python_package, packages }
    }
    
    
    function makeDirs() {
        if (!Module.FS.isDir(`/package_tarballs`)) {
            Module.FS.mkdir(`/package_tarballs`);
        }
    }
    
    
    async function fetchAndUntar
        (
            package_tarballs_root_url,
            python_is_ready_promise,
            package
        ) {
        let package_url = `${package_tarballs_root_url}/${package.filename}`
        console.log(`fetching pkg ${package.name} from ${package_url}`)
        let byte_array = await fetchByteArray(package_url)
        const tarball_path = `/package_tarballs/${package.filename}`;
        Module.FS.writeFile(tarball_path, byte_array);
        console.log(`extract ${tarball_path} (${byte_array.length} bytes)`)
        await python_is_ready_promise;
        return untar_from_python(tarball_path);
    }






    // fetch json with list of all packages
    let empack_env_meta = await fetchJson(packages_json_url);
    let all_packages = empack_env_meta.packages;
    let prefix = empack_env_meta.prefix;
    makeDirs();

    // enusre there is python and split it from the rest
    let splitted = splitPackages(all_packages);
    let packages = splitted.packages;
    let python_package = splitted.python_package;
    let python_version = python_package.version.split(".").map(x => parseInt(x));

    // fetch init python itself
    let python_is_ready_promise = bootstrap_python(prefix, package_tarballs_root_url, python_package);

    // create array with size 
    let shared_libs = await Promise.all(packages.map(package => fetchAndUntar(package_tarballs_root_url, python_is_ready_promise, package)))

    // instantiate all packages
    for (let i = 0; i < packages.length; i++) {

        // if we have any shared libraries, load them
        if (shared_libs[i].length > 0) {

            for (let j = 0; j < shared_libs[i].length; j++) {
                let sl = shared_libs[i][j];
            }
            await Module._loadDynlibsFromPackage(
                prefix,
                python_version,
                packages[i].name,
                false,
                shared_libs[i]
            )
        }
    }
}