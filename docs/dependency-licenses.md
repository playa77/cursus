# Dependency license review — WP-01

Reviewed 2026-11-19 from the downloaded PyPI wheels and their complete bundled license files. The runtime closure and build tools below use permissive licenses. No optional extras are selected. All non-yanked release artifact hashes from each pinned PyPI JSON endpoint are allowlisted in `requirements.lock`; only the wheels listed below were locally installed/reviewed. Other platform artifacts require deployment verification. This is license evidence, not a security audit.

| Distribution | Version | License |
| --- | --- | --- |
| [annotated-doc](https://pypi.org/project/annotated-doc/0.0.7/) | 0.0.7 | MIT |
| [annotated-types](https://pypi.org/project/annotated-types/0.8.0/) | 0.8.0 | MIT |
| [anyio](https://pypi.org/project/anyio/4.16.0/) | 4.16.0 | MIT |
| [asyncpg](https://pypi.org/project/asyncpg/0.32.0/) | 0.32.0 | Apache-2.0 |
| [build](https://pypi.org/project/build/1.6.1/) | 1.6.1 | MIT |
| [click](https://pypi.org/project/click/8.5.1/) | 8.5.1 | BSD-3-Clause |
| [fastapi](https://pypi.org/project/fastapi/0.165.0/) | 0.165.0 | MIT |
| [flit_core](https://pypi.org/project/flit_core/4.2.0/) | 4.2.0 | BSD-3-Clause |
| [h11](https://pypi.org/project/h11/0.16.0/) | 0.16.0 | MIT |
| [idna](https://pypi.org/project/idna/3.20/) | 3.20 | BSD-3-Clause |
| [Jinja2](https://pypi.org/project/Jinja2/3.1.6/) | 3.1.6 | BSD-3-Clause |
| [MarkupSafe](https://pypi.org/project/MarkupSafe/3.0.4/) | 3.0.4 | BSD-3-Clause |
| [opentelemetry-api](https://pypi.org/project/opentelemetry-api/1.45.2/) | 1.45.2 | Apache-2.0 |
| [packaging](https://pypi.org/project/packaging/26.3/) | 26.3 | Apache-2.0 OR BSD-2-Clause |
| [pydantic](https://pypi.org/project/pydantic/2.14.4/) | 2.14.4 | MIT |
| [pydantic_core](https://pypi.org/project/pydantic_core/2.50.5/) | 2.50.5 | MIT |
| [pyproject_hooks](https://pypi.org/project/pyproject_hooks/1.3.3/) | 1.3.3 | MIT |
| [starlette](https://pypi.org/project/starlette/1.10.0/) | 1.10.0 | BSD-3-Clause |
| [typing_extensions](https://pypi.org/project/typing_extensions/4.16.0/) | 4.16.0 | PSF-2.0 |
| [typing-inspection](https://pypi.org/project/typing-inspection/0.4.5/) | 0.4.5 | MIT |
| [uvicorn](https://pypi.org/project/uvicorn/0.54.0/) | 0.54.0 | BSD-3-Clause |

## Inspected artifacts

Each entry records the wheel SHA-256, followed by the bundled license path and its SHA-256. Packaging also includes MIT-licensed license parsing code; flit_core bundles MIT tomli. typing_extensions includes the permissive historical Python license notices.

- `annotated_doc-0.0.7-py3-none-any.whl` — `6bc31bbbec6dfaaedc1676dbc11dbda96fe22a2b5c400e9ebad113fec44a9dc6`. `annotated_doc-0.0.7.dist-info/licenses/LICENSE`: `fff170779a6acbf65abdb405c087f1cee1786691e4a96a4034517e4a504a0cdf`
- `annotated_types-0.8.0-py3-none-any.whl` — `f072f4d804ea359e4eaf198b1af7a8b0943881a87f31bb764f8bf219bb9419e0`. `annotated_types-0.8.0.dist-info/licenses/LICENSE`: `fe1049884b1a0d9342901e88e07f32925d24b3121d9972b6a6805fb9824b095d`
- `anyio-4.16.0-py3-none-any.whl` — `c66ae634e0b8228396b801741beb3294326d4b6102f7bba4041c0dfb58c29026`. `anyio-4.16.0.dist-info/licenses/LICENSE`: `5361ac9dc58f2ef5fd2e9b09c68297c17f04950909bbc8023bdb82eacf22c2b0`
- `asyncpg-0.32.0-cp314-cp314-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl` — `63417b8f7369c54f6754c1fbd5a2968fbe632ff55bfbedd56a0177b6a96bd251`. `asyncpg-0.32.0.dist-info/licenses/LICENSE`: `d9222d73fdac50992174076efa04f44f6fbcd9d56155a7c7092e98757042a6f6`
- `build-1.6.1-py3-none-any.whl` — `ecd351a4be9d35a9eaaba244a7687143c9c7d4aea6ac964e7e7ddab20cbcf4e7`. `build-1.6.1.dist-info/licenses/LICENSE`: `aaf9a29ca5907971ccf07de025375db34539a8d5eeebce20b46099805722106f`
- `click-8.5.1-py3-none-any.whl` — `8bb5376d2006950386f8c6427613334a2acadc5f559cb80e638d00b4df957e37`. `click-8.5.1.dist-info/licenses/LICENSE.txt`: `9a8ad106a394e853bfe21f42f4e72d592819a22805d991b5f3275029292b658d`
- `fastapi-0.165.0-py3-none-any.whl` — `896f48462042bb4f162147eb8fac7e858753dc1f486765709baf105d70e4fc5b`. `fastapi-0.165.0.dist-info/licenses/LICENSE`: `4ec89ffc81485b97fec584b2d4a961032eeffe834453894fd9c1274906cc744e`
- `flit_core-4.2.0-py3-none-any.whl` — `2bee22dc8ba89c2e35b4e1ad575e596aac945c85672dd8f3cad21b629036e044`. `flit_core/vendor/tomli-1.2.3.dist-info/LICENSE`: `b80816b0d530b8accb4c2211783790984a6e3b61922c2b5ee92f3372ab2742fe`; `flit_core-4.2.0.dist-info/licenses/LICENSE`: `35b4f1dec512e617077fd6980dbb43ef8c2887adc5d0185edb4c04da175dd816`; `flit_core-4.2.0.dist-info/licenses/flit_core/vendor/tomli-1.2.3.dist-info/LICENSE`: `b80816b0d530b8accb4c2211783790984a6e3b61922c2b5ee92f3372ab2742fe`
- `h11-0.16.0-py3-none-any.whl` — `63cf8bbe7522de3bf65932fda1d9c2772064ffb3dae62d55932da54b31cb6c86`. `h11-0.16.0.dist-info/licenses/LICENSE.txt`: `37db5bb85926db28a427a25867f10b1232003aea1be69ccb851138adb8e6f361`
- `idna-3.20-py3-none-any.whl` — `ab7ae7122974553370f0bdb919e1a960b2cd1bc1ef0276416d896db81c14582c`. `idna-3.20.dist-info/licenses/LICENSE.md`: `1a9a4f0e3d479a27240ddd59a9137a66ab4a0f9dfdc8ca6188cc0bfd85187f04`
- `jinja2-3.1.6-py3-none-any.whl` — `85ece4451f492d0c13c5dd7c13a64681a86afae63a5f347908daf103ce6d2f67`. `jinja2-3.1.6.dist-info/licenses/LICENSE.txt`: `3b49dcee4105eb37bac10faf1be260408fe85d252b8e9df2e0979fc1e094437b`
- `markupsafe-3.0.4-cp314-cp314-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl` — `a8e9f292fcda89b324f2f5c91d13f1424a153e40fc2756f38ee23b15835ff300`. `markupsafe-3.0.4.dist-info/licenses/LICENSE.txt`: `489a8e1108509ed98a37bb983e11e0f7e1d31f0bd8f99a79c8448e7ff37d07ea`
- `opentelemetry_api-1.45.2-py3-none-any.whl` — `2cbd737377e710ee740d261c94e93fa0f08e6d037c18f17513cc0a2d94479a34`. `opentelemetry_api-1.45.2.dist-info/licenses/LICENSE`: `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`
- `packaging-26.3-py3-none-any.whl` — `d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c`. `packaging-26.3.dist-info/licenses/LICENSE`: `cad1ef5bd340d73e074ba614d26f7deaca5c7940c3d8c34852e65c4909686c48`; `packaging-26.3.dist-info/licenses/LICENSE.APACHE`: `0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594`; `packaging-26.3.dist-info/licenses/LICENSE.BSD`: `b70e7e9b742f1cc6f948b34c16aa39ffece94196364bc88ff0d2180f0028fac5`
- `pydantic-2.14.4-py3-none-any.whl` — `653a2ad9f6d8858529c77c72717d0ea991d6c6837fe683246b2f4b2bbfc3fadc`. `pydantic-2.14.4.dist-info/licenses/LICENSE`: `a9e186f3ca16b5eef84318e7a701721351a00cb7b8ae3a4394b67b49e3529ef3`
- `pydantic_core-2.50.5-cp314-cp314-manylinux2014_x86_64.manylinux_2_17_x86_64.whl` — `88b543705849d0c59343f97c38296dbf59eb7b3c9565bd4fe1ed638ba38da5ed`. `pydantic_core-2.50.5.dist-info/licenses/LICENSE`: `2afdd30d54b4d62b6f488a6bcc1546e84ec5061f13f4209c03d012348783795a`
- `pyproject_hooks-1.3.3-py3-none-any.whl` — `5fc53fdac9f7bd63fbcdc868fb5f90b4784d78a53a3d3388cd738b807441a20b`. `pyproject_hooks-1.3.3.dist-info/licenses/LICENSE`: `1b22b049b5267d6dfc23a67bf4a84d8ec04b9fdfb1a51d360e42b4342c8b4154`
- `starlette-1.10.0-py3-none-any.whl` — `478c0ab3b4ced6e82719849c118fa406f0278a3499c1a898cd15cd31bdc38ce4`. `starlette-1.10.0.dist-info/licenses/LICENSE.md`: `dcb95677a02240243187e964f941847d19b17821cf99e5afae684fab328c19bf`
- `typing_extensions-4.16.0-py3-none-any.whl` — `481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8`. `typing_extensions-4.16.0.dist-info/licenses/LICENSE`: `3b2f81fe21d181c499c59a256c8e1968455d6689d269aa85373bfb6af41da3bf`
- `typing_inspection-0.4.5-py3-none-any.whl` — `bc210535442b39e1bf2805e0c7a17dfd6a4ace760c84c7f7d16245d23a6b1c39`. `typing_inspection-0.4.5.dist-info/licenses/LICENSE`: `804b59b25f2c31bd278f9202a19ae49a3945aa2664387e2d0a128c7cacc61ec3`
- `uvicorn-0.54.0-py3-none-any.whl` — `505bdb0f318731d45f1f712071fc781a8981f6847a31c902c9f5e652d4f67faf`. `uvicorn-0.54.0.dist-info/licenses/LICENSE.md`: `efe1acf3e62fb99c288b0ec73e5a773b7268ef4320fe757ea994214e4b63c371`

## Selection and renewal

The initially considered setuptools 84.2.1 wheel contains LGPL autocommand and MPL validate-pyproject notices. It is excluded from the lock and build. flit_core 4.2.0 has no runtime dependencies and avoids those bundled components. The four runtime dependencies are prescribed by D2 §3; remaining packages are their mandatory closure or the build frontend/backend closure. No runtime modules import them until their assigned WP.

To renew: resolve the four direct dependencies plus build/flit_core in an isolated supported Python environment, download candidate wheels, inspect every direct/transitive bundled license and notice before selecting versions, then pin the complete closure. Retrieve each selected release’s PyPI JSON once (one request at a time, at least one second apart, 15s timeout, no retries) and allowlist its non-yanked artifact SHA-256 values. Check downloaded bytes against those hashes. Re-run the locked install, wheel build, clean install, and tests. Update this record, pyproject pins, ADR and changelog together. Cross-Python resolution must be checked on the deployment interpreter; local verification here uses CPython 3.14.4 only.

## WP-16 local browser asset

Vendored htmx **2.0.4**, from the pinned upstream tag, with its **Zero-Clause
BSD** license. This is the only third-party browser runtime; there is no frontend
build or remote asset request. `allowEval` and inline script processing are off.

- [Runtime source](https://github.com/bigskysoftware/htmx/blob/v2.0.4/dist/htmx.min.js)
  → `src/cursus/static/htmx.min.js`, SHA-256
  `e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447`.
- [License source](https://github.com/bigskysoftware/htmx/blob/v2.0.4/LICENSE)
  → `src/cursus/static/htmx.LICENSE`, SHA-256
  `d3d2456f76414f2456104660ebd65aff1c04cd7966b942bdabd63f3cdb316a38`.

The deployed CSS is the handoff's original Cursus stylesheet with production
bindings; no Proper UI catalog software or prototype JavaScript is shipped.
