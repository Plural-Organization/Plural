# Contributing

- Sign off every commit (`git commit -s`), we use the [DCO](https://developercertificate.org/).
- Conventional Commits, small PRs.
- Respect layer contracts (`uv run lint-imports`): `protocol` and `core` do no I/O, `relay` never decides permissions.
- Every tool call goes through `PolicyGate`. No bypasses, not even temporary ones.
- Protocol change: models → `uv run python scripts/gen_schema.py` → `npm run gen --workspace client` → `uv run python scripts/gen_fixtures.py` → `docs/protocol.md`.
- New behaviour ships with tests; harness tests use `FakeProvider`.
- Set-up, checks and the project layout are in [`docs/development.md`](docs/development.md).
