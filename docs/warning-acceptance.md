# EnergyPlus warnings and EPSM acceptance

`EnergyPlusRunner.run` uses two-stage diagnostic acceptance (`evidence-2`).
Known, bounded EnergyPlus 24.2 psychrometric warnings may proceed to output
validation. They become **accepted with warnings** only after that validation
passes. Other unapproved warnings, unsuccessful engine execution, severe/fatal
errors, geometry concerns, compromised shadow calculations and invalid outputs
continue to reject the run. Original warnings are retained in `diagnostics.json`
and the final result receipt.

## Why this replaces blanket rejection

The former `strict-1` runner rejected every unapproved warning before reading
SQL results. Its catch-all `ENERGYPLUS_NUMERICAL_FAILURE` label implied numerical
failure even when EnergyPlus had completed successfully. A review of the same
200-building national MF SE.02 baseline found 57 such policy rejections:

| Disjoint group | Buildings |
| --- | ---: |
| Internal wet-bulb iteration temperature warning only | 40 |
| Wet-bulb iteration-limit warning, including two also reporting temperature warnings | 4 |
| Small surface areas | 10 |
| Zone not fully enclosed | 1 |
| Shadow-overlap capacity exceeded | 2 |

All 57 reached successful engine completion without severe/fatal errors. Their
retained SQL outputs passed full-calendar, hourly/annual energy and geometry-total
reconciliation. This established that the rejection label alone was insufficient
proof of an invalid annual-heating prediction; it did not qualify all geometry
or shading assumptions.

All 42 temperature-range warnings name `PsyTwbFnTdbWPb`: 40 have one annual
occurrence, one has two and one has three. EnergyPlus passes its internal wet-bulb
estimate into `PsyPsatFnTemp` during iteration. An out-of-range estimate is not a
zone temperature. The saturation-pressure function bounds below-range values
and the wet-bulb routine can continue to converge. A wet-bulb iteration-limit
warning is different: the local solve exhausted 100 iterations and returns its
final estimate, limited above by the input dry-bulb temperature.

Reference: [EnergyPlus 24.2 psychrometric implementation](https://github.com/NREL/EnergyPlus/blob/v24.2.0/src/EnergyPlus/Psychrometrics.cc),
particularly `PsyTwbFnTdbWPb_raw` and `PsyPsatFnTemp_raw`.

Six warning cases were tested at 12 instead of six timesteps per hour: all four
near-freezing iteration-limit cases, the largest temperature excursion, and the
highest recurrence count. Annual heating changed by at most **0.008883%**; a clean
control changed by **0.012086%**. Some warnings persisted, while reported timestep
wet-bulb outputs remained within ordinary weather ranges. This supports a narrow
annual-heating disposition, not a general exception for convergence warnings.

## Eligibility before output validation

The default review (`psychrometric-annual-heating-1`) requires:

- EnergyPlus **24.2**, process return code zero, a successful-completion marker,
  and no severe/fatal messages.
- Ideal-loads systems with both humidification and dehumidification control set
  to `None`. Humidity-controlled systems are outside this review.
- Every otherwise-unapproved message must match one of the two cases below;
  mixed unknown, geometry or general HVAC-convergence warnings are rejected.
- Detailed evidence identifying the `ANNUAL` environment, with no recorded
  warmup or sizing occurrences.

| Reviewed message | Additional evidence | Annual occurrence limit |
| --- | --- | ---: |
| `Temperature out of range [-100. to 200.] (PsyPsatFnTemp)` | All reported callers are exactly `PsyTwbFnTdbWPb`. | 5 |
| `WetBulb not converged after 101/max iterations(PsyTwbFnTdbWPb)` | Detailed dry bulb 0–5°C, humidity ratio 0–0.01 kg/kg, pressure 31,000–120,000 Pa, final wet bulb within ±0.5°C. | 1 |

The limits conservatively bound the audited evidence, including the observed
five excursions in a finer-timestep variant. They are engineering review limits,
not universal scientific guarantees. Missing detailed context, other callers,
other engine versions, or counts above these limits retain rejection.

The initial `101 iterations` warning and recurring `max iterations` summary
represent one warning family. The parser now merges them, retaining both source
texts and the recurring total. This fixes double-counting the initial example
and its summary without merging unrelated convergence warnings.

## Validation and final disposition

Eligibility sets `warning_review_pending=True`; it never means acceptance.
The runner then uses the existing `read_results` checks: expected outputs, exact
8760/8784-hour calendar, finite hourly values, reconciled hourly/annual energy,
and agreement between engine and compiler geometry totals.

Final review additionally requires finite hourly outputs, nonnegative hourly
space-heating demand, and reported temperatures for every modeled zone strictly
inside the psychrometric domain of −100 to 200°C. These domain checks detect
invalid final states; they do not establish comfort or building-specific physical
accuracy.

After validation, every reviewed message retains its original text, count and
category, and gains `disposition="accepted_with_warning"` with a versioned
`exception_rule`. The run gains `disposition="accepted_with_warnings"` and
`warning_review` metadata containing limits, validation evidence and scope.
`result.json` is still written last, after delivery and PV accounting succeeds.

The scope is **annual space-heating demand**. Cooling, humidity control and
latent-load accuracy are explicitly unqualified by this rule. A warning-accepted
result must not be presented as validating those applications. Routine completion
and small timestep sensitivity also do not validate site weather or archetype
accuracy against measurements.

## API and strict opt-out

Default behavior:

```python
result = runner.run(building, "output/fresh-run")
print(result.diagnostics.get("disposition"))
print(result.diagnostics.get("warning_review"))
```

Require warning-strict acceptance when appropriate:

```python
result = runner.run(
    building,
    "output/fresh-strict-run",
    review_psychrometric_warnings=False,
)
```

`error_diagnostics` remains a strict parser without result evidence: calling it
alone does not approve these warnings. Explicit existing `WarningRule` exceptions
continue to work under their original engine/condition/count requirements.
Generic convergence failures cannot be waived by a broad rule. The runner's
specific post-validation review is distinct from such blanket exceptions.

Unapproved warning-only cases now receive `WARNING_POLICY_REJECTION` rather than
the catch-all numerical-failure code. Hard convergence/process failures retain
`ENERGYPLUS_NUMERICAL_FAILURE`; geometry and shadow failures retain their own
categories. `not fully enclosed` is now recognized as invalid geometry.

## Reproducibility and verification

This source change changes the compiler/campaign identity. Existing frozen study
receipts, metrics and old acceptance decisions are not modified or silently
reused. Prepare a new campaign to apply this policy to scientific results.
The 44-case recovery audit reads the retained outputs independently; it is not a
replacement for the old campaign's signed/frozen results.

Regression tests cover context/count/version bounds, recurring-message merging,
unknown and mixed warnings, humidity-control exclusion, incomplete engine runs,
invalid final temperatures and strict opt-out. Real-engine runner tests inject a
known warning into otherwise completed fixture logs solely to verify control-flow
ordering; separate fresh runs exercise actual warning-producing cohort models.

Local evidence from the 5 October 2026 national rerun is retained in the workflow
repository under `output/national-mf-se02-random-baseline-2026-10-05-v2-roof-weather/warning-policy-review`:
`assessment.json/html`, `output-audit.json`, `sensitivity.json`, source scripts,
`proposed-core-policy-verification.json`, and `core-runner-smoke.json`.
