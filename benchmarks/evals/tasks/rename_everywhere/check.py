import subprocess
import sys

sys.path.insert(0, ".")
found = subprocess.run(["grep", "-rn", "fetch_user", ".", "--exclude-dir=.git", "--exclude-dir=__pycache__"], capture_output=True, text=True)
assert not found.stdout, found.stdout
done = subprocess.run([sys.executable, "-m", "unittest"], capture_output=True, text=True)
assert done.returncode == 0, done.stderr
from app.plugins import call
from app.store import load_account

assert load_account(1) == "ada"
assert call("user", 1) == "ada"
assert "load_account" in open("docs/api.md").read()
