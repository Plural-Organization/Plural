# Contributing

- Sign off every commit (`git commit -s`), we use the [DCO](https://developercertificate.org/).
- Conventional Commits, small PRs.
- Respect layer contracts (`uv run lint-imports`): `protocol` and `core` do no I/O, `relay` never decides permissions.
- Every tool call goes through `PolicyGate`. No bypasses, not even temporary ones.
- Protocol change: models → `uv run python scripts/gen_schema.py` → `docs/protocol.md` → golden fixtures.
- New behaviour ships with tests; harness tests use `FakeProvider`.
