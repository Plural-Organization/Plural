import re

UNITS = {"s": 1, "m": 60, "h": 3600}


def parse(text):
    """Seconds in a duration such as 90s, 2m or 1h30m."""
    total = 0
    for amount, unit in re.findall(r"(\d+)([smh])", text):
        total += int(amount) * UNITS[unit]
    return total


def render(seconds):
    hours = seconds // 3600
    minutes = seconds // 60
    rest = seconds % 60
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if rest or not parts:
        parts.append(f"{rest}s")
    return "".join(parts)
