import os
# os.environ["PYJS_DONT_AUTOSTART_EVENT_LOOP"] = "1"

import pytest
import pytest_benchmark
import time
import pyjs

#  to benchmark:
#   - get global property
#   - long chain   "foo.bar.foobar.barfoo"
#   - implicted converted properties




def test_get_global_property(benchmark):

    benchmark(lambda : pyjs.js.Object)


@pytest.mark.parametrize("n_args", [4])
def test_function_call(benchmark, n_args):

    args = [f"a{i}" for i in range(n_args)]
    body = ["return 1"]

    f = pyjs.js.Function(*(args+body))
    benchmark(f,*args)



if __name__ == "__main__":
    import pyjs
    # start the tests
    os.environ["NO_COLOR"] = "1"
    retcode = pytest.main(["-s","/script/benchmark_pyjs.py","--benchmark-min-time=0.0005","--benchmark-warmup=on"])
    if retcode != 0:
        raise RuntimeError(f"pytest failed with return code: {retcode}")