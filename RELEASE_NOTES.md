# Core 0.8.1 — RC context readiness

RC readiness now accepts explicit context buildings for the ISO 13790 hourly
horizon method implemented by RC 0.8.3. Facade overhangs, reveals and balconies
remain unsupported by that adapter. Physical context, scene exports, EnergyPlus
compilation and thermal input formats retain their existing contracts.

# Core 0.8.0 — separate viewer ownership

- Browser rendering, JavaScript assets, local preview hosting and optional
  notebook widgets move to the independent `epsm_viewer` package. Core has no
  viewer runtime dependency.
- `Building.scene()`, `GeometrySpec.scene()` and `BuildingSpec.scene()` export
  detached `epsm.scene/1` polygons, opening rings, metric coordinate information
  and inspection metadata. Physical Building exports retain owner and snapshot
  identities. No weather, engine, server or browser is required.
- The removed `.view()`, `.widget()`, `preview_geometry`, viewer module and
  `epsm-core view` APIs have explicit replacements in the
  [viewer migration guide](docs/viewer-migration.md). Rendering triangulation and
  display lifecycle now belong to Viewer; Studio owns application adapters.
- This pre-1.0 API break changes display ownership. The scene format remains
  `epsm.scene/1`; physical inputs, numerical methods and engine output formats
  retain their existing contracts. Install the independent Viewer artifact
  explicitly when display is needed.

# Core 0.7.1 — shared snapshot preparation

- Physical snapshot resolution shares one validated conversion, geometry graph
  and physical owner mapping. The advanced `resolve_snapshot_inputs` handoff
  returns that specification, read-only resolved view and caller-owned Building.
  Existing snapshot and resolved export formats are unchanged.
- Snapshot restoration decodes each physical assignment once. The read-only
  resolved view parses its JSON once on inspection while detached exports and
  portable serialization retain their existing behavior.
- `hourly_schedule_scope()` shares immutable expansions within one preparation
  and calculation call, including nested validation and energy accounting.
  Independent calls retain no schedule cache.
- EPW calendar validation accepts an explicit captured text stream as well as a
  path. Reduced domains can pass validated airflow directly to
  `heating_delivery_for_domain`, sharing the existing energy accounting without
  constructing a compiler report or reconstructing airflow models.
- Geometry cache implementation identity is captured lazily once per process.
  Restart after editing sources; later lookups do not reread or check source
  metadata. The cache still returns detached working graphs.
- The ten-layer construction limit belongs to EnergyPlus readiness, preflight
  and compilation. RC and physical snapshot inspection accept longer explicit
  constructions. Existing numerical behavior is preserved.

See [prepared geometry and shared inputs](docs/geometry-cache.md).

# Core 0.7.0 — physical roofs and basement controls

- Cold attics retain their separate ceiling, actual sloped weather-shell area and
  gable walls. Shell and ceiling constructions remain explicit physical inputs;
  thermal faces and material quantities refer to the same installed elements.
- Conditioned basement slabs, ground walls and internal separating floors retain
  their physical boundaries and shared-wall ownership. A separating floor is not
  counted as an additional ground boundary.
- Physical Buildings retain declared `zone_uses` and `unconditioned_exchange`
  through snapshots and the EnergyPlus handoff. No attic ventilation rate or
  basement thermostat is inferred by Core.
- Snapshot format 8 stores these operations. Older formats remain readable and
  keep their identity until edited. Old incomplete attic inventories or outdated
  basement-interface metadata require explicit geometry regeneration before
  simulation; stored inventories are not silently relabelled.
- RC 0.7.0 consumes the new roof/domain inputs under its separately declared
  reduction policies. Pitched roofs on touching parts and ambiguous physical
  interfaces retain explicit support limitations. Catalogue defaults are unchanged.

See [supported geometry and migration](docs/roofs-and-basements.md) and the
[public authoring example](examples/roofs_and_basements.ipynb).

# Core 0.6.0 — shared-wall boundaries

- Confirmed geometric contact is an explicit adiabatic modelling assumption,
  independent of the neighbour's heating evidence. Partial horizontal and
  vertical contacts preserve the exposed wall remainder.
- Physical windows and thermal windows use the same outdoor exposure. Physical
  opaque contact area remains installed, including material mass and capacity.
- Flat compact attached conditioned parts retain shared walls once, with internal
  thermal mass and no outdoor conduction or gains on that area.
- `PartyWallNeighbor` and `GeometrySpec.with_party_wall_contacts` detect opposing
  collinear wall edges from supplied metric footprints and heights. Exact contact
  is the default; up to 0.1 m tolerance is an explicit sensitivity assumption.
- Physical snapshot format 7 records each element's boundary. Formats 1–6 remain
  readable without rewriting unchanged snapshots. RC needs 0.6.0 or later to
  consume the boundary-aware physical inventory. Catalogue defaults are unchanged.

See [scope and migration](docs/party-walls.md). Package release checks and tested
revisions are recorded with the coordinated release.

# Release 0.5.0 — 18 October 2026

Physical conversion resolves geometry once and reuses it for surface and internal
mass assignments. Advanced conversion, inspection and compiler calls accept an
explicit bounded `GeometryCache`; every consumer receives detached working
geometry and current material/operation assignments. Cached lookup fingerprints
installed sources and invalidates geometry, window-placement and shading edits.

The numerical and physical input contracts are unchanged. Data 0.6.0 remains the
minimum dependency. See [prepared geometry](docs/geometry-cache.md) for cache
ownership, source-file access, clearing and examples. Core 0.5.0 is the supported
Core version for RC 0.5.0's optional preparation reuse.

# Release 0.4.0 — 15 October 2026

Core consumes shared Data archetypes and operating definitions and assigns validated inputs atomically to physical Buildings. Replace/fill modes retain geometry, material quantities, provenance and renovation lineage; rejected assignments leave the Building unchanged.

This minor release removes migrated redundant profile selectors. Use Data definitions and Core's documented physical converters and calendar builders; see [the profile and assignment guide](docs/archetype-operation.md). Core now requires Data 0.6.0 or later. Physical recipes and scientific algorithms are unchanged by this release preparation.

# Release 0.3.0 — 15 October 2026

Geometry preparation, conversion, compilation, preflight, EnergyPlus execution and result artifacts. Raw engine artifacts keep their existing formats.

Libraries emit through Python's standard logging without configuring output.
Instrumented operations accept optional keyword-only `log_context`; identifiers
stay separate from scientific inputs, saved models and cache keys. INFO shows
major stages; DEBUG adds decisions and timing. Standalone commands support
`--log-level`, including `OFF`, where the package provides a command.

The EPSM application configures the combined stderr and optional DEBUG JSONL
output with `configure_logging`; `enabled=False` disables both destinations.
Existing callers and supported older collaborator signatures remain supported.
No new mandatory dependency is introduced by the logging implementation.

The coordinated release was requested for manual review and local validation
because GitHub refused to start several hosted jobs due to account billing.
Hosted checks that did not run are not counted as passes. See the
[coordinated verification record](https://github.com/SB-Chalmers/epsm_development/blob/main/docs/logging-verification.md)
for exact tested revisions, executed checks and remaining limitations.
