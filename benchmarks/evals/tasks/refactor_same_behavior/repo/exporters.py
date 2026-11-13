def to_csv(rows):
    kept = []
    for row in rows:
        if row.get("active") and row.get("email"):
            kept.append(row)
    kept.sort(key=lambda row: (row["name"].lower(), row["email"]))
    return "\n".join(f"{row['name']},{row['email']}" for row in kept)


def to_lines(rows):
    kept = []
    for row in rows:
        if row.get("active") and row.get("email"):
            kept.append(row)
    kept.sort(key=lambda row: (row["name"].lower(), row["email"]))
    return [f"{row['name']} <{row['email']}>" for row in kept]


def to_table(rows):
    kept = []
    for row in rows:
        if row.get("active") and row.get("email"):
            kept.append(row)
    kept.sort(key=lambda row: (row["name"].lower(), row["email"]))
    return {row["email"]: row["name"] for row in kept}
