import random

rng = random.Random(7)
routes = ["/home", "/search", "/cart", "/checkout", "/login"]
rows = []
for index in range(40000):
    route = rng.choice(routes)
    status = rng.choice([200, 200, 200, 200, 302, 404, 500])
    rows.append(f"{index:08d} route={route} status={status} latency_ms={rng.randint(5, 4000)} request_id=req-{index:08x}")
rows.insert(31000, "31000x route=/checkout status=500 latency_ms=9120 request_id=req-7f3a91c2")
rows.insert(12000, "12000x route=/search status=500 latency_ms=9990 request_id=req-9d9d9d9d")
rows.insert(20000, "20000x route=/checkout status=200 latency_ms=9950 request_id=req-8c8c8c8c")
open("server.log", "w").write("\n".join(rows) + "\n")
