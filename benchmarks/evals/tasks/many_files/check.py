import pathlib
import subprocess

expected = []
for path in sorted(pathlib.Path("services").glob("*.yaml")):
    original = subprocess.run(["git", "show", f"HEAD:{path}"], capture_output=True, text=True).stdout
    text = path.read_text()
    if "channel: stable\n" in original:
        expected.append(path.name)
        lines = [l if not l.startswith("version:") else "version: 2.0.0" for l in original.splitlines()]
        assert text.splitlines() == lines, path
    else:
        assert text == original, f"{path} changed"
assert pathlib.Path("changed.txt").read_text().split() == expected
