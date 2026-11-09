def render(rows):
    width = max(len(row[0]) for row in rows)
    return "\n".join(f"{row[0]:<{width}} {row[1]}" for row in rows)
