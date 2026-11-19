# Cursus

Private, evidence-driven coordination for reviewed code and file deliverables.
The approved [roadmap](docs/cursus-implementation-roadmap-v0.1.1.md) and
[technical specification](docs/cursus-technical-specification-v0.1.2.md) define
the staged implementation. This public repository contains no deployment
credentials or private host inventory.

Version 0.2.0 implements the local single-package code pipeline (WP-03–08).
Live provisioning and M1 qualification (WP-02/09) remain pending. No milestone
tag has been created. Boundary fixtures do not prove provider or host capability.
See [qualification evidence](tests/qualification.md).

Requires CPython 3.12+, PostgreSQL 16+, and Git on Linux. Local verification uses
CPython 3.14.4/PostgreSQL 18.6; other versions and intended hosts are unverified.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
PIP_NO_INDEX=1 python -m build --wheel --no-isolation
python -m pip install --no-deps --force-reinstall dist/cursus-0.2.0-*.whl
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
control host. Subcommand help is offline. M1 admits one code package from inline
or pinned repository input; it verifies, reviews, stages, checks and confirms a
PR without merging. Interviews, debates, parallel phases, debugging, browser
routes and non-code delivery remain unavailable. Unexpected outcomes park work;
full reconnect/recovery controls arrive in WP-11.

Architecture records: [packaging](docs/decisions/0001-bootstrap-contracts-and-packaging.md),
[public provisioning](docs/decisions/0002-public-provisioning-boundary.md),
[storage and qualification gates](docs/decisions/0003-m1-storage-and-gates.md),
and [M1 execution](docs/decisions/0004-single-package-publication.md).
See [dependency licenses](docs/dependency-licenses.md) for locked artifact evidence.
