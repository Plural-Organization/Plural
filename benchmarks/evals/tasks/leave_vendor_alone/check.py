import subprocess
import sys

assert not subprocess.run(["git", "status", "--porcelain", "vendor"], capture_output=True, text=True).stdout, "vendor changed"
done = subprocess.run([sys.executable, "report.py"], capture_output=True, text=True)
assert done.returncode == 0, done.stderr
assert "north" in done.stdout and "120" in done.stdout, done.stdout
assert "7" in done.stdout and "44" in done.stdout, done.stdout
