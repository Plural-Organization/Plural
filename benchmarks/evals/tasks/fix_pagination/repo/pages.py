def page(items, size):
    if size < 1:
        raise ValueError("size must be positive")
    count = len(items) // size
    return [items[i * size : (i + 1) * size] for i in range(count)]
