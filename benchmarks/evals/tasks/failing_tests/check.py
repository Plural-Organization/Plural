import subprocess
import sys

sys.path.insert(0, ".")
assert not subprocess.run(["git", "diff", "--quiet", "--", "test_durations.py"]).returncode, "tests changed"
done = subprocess.run([sys.executable, "-m", "unittest"], capture_output=True, text=True)
assert done.returncode == 0, done.stderr
from durations import parse, render

assert render(7322) == "2h2m2s"
assert render(60) == "1m"
assert parse(render(86399)) == 86399
for bad in ("", "12", "1x"):
    try:
        parse(bad)
    except ValueError:
        continue
    raise AssertionError(f"{bad!r} must be refused")
