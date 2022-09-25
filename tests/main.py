import pyjs
import time
from atests import *
from js_tests import main as js_main


async def main():

    # run js tests
    retcode = await js_main()
    if retcode != 0:
        return retcode

    import inspect
    import traceback

    bar = "".join(["="] * 40)
    print(f"{bar}\nRUN ASYNC TESTS:\n{bar}")
    n_failed, n_tests = 0, 0
    t0 = time.time()
    for k, v in globals().items():
        if k.startswith("test_") and inspect.iscoroutinefunction(v):
            try:
                print(f"RUN: {k}")
                await v()
            except Exception as e:
                traceback.print_exc()
                n_failed += 1
            n_tests += 1
    t1 = time.time()
    d = t1 - t0
    print(
        f"============================== {n_tests-n_failed} passed in {d:.01}s =============================="
    )

    if n_failed > 0:
        return 1

    import pyjs
    import pytest

    import os

    dir_path = os.path.dirname(os.path.realpath(__file__))
    os.chdir(dir_path)

    # import pytest_asyncio

    # start the tests
    os.environ["NO_COLOR"] = "1"

    specific_test = None
    args = []
    args = ["-s", f"{dir_path}/tests"]
    if specific_test is not None:
        args += ["-k", str(specific_test)]

    # args += ["-p", "pytest_asyncio"]

    retcode = pytest.main(args, plugins=[])
    if retcode != pytest.ExitCode.OK:
        raise RuntimeError(f"pytest failed with return code: {retcode}")

    return 0
