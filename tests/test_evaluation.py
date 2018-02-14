import pytest
import random
from time import sleep, time

from lproc import add_cache, rmap, eager_iter, EagerAccessException


def test_cached():
    def f(x):
        sleep(.01)
        return x

    cache_size = 3
    x = [random.random() for _ in range(100)]
    y = rmap(f, x)
    z = add_cache(y, cache_size)

    assert list(iter(y)) == x
    assert [z[i] for i in range(len(z))] == x

    t1 = time()
    for i in range(len(x)):
        for j in range(max(0, i - cache_size + 1), i + 1):
            assert y[j] == x[j]
            assert y[j] == x[j]
    t2 = time()

    t3 = time()
    for i in range(len(x)):
        for j in range(max(0, i - cache_size + 1), i + 1):
            assert z[j] == x[j]
            assert z[j] == x[j]
    t4 = time()

    speedup = (t2 - t1) / (t4 - t3)
    print(speedup)
    assert speedup > 1.9


@pytest.mark.timeout(15)
@pytest.mark.parametrize("method", ["thread", "proc"])
def test_eager_iter(method):
    def f1(x):
        sleep(.01)
        return x

    x = list(range(1000))
    y = rmap(f1, x)

    t1 = time()
    list(iter(y))
    t2 = time()

    t3 = time()
    z = list(eager_iter(y, nworkers=4, max_buffered=20, method=method))
    t4 = time()

    assert all(x_ == z_ for x_, z_ in zip(x, z))
    speedup = (t2 - t1) / (t4 - t3)
    print(speedup)
    assert speedup > 2.5  # be conservative for travis busy machines...


@pytest.mark.timeout(10)
@pytest.mark.parametrize("method", ["thread", "proc"])
def test_eager_iter_errors(method):
    class CustomError(Exception):
        pass

    def f1(x):
        if x is None:
            raise CustomError()
        else:
            return x

    arr1 = [1, 2, 3, None]
    arr2 = rmap(f1, arr1)

    with pytest.raises(EagerAccessException):
        for i, y in enumerate(eager_iter(
                arr2, nworkers=2, max_buffered=2, method=method)):
            assert arr1[i] == y

    def f2(x):
        if x is None:
            raise ValueError("blablabla")
        else:
            return x

    arr3 = rmap(f2, arr1)

    try:
        for i, y in enumerate(eager_iter(
                arr3, nworkers=2, max_buffered=2, method=method)):
            assert arr1[i] == y
    except Exception as e:
        assert isinstance(e, EagerAccessException)
        assert isinstance(e.__cause__, ValueError)