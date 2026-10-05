# Opt-in context shadow recovery

EnergyPlus PolygonClipping can exhaust its 1,000,000-figure workspace even for
valid building geometry. Repeated context facade projections produce many
shadow polygons. A smaller context radius can leave the responsible geometry
inside the remaining scene. This policy retains the context radius and all
neighbours while simplifying only their shading footprints.

## Usage and scope

```python
result = runner.run(building, "output/new-run", recover_context_shadows=True)
```

The default is `False`. Enabling this option authorizes an approximate shading
model, not an exception to warning acceptance. It does not enable PixelCounting,
change the shadow workspace, reduce context radius, modify thermal target
geometry, or change neighbour heights/base elevations, weather or systems.

The runner first executes the original scene. Only an isolated
`SHADOW_COMPLEXITY_LIMIT`, with zero process error, severe/fatal errors or other
unapproved warning categories, permits a retry. It then tries 1 m and 2 m
context simplification, stopping at the first fully validated success. Each
candidate is generated from the original scene, never from the previous retry.
The existing small-cap context cleanup still runs independently during compilation.

## Geometry safeguards

Shapely topology-preserving simplification is applied to outer rings only.
Courtyard coordinates stay exact. A footprint remains unchanged if its
symmetric-difference area exceeds 10% of the original area, its measured boundary
Hausdorff displacement exceeds the requested tolerance, or it becomes invalid.
Symmetric difference measures both removed and added area, not just net area.

After assembling a candidate scene, Core compares original and proposed boundary
contact sets against the target and every other context footprint. Changed
contacts or any plan overlap above 1e-8 m² reject the entire candidate. This
protects shared-wall evidence; it does not qualify the new shadow approximation.
Unchanged or unsafe candidates skip engine execution. Normal compiler shell,
face and emission proofs and engine/SQL validation remain mandatory. Mixed
failures stop immediately; exhausted retries remain rejected.

## Artifacts and scientific interpretation

Every attempted model, input specification, compilation report, process log and
result/diagnostic receipt remains in `shadow-recovery/original`,
`shadow-recovery/context-1m`, or `shadow-recovery/context-2m`. Root-level artifacts
are copies of the selected successful attempt, or the last failed attempt. Root
`result.json` is written only after a fully validated success; it binds the actual
candidate model's run identity. Returned artifact paths point to the promoted
files. Existing output directories must still be empty.

`shadow-recovery.json` and `diagnostics.shadow_recovery` record policy
`context-shadow-simplification-1`, each attempt's identity/disposition, selected
attempt, and whether an approximation was used. Candidate generation metadata
records source/prepared rings, per-footprint areas, exchanged-area fractions and
boundary displacements. `sensitivity_review_required=True` marks a selected
approximation, including failed candidates. A successful original run sets it
False. The timeout is per engine attempt; enabling recovery may launch three
annual simulations, and all artifact copies increase disk use.

A successful simulation is not an archetype or calibration qualification.
Simplification can remove real balconies or other projections, and a small
annual heating difference does not establish hourly solar or cooling accuracy.
Review sensitivity before combining recovered runs with strict cohort results.

## Local evidence, 2026-10-05

Two retained national-sample failures were replayed at 100 m with context-only
0.5 m, 1 m and 2 m simplification and unchanged engine capacity. At 0.5 m both
still failed; at 1 m the first passed and the second failed; at 2 m both passed.
All successful runs had zero warnings and passed annual output validation.

Relative to successful unsimplified 100 m GPU/PixelCounting runs (512 resolution),
annual space-heating demand changed by -0.003331% for building `5619fdfd` at 1 m,
and -0.004814% for building `90285664` at 2 m. In the latter scene, context shading
faces fell from 473 to 114. Maximum individual footprint exchanged area approached
10%, despite the small annual heating differences. GPU resolution convergence
and broader-cohort shading accuracy remain unqualified. These observations
support an opt-in recovery policy rather than a universal geometry default.

The workflow retains original receipts and isolated replay evidence under
`output/national-mf-se02-random-baseline-2026-10-05-v2-roof-weather/geometry-review/`
including `aggressive-context-simplification-probe.json`. Frozen campaign totals
and calibration results are not rewritten by this Core change.
