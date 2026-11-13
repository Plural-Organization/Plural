import sys

sys.path.insert(0, ".")
from pages import page

assert page(list(range(10)), 3) == [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9]]
assert page(list(range(9)), 3) == [[0, 1, 2], [3, 4, 5], [6, 7, 8]]
assert page([], 3) == []
try:
    page([1], 0)
except ValueError:
    pass
else:
    raise AssertionError("size 0 must still be refused")
