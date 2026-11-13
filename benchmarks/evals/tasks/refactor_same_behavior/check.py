import ast
import pathlib
import sys

sys.path.insert(0, ".")
from exporters import to_csv, to_lines, to_table

rows = [
    {"name": "bo", "email": "b@x", "active": True},
    {"name": "Al", "email": "z@x", "active": True},
    {"name": "al", "email": "a@x", "active": True},
    {"name": "Cy", "email": "", "active": True},
    {"name": "Di", "email": "d@x", "active": False},
    {"name": "Ed", "active": True},
]
assert to_csv(rows) == "al,a@x\nAl,z@x\nbo,b@x"
assert to_lines(rows) == ["al <a@x>", "Al <z@x>", "bo <b@x>"]
assert to_table(rows) == {"a@x": "al", "z@x": "Al", "b@x": "bo"}
source = pathlib.Path("exporters.py").read_text()
assert source.count(".sort(") + source.count("sorted(") == 1, "sorting still repeated"
tree = ast.parse(source)
assert len([n for n in tree.body if isinstance(n, ast.FunctionDef)]) >= 4, "no helper"
