Module["mkdirs"] = function (dirname) {
   // get all partent directories
   let parent_dirs = []
   let parent_dir = dirname
   while(parent_dir != ""){
       parent_dirs.push(parent_dir)
       parent_dir = parent_dir.split("/").slice(0,-1).join("/")
   }
   console.log(parent_dirs)
   // make directories
   parent_dirs = parent_dirs.reverse()
   for(let parent_dir of parent_dirs){
       if(!Module.FS.isDir(parent_dir)){
           Module.FS.mkdir(parent_dir)
       }
   }
}

function untar(tarball_path){
    let shared_libs = Module.exec_eval(`
import tarfile
import json
import pyjs
from pathlib import Path
import tempfile
import shutil
import os
import sys


try:
    with tarfile.open("${tarball_path}") as tar:
        files = tar.getmembers()
        shared_libs = []
        for file in files:
            if file.name.endswith(".so"):
                if sys.prefix == "/":
                    shared_libs.append(f"/{file.name}")
                else:
                    shared_libs.append(f"{sys.prefix}/{file.name}")

        tar.extractall(sys.prefix)
        s = json.dumps(shared_libs)
except Exception as e:
    print("ERROR",e)
    raise e
s
`)
    return JSON.parse(shared_libs)
}


async function fetchByteArray(url){
    let response = await fetch(url)
    if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
    }
    let arrayBuffer = await response.arrayBuffer()
    let byte_array = new Uint8Array(arrayBuffer)
    return byte_array
}

async function fetchJson(url){
    let response = await fetch(url)
    if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
    }
    let json = await response.json()
    return json
}

async function bootstrap_python(prefix, package_tarballs_root_url, python_package){
    // fetch python package
    let python_package_url = `${package_tarballs_root_url}/${python_package.filename}`
    let byte_array = await fetchByteArray(python_package_url)

    if(!Module.FS.isDir(`/package_tarballs`)){
        Module.FS.mkdir(`/package_tarballs`);   
    }
    const python_tarball_path = `/package_tarballs/${python_package.filename}`;
    Module.FS.writeFile(python_tarball_path, byte_array);
    Module._untar(python_tarball_path, prefix);

    await Module.init(prefix);
}




function splitPackages(packages){
    // find package with name "python" and remove it from the list
    let python_package = undefined
    for(let i=0;i<packages.length;i++){
        if(packages[i].name == "python"){
            python_package = packages[i]
            packages.splice(i,1)
            break
        }
    }
    if(python_package == undefined){
        throw new Error("no python package found in package.json")
    }
    return {python_package, packages}
}




Module["bootstrap_from_empack_packed_environment"] = async function
(    packages_json_url,
    package_tarballs_root_url,
    verbose=false
) {
    
    // fetch json with list of all packages
    let empack_env_meta = await fetchJson(packages_json_url);
    let all_packages = empack_env_meta.packages;
    let prefix = empack_env_meta.prefix;
    // enusre there is python and split it from the rest
    
    let splitted= splitPackages(all_packages);
    let packages = splitted.packages;
    let python_package = splitted.python_package;

    // fetch init python itself
    await bootstrap_python(prefix, package_tarballs_root_url, python_package);

    // create array with size 
    let shared_libs = new Array(packages.length)
    
    // download all
    let urls = packages.map(item => `${package_tarballs_root_url}/${item.filename}`)
    let byte_arrays = await Promise.all(urls.map(url =>  fetchByteArray(url)))

    // write tarfiles to FS
    for(let i=0;i<packages.length;i++){
        let tarball_path = `/package_tarballs/${packages[i].filename}`;
        Module.FS.writeFile(tarball_path, byte_arrays[i]);
    }

    // untar all
    for(let i=0;i<packages.length;i++){
        let tarball_path = `/package_tarballs/${packages[i].filename}`;
        shared_libs[i] = untar(tarball_path)
    }
    // instantiate all packages
    for(let i=0;i<packages.length;i++){ 

        // if we have any shared libraries, load them
        if(shared_libs[i].length > 0){

            for(let j=0;j<shared_libs[i].length;j++){
                let sl = shared_libs[i][j];
            }
            await Module._loadDynlibsFromPackage(
                prefix,
                packages[i].name,
                false,
                shared_libs[i]
            )
        }        
    }
}