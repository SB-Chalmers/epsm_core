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
