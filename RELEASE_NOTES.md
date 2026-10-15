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
