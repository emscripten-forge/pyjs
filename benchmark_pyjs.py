import pytest

import pyjs

# os.environ["PYJS_DONT_AUTOSTART_EVENT_LOOP"] = "1"


#  to benchmark:
#   - get global property
#   - long chain   "foo.bar.foobar.barfoo"
#   - implicted converted properties


# def test_get_global_property(benchmark):

#     benchmark(lambda : pyjs.js.Object)


@pytest.mark.parametrize("n_args", [2])
def test_function_call(benchmark, n_args):

    args = [f"a{i}" for i in range(n_args)]
    body = ["return 1"]

    f = pyjs.js.Function(*(args + body))
    benchmark(f, *args)


@pytest.mark.parametrize("n_args", [2])
def test_function_jcall(benchmark, n_args):

    args = [f"a{i}" for i in range(n_args)]
    body = ["return 1"]

    f = pyjs.js.Function(*(args + body)).jcall
    benchmark(f, *args)


@pytest.mark.parametrize("n_args", [2])
@pytest.mark.parametrize("jin", [False, True])
@pytest.mark.parametrize("jout", [False, True])
def test_function_gcall(benchmark, n_args, jin, jout):

    args = [f"a{i}" for i in range(n_args)]
    body = ["return 1"]

    f = pyjs.js.Function(*(args + body))

    benchmark(lambda: pyjs.gapply(f, args, jin=jin, jout=jout))


# @pytest.mark.benchmark(
#     min_rounds=500
# )
# def test_real_world_scenario(benchmark):

#     def f():
#         myRequest = js.XMLHttpRequest.new()
#         myRequest.open("GET","https://www.w3schools.com/bootstrap/bootstrap_ver.asp",False)
#         myRequest.responseType = "arraybuffer"

#     benchmark(f)


# @pytest.mark.benchmark(
#     min_rounds=500
# )
# def test_jcall(benchmark):

#     fopen = js.XMLHttpRequest.new().open
#     benchmark(fopen,"GET","https://www.w3schools.com/bootstrap/bootstrap_ver.asp",False)


# @pytest.mark.benchmark(
#     min_rounds=500
# )
# def test_call(benchmark):

#     fopen = js.XMLHttpRequest.new().open.jcall
#     benchmark(fopen,"GET","https://www.w3schools.com/bootstrap/bootstrap_ver.asp",False)


if __name__ == "__main__":
    # start the tests
    # os.environ["NO_COLOR"] = "1"
    args = [
        "-s",
        "/script/benchmark_pyjs.py",
        "--benchmark-min-time=0.0005",
        "--benchmark-warmup=on",
    ]
    specific_test = ""  # "test_real_world_scenario"
    if specific_test is not None and specific_test != "":
        args += ["-k", str(specific_test)]
    retcode = pytest.main(args)
    if retcode != 0:
        raise RuntimeError(f"pytest failed with return code: {retcode}")
