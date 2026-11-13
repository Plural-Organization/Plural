import subprocess
import sys

reply = open(sys.argv[1]).read()
assert "req-7f3a91c2" in reply, reply[-300:]
assert "req-9d9d9d9d" not in reply, "named the slower request on another route"
assert not subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout, "files changed"
