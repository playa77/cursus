# Cursus

Private, evidence-driven coordination for reviewed code and file deliverables.
The approved [roadmap](docs/cursus-implementation-roadmap-v0.1.1.md) defines the
staged implementation. This public repository contains no deployment credentials
or private host inventory.

## Bootstrap (WP-01)

Requires CPython 3.12+ on Linux; unit ref conformance checks also require Git.
Locally verified on CPython 3.14.4/Linux: hash-locked install, isolated wheel
build, wheel reinstall, offline help, 13 unit tests, and `pip check` passed on
2026-11-19. CPython 3.12/3.13 and deployment hosts have not been tested.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
PIP_NO_INDEX=1 python -m build --wheel --no-isolation
python -m pip install --no-deps --force-reinstall dist/cursus-*.whl
cursus --help
python -m unittest discover -s tests/unit
python -m pip check
```

The lock includes build tools, so `--no-isolation` uses the already hash-verified
backend without a second dependency download. For an isolated build, pre-download
the lock to a private wheelhouse and use
`PIP_NO_INDEX=1 PIP_FIND_LINKS=/absolute/wheelhouse python -m build --wheel`.
The CLI currently provides offline help and version only. Runtime commands and
services are introduced in later work packages.

[ADR 0001](docs/decisions/0001-bootstrap-contracts-and-packaging.md) records package
and contract choices; [dependency licenses](docs/dependency-licenses.md) records
artifact inspection. Deployment examples and a provisioning runbook arrive in WP-02.
A public template does not prove live authentication or release readiness.
