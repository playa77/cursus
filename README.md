# Cursus

Private, evidence-driven coordination for reviewed code and file deliverables.
The approved [roadmap](docs/cursus-implementation-roadmap-v0.1.1.md) and
[technical specification](docs/cursus-technical-specification-v0.1.2.md) define
the staged implementation. This public repository contains no deployment
credentials or private host inventory.

Version 0.5.0 implements the source work through WP-16, including durable
verification artifacts and the accepted private browser design. User qualification
and live testing are deferred until the end of M3 (WP-17); live provisioning and
M0/M1/M2/M3 acceptance remain pending.
No milestone tag has been created. Boundary fixtures do not prove provider or host capability.
See [qualification evidence](tests/qualification.md).

Install with the [worker/controller setup scripts](ops/setup.md). The worker
script creates 16 reusable execution accounts. Choose worker concurrency (1–4)
and each frontier provider (1–2) explicitly; no shared frontier cap or per-agent
account provisioning. See [ADR 0008](docs/decisions/0008-execution-pool-and-hardware-admission.md) for resource and credential boundaries.

Requires CPython 3.12+, PostgreSQL 16+, and Git on Linux. WP-15/16 local verification uses
CPython 3.12.14/PostgreSQL 18.6; earlier packages also used CPython 3.14.4.
Intended deployment hosts remain unverified.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
PIP_NO_INDEX=1 python -m build --wheel --no-isolation
python -m pip install --no-deps --force-reinstall dist/cursus-0.5.0-*.whl
cursus --help
python -m unittest discover -s tests/unit
python -m pip check
```

The lock includes the build backend. The [runbook](ops/runbook.md) describes
startup, identities and disposable PostgreSQL integration tests. Set
`CURSUS_TEST_DSN` to an authorized disposable database before running
`python -m unittest discover -s tests/integration`. Tests create and remove only
their own random schemas. Model execution uses local executable fixtures.

Deploy the committed role/prompt release, replace the unqualified configuration
worksheets using actual capability measurements, then start separate services:

```text
cursus control --config /etc/cursus/control.toml
cursus runner --config /etc/cursus/runner.toml
cursus submit --input /absolute/input.json
cursus status --phase-id UUID
```

`submit`, `action`, and `status` use a protected operator Unix socket on the
control host. Subcommand help is offline. Code phases support dependency graphs,
parallel workers, independent delivery groups and serialized integration. Debugging retains one pi RPC process across
independently verified checkpoints. Guided interviews and optional three-seat
debates use durable revisions. Recovery preserves ownership across disconnects;
unknown outcomes require evidence or explicit abandonment. Target drift receives
bounded revalidation before PR delivery. The private Serve browser exposes existing actions, committed SSE history and
authorized evidence downloads with local assets and no frontend build. Non-code
delivery remains unavailable until WP-18.

Architecture records: [packaging](docs/decisions/0001-bootstrap-contracts-and-packaging.md),
[public provisioning](docs/decisions/0002-public-provisioning-boundary.md),
[storage and qualification gates](docs/decisions/0003-m1-storage-and-gates.md),
[M1 execution](docs/decisions/0004-single-package-publication.md),
[M2 scope](docs/decisions/0005-m2-state-and-qualification.md), and
[debug and conversations](docs/decisions/0006-m2-debug-and-conversations.md), and
[M3 artifacts/browser](docs/decisions/0007-m3-artifacts-and-browser.md).
See [dependency licenses](docs/dependency-licenses.md) for locked artifact evidence.
