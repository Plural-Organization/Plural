import json
import subprocess
import sys

plain = subprocess.run([sys.executable, "count.py", "notes.txt"], capture_output=True, text=True)
assert plain.stdout == "notes.txt: 2 lines, 3 words\n", plain.stdout
data = subprocess.run([sys.executable, "count.py", "--json", "notes.txt"], capture_output=True, text=True)
assert json.loads(data.stdout) == {"lines": 2, "words": 3, "path": "notes.txt"}, data.stdout
assert "--json" in open("README.md").read()
