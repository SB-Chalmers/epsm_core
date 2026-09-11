# EnergyPlus optimization experiments

These scripts are workflow tools, not compiler configuration profiles. Use a directory
outside the checkout for raw SQL and simulation artifacts. Never reuse a nonempty run
directory. EnergyPlus 24.2, the geometry extra and `psutil` (batch memory sampling) are
required for the complete campaign. macOS `/usr/bin/time -l` supplies CPU/RSS metrics.

```sh
python benchmarks/optimization.py freeze /path/to/artifacts
python benchmarks/optimization.py compare /path/to/artifacts --repetitions 3
python benchmarks/optimization.py summarize /path/to/artifacts
python benchmarks/optimization.py shadow /path/to/artifacts
python benchmarks/optimization.py context /path/to/artifacts
python benchmarks/optimization.py context-pruned /path/to/artifacts
python benchmarks/solar_accuracy.py /path/to/artifacts context_pruned
python benchmarks/proximity.py /path/to/artifacts/proximity
python benchmarks/corpus_compile.py /path/to/artifacts/corpus
python benchmarks/throughput.py /path/to/artifacts isolated
```

Freeze must run before changing the compiler. It preserves the exact models, physical
specifications, compilation reports, SQL, original diagnostics and per-run measurements.
The comparison reloads those physical specifications, preserving context exactly.
Experiments isolate thermal geometry, output requests, clipping algorithm, figure capacity,
timestep and the combined candidate. Model hashes identify every execution configuration.

The radius campaigns use 80/100/120/160/240 m, three climates, three shapes and stratified
0/45/90° orientations and seeds 0/17/41. `context` retains every face; `context-pruned`
holds the proven face-pruning algorithm fixed across all radii and retains every building.
Both use an explicit one-million-figure *validation* cap, with no retry. A capped reference
fails acceptance. The mirroring experiment likewise uses matched capacity on both sides.
Validation requests target thermal surfaces explicitly, avoiding context-wide solar output.

Acceptance uses 1% annual energy/solar, 2% monthly and hourly-average load peaks, and
0.1°C maximum hourly-average temperature difference. Absolute floors are 0.1 kWh/m²
annually, 0.01 kWh/m² monthly and 0.1 W/m² for load peaks. Surface solar uses 1% annual,
2% monthly with a 0.1 kWh/m² incident / 0.1 kWh transmitted absolute floor. Daylight
sunlit fraction uses MAE ≤0.01, p95 ≤0.05 and at most 1% of samples differing by >0.1.
Maximum disagreement duration is also recorded. A radius needs two larger passing
comparisons; the largest tested radius is never automatically a reference truth.

`throughput.py` measures 12 precompiled cases per configuration at two workers, with
sampled aggregate RSS. `workflow_throughput.py ARTIFACTS SOURCE_DIRECTORY LABEL` uses
the public runner for nine cases at two workers, including prospective run identity,
compilation, output validation and (for the old implementation) previews.

Timing runs must not overlap other benchmark or corpus jobs. Cache state is uncontrolled
and generally warm after the first run; these scripts do not claim cold-cache results.
macOS I/O-wait measurement is unavailable. See [measured results](../docs/optimization-results.md).
