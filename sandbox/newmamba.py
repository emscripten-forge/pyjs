import asyncio
import io
import json
import sysconfig
import tarfile
import time
from contextlib import redirect_stdout
from zipfile import ZipFile

import requests

import pyjs


class Singleton:
    def __init__(self, decorated):
        self._decorated = decorated

    def instance(self):
        try:
            return self._instance
        except AttributeError:
            self._instance = self._decorated()
            return self._instance

    def __call__(self):
        raise TypeError("Singletons must be accessed through `instance()`.")

    def __instancecheck__(self, inst):
        return isinstance(inst, self._decorated)


@Singleton
class PikoMamba:
    banner = """
=========================================
 _
|_) o  _  _   |\\/|  _. ._ _  |_   _.
|   | (_ (_)  |  | (_| | | | |_) (_|

                   ____
         _________/ O  \\___/
        <__p_i_c_o_____/   \\

=========================================
"""

    def __init__(self):
        print(self.banner)
        self.pool = pyjs.mamba.MPool()
        self.repodata_arch = None
        self.config = None

        meta = "/home/runner/env/conda-meta"

        from os import listdir
        from os.path import isfile, join

        installed = [f for f in listdir(meta)]

        self.installed = dict()

        for f in installed:
            path = os.path.join(meta, f)
            with open(path, "r") as ff:
                info = json.load(ff)
                self.installed[f[:-5]] = info

        self.installed_specs = set()
        for k, v in self.installed.items():
            spec = f"{v['name']}={v['version']}={v['build']}"
            self.installed_specs.add(spec)

    async def async_init(self, config):

        self.config = config
        pkg_base_url = self.config["data_urls"]["arch"]

        pyjs.js.Function(
            f"""
        globalThis.EmscriptenForgeModule['locateFile'] = function(f){{
            let path =  "{pkg_base_url}/" + f;
            console.log("downloading",path)
            return path
        }}
        """
        )()

        async def fetch_raw_repodata(url):
            print(f"fetch repodata: {url}")
            response = await pyjs.js.fetch(url)
            array = await response.arrayBuffer()
            nparray = pyjs.to_py(array)

            file_file = io.BytesIO(nparray)
            with ZipFile(file_file, "r") as zipObj:
                rp = zipObj.namelist()[0]
                with zipObj.open(rp) as myfile:
                    return myfile.read()

        raw_arch = await fetch_raw_repodata(self.config["repodata"]["noarch"])
        raw_noarch = await fetch_raw_repodata(self.config["repodata"]["arch"])
        self.repodata_arch = json.loads(raw_noarch)

        with open("/home/arch.json", "wb") as f:
            f.write(raw_arch)
        with open("/home/noarch.json", "wb") as f:
            f.write(raw_noarch)

        self.pool.load_repo("/home/arch.json", "arch")
        self.pool.load_repo("/home/noarch.json", "noarch")

    def is_noarch(self, name, ver, build):
        pkg_fname = self.pkg_filename(name, ver, build)
        return pkg_fname not in self.repodata_arch["packages"]

    def pkg_filename(self, name, ver, build):
        return f"{name}-{ver}-{build}.tar.bz2"

    async def install_arch(self, name, ver, build):
        pkg_filename = self.pkg_filename(name, ver, build)
        is_noarch = self.is_noarch(name, ver, build)

        pkg_base_url = f"{self.config['data_urls']['arch']}/{pkg_filename}"
        js_url = f"{pkg_base_url}.js"
        data_url = f"{pkg_base_url}.data"

        # todo, this might need to be changed for a non worker
        pyjs.js.importScripts(js_url)

    async def install_noarch(self, name, ver, build):
        pkg_filename = self.pkg_filename(name, ver, build)
        annaconda_url = f"https://anaconda.org/conda-forge/pycparser/{ver}/download/noarch/{pkg_filename}"

        response = await pyjs.js.fetch(annaconda_url)
        array = await response.arrayBuffer()
        nparray = pyjs.to_py(array)

        f = io.BytesIO(nparray)
        tar = tarfile.open(fileobj=f, mode="r:bz2")
        tar.extractall(path=sysconfig.get_path("purelib"))
        tar.close()

    async def install(self, specs):

        print("solving for: ", specs)
        to_install = list(specs) + list(self.installed_specs)

        res = self.pool.solve([str(s) for s in to_install])
        if "ERROR" in res:
            raise RuntimeError("failed")

        install = res["INSTALL"]

        to_install = []
        # install all needed packages
        for (name, ver, build) in install:
            spec = f"{name}={ver}={build}"
            if spec not in self.installed_specs:
                # print("skip installed")
                to_install.append((name, ver, build))

        print("installing: ", to_install)

        # install all needed packages
        for (name, ver, build) in to_install:
            spec = f"{name}=={ver}=={build}"
            if spec in self.installed_specs:
                # print("skip installed")
                continue
            pkg_filename = self.pkg_filename(name, ver, build)
            is_noarch = self.is_noarch(name, ver, build)

            if is_noarch:
                continue
                await self.install_noarch(name, ver, build)
            else:
                await self.install_arch(name, ver, build)

        await pyjs.js.EmscriptenForgeModule._wait_run_dependencies()


import asyncio

_async_done_ = [False]


async def main_runner():
    try:
        await main()

    except Exception as e:
        print(e)
    finally:
        global _async_done_
        _async_done_[0] = True


async def prepare_mamba():
    root = "http://127.0.0.1:8000"
    config = {
        "repodata": {
            "arch": f"{root}/distribution/repodata/arch.zip",
            "noarch": f"{root}/distribution/repodata/conda_forge_noarch_repodata.zip",
        },
        "data_urls": {
            "arch": f"{root}/distribution",
        },
    }

    mamba = PikoMamba.instance()
    await mamba.async_init(config)


async def main():

    t0 = time.time()
    import os

    # load repodata etc.
    await prepare_mamba()

    # do the thing
    await PikoMamba.instance().install(["regex"])

    print(f"took {time.time()-t0 :.2f} sec")

    import regex


asyncio.ensure_future(main_runner())
