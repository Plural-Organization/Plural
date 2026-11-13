from shop.tax import tax_for


class Cart:
    def __init__(self):
        self.lines = []

    def add(self, name, cents, quantity=1):
        self.lines.append((name, cents, quantity))

    def subtotal(self):
        return sum(cents * quantity for _, cents, quantity in self.lines)

    def total(self):
        return self.subtotal() + tax_for(self.subtotal())
