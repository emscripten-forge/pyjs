# import requests
import json
import tarfile
from zipfile import ZipFile


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
class Mamba:
    def __init__(self):
        print("Mamba created")
        self.pool = mamba.MPool()

    # initalize mamba
    def init_mamba(self, url_arch, url_noarch):

        # download repodata zip file
        def dl_repodata(url):
            response = requests.get(url)
            response.raise_for_status()
            file_file = io.BytesIO(response.content)
            with ZipFile(io.BytesIO(response.content), "r") as zipObj:
                rp = zipObj.namelist()[0]
                with zipObj.open(rp) as myfile:
                    return myfile.read()

        pool = pyjs.Mabma.instance().pool
        print("download raw_arch")
        raw_arch = dl_repodata(url_arch)
        print("download raw_noarch")
        raw_noarch = dl_repodata(url_noarch)
        repodata_arch = json.loads(raw_arch)
        with open("/home/arch.json", "wb") as f:
            f.write(raw_arch)
        with open("/home/noarch.json", "wb") as f:
            f.write(raw_noarch)

        pool.load_repo("/home/arch.json", "arch")
        pool.load_repo("/home/noarch.json", "noarch")

        return repodata_arch
