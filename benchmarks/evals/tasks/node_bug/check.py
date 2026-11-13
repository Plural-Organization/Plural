import subprocess

assert not subprocess.run(["git", "diff", "--quiet", "--", "test.js"]).returncode, "test changed"
done = subprocess.run(["node", "test.js"], capture_output=True, text=True)
assert done.returncode == 0, done.stderr[-300:]
script = """const {slug}=require('./slug');console.log(slug(' Trim  Me '))"""
done = subprocess.run(["node", "-e", script], capture_output=True, text=True)
assert done.stdout.strip() == "trim-me", done.stdout
