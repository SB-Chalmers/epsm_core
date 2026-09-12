# Geometry and EnergyPlus optimization — 2026-09-11

Implemented generation-time assertions and shared vertex identities, cyclic-only
serialization, deterministic nested synthetic context, closed context-shell proofs,
lean keyed outputs, explicit shading settings and single-attempt execution. Automatic
previews, shadow recovery, whole-model canonicalization and the Uppsala-specific policy
were removed. Their original source is preserved in the campaign baseline archive.

## Measured production candidate

Apple M4 Pro, 14 cores, 24 GiB RAM, macOS 26.6.2 arm64; EnergyPlus
24.2.0-94a887817b. Annual Gothenburg cases use active cooling at 24°C, heating at
21°C, whole-building Ideal Loads zoning and exactly the frozen context specifications.
One EnergyPlus process/thread, randomized configuration order, three repetitions.

| Target | Previous median | Candidate median | Runtime retained | SQL previous → candidate |
|---|---:|---:|---:|---:|
| Rectangle | 3.044 s | 1.461 s | 48.0% | 19.29 → 1.33 MB |
| L shape | 3.488 s | 1.930 s | 55.3% | 28.88 → 1.33 MB |
| Courtyard | 4.391 s | 2.525 s | 57.5% | 39.66 → 1.33 MB |

All combined six-timestep cases passed annual/monthly energy and solar, hourly-average
load-peak and hourly-average temperature comparisons against the frozen reference.
The runtime ≤65% and SQL ≤35% targets passed. Geometry-only serialized thermal models
were identical in the three frozen cases. Output-only and capacity-only tests passed
independently. Clipping changes showed no consistent ≥5% benefit; SutherlandHodgman remains.

The two-worker **precompiled** batch improved from 27.60 to 59.68 buildings/minute
(12 buildings/configuration). Aggregate sampled RSS fell from 3.657 to 0.452 GB;
total CPU time fell from 39.59 to 22.88 s, with zero failures.
The **public runner** batch, including compilation and result processing, improved from
19.79 to 41.78 buildings/minute (nine buildings/configuration; 27.28 → 12.93 s).
The first precompiled batch overlapped corpus compilation and was excluded in favor
of the isolated repeat. Cache state was uncontrolled/warm; no cold-cache claim is made.

## Defaults deliberately not promoted

**Four timesteps failed.** Against six, maximum hourly-average temperature differences
were 0.244°C, 0.218°C and 0.246°C for rectangle, L shape and courtyard. These exceed
the agreed 0.1°C criterion, despite small annual-energy differences. Twelve timesteps
also revealed sensitivity relative to six. The production default remains six; no
claim is made that the existing six-timestep model is an independently converged truth.

**No smaller context radius was certified.** The 45-run, pruned-context radius matrix
covered Malmö/Gothenburg/Kiruna, all three shapes, stratified orientations and seeds,
and 80/100/120/160/240 m. Annual energy comparisons were less restrictive than the
surface sunlit-fraction checks. No radius with two available larger contexts passed
the complete acceptance gate. The 160/240 m entries lacking two larger comparisons
are inconclusive, not measured accuracy failures. The existing 100 m default remains
an illustrative scenario choice, not a validated physical cutoff.

The unpruned 240 m Malmö rectangle reference exceeded even the explicit 1,000,000
validation capacity. The pruned 240 m Gothenburg L-shape case hit the overlap polygon
vertex limit (≥15); increasing figure capacity does not address that separate limit.
Such runs cannot certify convergence. No production limit was silently increased and no engine retry
was introduced. Further radius certification needs a usable larger reference and
the remaining tall-obstruction / orientation coverage; 80 m is not approved.

## Dense campaign capacity correction — 2026-09-12

The production compiler now emits a 1,000,000-figure shadow-overlap allowance. The
previous 15,000 setting was validated only on the simpler frozen performance cases and
failed exact dense-campaign inputs with 238–375 retained shading faces. Re-running those
unchanged epJSON models at 1,000,000 completed without shadow warnings and without a
material local runtime increase. This is the same capacity used by the dense-context
validation matrix above; PolygonClipping/SutherlandHodgman, geometry pruning, mirroring,
strict diagnostics and single-attempt execution are unchanged.

## Geometry and diagnostics evidence

Full-versus-pruned context and matched-capacity mirroring comparisons passed separately
for all three shapes, including individual surface solar and daylight sunlit fractions.
Standalone planes and deliberately opened shells fail the mirror eligibility proof.
Explicit context specifications remain intact and complete context geometry remains
visible in inspection artifacts.

Pinned-executable chamfer probes at 1 µm, 10 µm, 0.1 mm and 1 mm offsets triggered
vertex dropping; a 10 mm offset (14.14 mm diagonal edge) passed. The emitted warning
identifies the engine's 0.01 m edge cutoff. The application minimum is 0.010001 m.
Hip-roof generation now interprets the skeleton backend's closed index rings before
emitting open face rings. No serializer winding repair is permitted.

The complete unit/integration suite passed: **529 passed, one optional-dependency skip**.
All **277 accepted real-world footprint fixtures** additionally compiled with the new
invariants; 23 existing preparation rejections remain outside that accepted corpus.
EnergyPlus initialization area, volume and thermal-mass areas are reconciled during
result reading. The larger full-cross-product/reference campaign, aligned transient
temperature study, cold-cache measurements and full corpus annual simulation remain
outside the completed evidence; this is not certification of every definition-of-done item.

## Artifacts and reproduction

Campaign artifacts are retained at `/private/tmp/epsm-optimization-2Nb0Jc`, including
`source-baseline.tar.gz`, baseline models/SQL, 81 randomized settings experiments,
the independent shading experiments, both context campaigns, close-vertex probes,
corpus outcomes and both throughput measurements. Failed/superseded experiments are
retained and excluded from acceptance. See [benchmark instructions](../benchmarks/README.md).
No SQL binaries are added to the repository. Preserve the campaign directory outside
temporary storage if these raw artifacts are needed long term.

A compressed copy is retained in the project's ignored output directory at
`output/optimization-20260911-0dKbxW/campaign.tar.gz`. It includes the original source
archive and all raw experiments, while excluding the temporary dependency installation
and redundant extracted baseline source.
