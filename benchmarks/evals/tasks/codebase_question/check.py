import re
import subprocess
import sys

reply = open(sys.argv[1]).read()
numbers = set(re.findall(r"(?<!\d)\d+(?!\d)", reply))
assert "5" in numbers, reply[-300:]
assert "12" in numbers, reply[-300:]
assert not subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout, "files changed"
