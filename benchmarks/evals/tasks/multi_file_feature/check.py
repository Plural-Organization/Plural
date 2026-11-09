import sys

sys.path.insert(0, ".")
from shop.cart import Cart
from shop.discounts import UnknownCode
from shop.receipt import receipt

cart = Cart()
cart.add("pen", 999, 2)
plain = receipt(cart)
assert "Discount" not in plain, plain
assert cart.total() == 1998 + 399
cart.apply_code("SAVE10")
assert cart.total() == 1799 + 359, cart.total()
cart.apply_code("HALF")
assert cart.total() == 999 + 199, cart.total()
rows = receipt(cart).splitlines()
places = [i for i, row in enumerate(rows) if "Discount" in row]
assert len(places) == 1 and "HALF" in rows[places[0]], rows
assert rows[places[0] + 1].startswith("Tax"), rows
assert rows[places[0] + 1].endswith("1.99"), rows
assert rows[-1].endswith("11.98"), rows
try:
    cart.apply_code("NOPE")
except UnknownCode:
    pass
else:
    raise AssertionError("unknown code accepted")
