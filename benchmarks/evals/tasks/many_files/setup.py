import pathlib
import random

rng = random.Random(11)
folder = pathlib.Path("services")
folder.mkdir()
for index in range(60):
    channel = rng.choice(["stable", "stable", "beta", "canary", "stable-candidate"])
    version = f"1.{rng.randint(0, 9)}.{rng.randint(0, 9)}"
    body = f"name: service-{index:02d}\nchannel: {channel}\nversion: {version}\nreplicas: {rng.randint(1, 5)}\n"
    (folder / f"service-{index:02d}.yaml").write_text(body)
