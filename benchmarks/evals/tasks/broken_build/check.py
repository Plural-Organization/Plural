import pathlib
import shutil
import subprocess

shutil.rmtree("dist", ignore_errors=True)
done = subprocess.run(["sh", "build.sh"], capture_output=True, text=True)
assert done.returncode == 0, done.stderr[-300:]
page = pathlib.Path("dist/site/index.html").read_text()
assert "<h1>Plural</h1>" in page, page
assert "2026" in page and "Plural</footer>" in page, page
assert "$" not in page, page
