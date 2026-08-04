"""A tiny stand-in for the handful of numpy calls ``synth`` makes.

Why this exists
---------------
numpy is not an AstrBot dependency, and a plugin that fails to *install*
because of an optional accelerator is worse than one that renders a chord a
few milliseconds slower. Synthesis here is elementwise arithmetic over a flat
buffer, which plain Python does perfectly well at these lengths (a 1.6 s
chord is ~51k samples).

Only the operations ``synth.py`` actually uses are implemented, and each one
matches numpy's behaviour for the shapes it is called with. This is a
compatibility shim, not an array library -- anything beyond that should make
the caller reach for real numpy instead.
"""
from __future__ import annotations

import math
import random
from typing import Iterable, Sequence

# Mirrors of the numpy names synth.py touches.
pi = math.pi
#: Only used as a tag for ``astype``; the conversion to 16-bit happens in
#: ``ndarray.tobytes``, which is where the value actually has to be an int.
int16 = "int16"


class ndarray(list):
    """A float list that supports the elementwise maths ``synth`` needs.

    Subclassing ``list`` keeps slicing, iteration and ``len()`` free, which is
    most of what the caller does with it.
    """

    __slots__ = ()

    # --- arithmetic ---------------------------------------------------------

    def _binary(self, other, operation) -> "ndarray":
        if isinstance(other, (int, float)):
            return ndarray(operation(value, other) for value in self)
        return ndarray(operation(a, b) for a, b in zip(self, other))

    def __add__(self, other):
        return self._binary(other, lambda a, b: a + b)

    __radd__ = __add__

    # list.__iadd__ *extends* rather than adding elementwise, so `mixed += osc`
    # silently concatenated the buffers and produced a clip several times too
    # long. Overriding it is essential, not cosmetic.
    def __iadd__(self, other):
        return self.__add__(other)

    def __imul__(self, other):
        return self.__mul__(other)

    def __isub__(self, other):
        return self.__sub__(other)

    def __itruediv__(self, other):
        return self.__truediv__(other)

    def __sub__(self, other):
        return self._binary(other, lambda a, b: a - b)

    def __rsub__(self, other):
        return self._binary(other, lambda a, b: b - a)

    def __mul__(self, other):
        return self._binary(other, lambda a, b: a * b)

    __rmul__ = __mul__

    def __truediv__(self, other):
        return self._binary(other, lambda a, b: a / b if b else 0.0)

    def __neg__(self):
        return ndarray(-value for value in self)

    # --- the slice assignment apply_envelope relies on ----------------------

    def __setitem__(self, key, value):
        if isinstance(key, slice) and not isinstance(value, (list, tuple)):
            indices = range(*key.indices(len(self)))
            for index in indices:
                list.__setitem__(self, index, value)
            return
        list.__setitem__(self, key, value)

    def __getitem__(self, key):
        result = list.__getitem__(self, key)
        return ndarray(result) if isinstance(key, slice) else result

    # --- reductions ---------------------------------------------------------

    @property
    def size(self) -> int:
        return len(self)

    def max(self) -> float:
        return max(self) if self else 0.0

    def min(self) -> float:
        return min(self) if self else 0.0

    def mean(self) -> float:
        return sum(self) / len(self) if self else 0.0

    def sum(self) -> float:
        return sum(self)

    def argmax(self) -> int:
        return max(range(len(self)), key=self.__getitem__) if self else 0

    def astype(self, dtype=None):
        """numpy would convert dtype here; we round at ``tobytes`` instead.

        Rounding early would make the array integers and break any later
        arithmetic, and nothing in synth.py depends on the intermediate type.
        """
        return self

    def tobytes(self) -> bytes:
        import array

        return array.array("h", (int(v) for v in self)).tobytes()


def array(values: Iterable[float]) -> ndarray:
    return ndarray(float(v) for v in values)


def zeros(count: int) -> ndarray:
    return ndarray([0.0] * max(0, int(count)))


def ones(count: int) -> ndarray:
    return ndarray([1.0] * max(0, int(count)))


def arange(count: int) -> ndarray:
    return ndarray(float(i) for i in range(int(count)))


def linspace(start: float, stop: float, count: int) -> ndarray:
    count = int(count)
    if count <= 0:
        return ndarray()
    if count == 1:
        return ndarray([float(stop)])
    step = (stop - start) / (count - 1)
    return ndarray(start + step * i for i in range(count))


def sin(values) -> ndarray:
    if isinstance(values, (int, float)):
        return math.sin(values)
    return ndarray(math.sin(v) for v in values)


def sign(values) -> ndarray:
    def one(value: float) -> float:
        return 0.0 if value == 0 else (1.0 if value > 0 else -1.0)

    if isinstance(values, (int, float)):
        return one(values)
    return ndarray(one(v) for v in values)


def abs(values):  # noqa: A001 - deliberately shadows the builtin, like numpy
    import builtins

    if isinstance(values, (int, float)):
        return builtins.abs(values)
    return ndarray(builtins.abs(v) for v in values)


def clip(values, low: float, high: float) -> ndarray:
    return ndarray(min(high, max(low, v)) for v in values)


def concatenate(chunks: Sequence[Sequence[float]]) -> ndarray:
    out = ndarray()
    for chunk in chunks:
        out.extend(chunk)
    return out


def isfinite(values) -> "ndarray":
    return ndarray(1.0 if math.isfinite(v) else 0.0 for v in values)


def array_equal(left, right) -> bool:
    return list(left) == list(right)


class _Generator:
    def __init__(self, seed: int) -> None:
        self._random = random.Random(seed)

    def uniform(self, low: float, high: float, count: int) -> ndarray:
        return ndarray(self._random.uniform(low, high) for _ in range(int(count)))


class _Random:
    @staticmethod
    def default_rng(seed: int = 0) -> _Generator:
        return _Generator(seed)


random_module = _Random()
#: ``np.random.default_rng(...)`` in synth.py resolves through this.
globals()["random"] = random_module
