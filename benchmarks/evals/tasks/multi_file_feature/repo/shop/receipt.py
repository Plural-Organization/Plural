from shop.tax import tax_for


def money(cents):
    return f"{cents // 100}.{cents % 100:02d}"


def receipt(cart):
    rows = [f"{name} x{quantity}  {money(cents * quantity)}" for name, cents, quantity in cart.lines]
    rows.append(f"Tax  {money(tax_for(cart.subtotal()))}")
    rows.append(f"Total  {money(cart.total())}")
    return "\n".join(rows)
