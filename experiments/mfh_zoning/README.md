# MFH layout prototype

This is an experimental Shapely comparison outside the `epsm_core` API. The 13 October 2026 native gate failed: only 10 of 15 MFH-labelled fixtures had any candidate that compiled through Core, below the required 12. No zoning mode was added to production.

The frozen source/preparation corpus is in `tests/fixtures/mfh_layouts/corpus.json`. The full analysis, matching PNG/SVG plots and per-case JSON are in `output/analysis/mfh-zoning-2026-10-13/`.

From the repository root, run:

```sh
.venv/bin/pytest -q tests/core/test_mfh_layouts.py
.venv/bin/python scripts/benchmark_mfh_layouts.py
.venv/bin/python scripts/mfh_stress_sweep.py --sweep --stress
```

The benchmark script reproduces the **refined** implementation. The `initial-*` files are the preserved pre-refinement results. The source-fixture creation script needs the saved Sweden experiment file named in its `--source` argument.

Native compilation and the four short EnergyPlus runs were performed with the temporary adapter archived as `core-trial.patch` alongside the report. `git apply --check` passes on the current checkout. The trial scripts require that patch to be applied on a disposable branch; they do not alter Core themselves.
