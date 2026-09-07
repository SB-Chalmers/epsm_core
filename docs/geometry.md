# Geometry feature contract

EPSM creates procedural energy-model geometry from metric footprints, known heights and explicit assumptions. It targets national UBEM workflows; it does not reconstruct detailed interior plans.

| Capability | Status and limits |
| --- | --- |
| Footprints | Valid concave polygons, courtyard holes and disconnected components |
| Massing | Nonoverlapping plan-area parts with unequal heights; all parts begin at uniform grade |
| Storeys | Explicit elevations, or a storey count and height; physical intermediate slabs |
| Basement | Full-footprint basement, conditioned or unconditioned; explicit boundary constructions |
| Windows | Scaled openings; repeated openings from WWR or dimensions; facade/storey overrides |
| Attached shading | Reveal fins, window or continuous overhangs, open balconies and screens |
| Roof | Flat, mono-pitch, gable and hip; pitched roofs use cold attics |
| Whole-building zoning | One zone per connected compatible volume |
| Per-storey zoning | Default; separate part/storey zones |
| Perimeter/core zoning | Exposed-facade strips plus remaining cores; explicit configurable depth |
| Apartment zoning | Experimental bounded residential generator; explicit error/fallback policy |
| Custom context | Neighbour footprints, heights and base elevations; shading only |
| Synthetic context | Rural, low-rise dense and high-rise dense illustrative scenarios |
| Inspection | Facade catalog and geometry-only preview, independent of EnergyPlus |

Supplied floorplans, individually positioned windows, BIM import, terrain steps, arbitrary overlapping solids, partial foundations, occupied pitched rooms, intersecting roof unions, dormers, enclosed balconies and vegetation are outside this release. Touching parts with pitched roofs remain unsupported; combine compatible footprints upstream or use separated parts.

## Footprints and facade identity

Input coordinates must already be metric. `source_crs` records their source; it does not reproject them. Preparation is explicit through `prepare_geometry`; construction does not silently repair or replace the outline. Holes and disconnected components are preserved.

`geometry.facades()` returns original facade IDs, endpoints, lengths, outward azimuths and storeys. IDs follow canonical part/ring/edge identities. Use those IDs in `FacadeOverride` and `BalconySpec`; unknown IDs or storeys are rejected. The catalog describes original part boundaries; shared/party surfaces receive no external windows.

`orientation_deg` rotates the complete scene clockwise, including context. Geographic district inputs already carry their orientation and therefore use zero additional rotation.

## Windows and attached shading

`WindowLayoutSpec(mode="scaled")` places one area-scaled opening per contiguous rectangular exposure run. `mode="wwr"` solves repeated openings at the requested WWR. `mode="dimensions"` accepts window width, height and centre spacing; achieved WWR becomes an output. Infeasible requested layouts raise an error.

Facade defaults apply first, then facade-wide overrides, then storey-specific overrides. Overrides support WWR, layout, glazing properties, reveal depth and overhangs. Advanced low/mid/high pattern controls are modelling assumptions, not descriptions inferred from building age or location.

Logical window placement is independent of thermal zoning. A window crossing a thermal boundary is represented by multiple EnergyPlus panes; reports distinguish logical window and pane counts. Reveals and overhangs follow the logical opening, avoiding new shade edges at thermal cuts.

`reveal_depth_m` represents recess shading using outward fins around coplanar glazing. It does not model frame conduction or change the supplied window U-value. Balconies are opaque open shading surfaces; their junction thermal bridges and enclosed volumes are not modelled. Keep `solar_shading_factor=1` unless it represents an additional effect beyond explicit geometry.

![Resolved roof shells and facade details illustrating scaled and repeated openings, reveal fins, overhangs and open balconies.](figures/roof-and-facade.svg)

*Rendered from current resolved geometry. Pitched roof shells sit above horizontal occupied ceilings. The detail views show the actual shading representation, including coplanar glazing and outward reveal fins; they do not imply recessed thermal window planes.*

## Roofs and thermal zoning

`RoofSpec` owns shape, pitch, direction, topology and flat-attic height. Flat roofs default to `topology="compact"`; use `topology="cold_attic"` for an unconditioned buffer. Pitched shapes resolve to cold-attic topology. Default pitches are 10° mono-pitch and 30° gable/hip. `attic_height_m` controls flat attics; pitched heights follow the footprint and slope. The occupied ceiling remains horizontal. Envelope constructions separately describe the top-floor boundary and exterior weather shell. Attics have no inferred ventilation.

Perimeter/core zoning defaults to a **4.5 m depth**. This is an illustrative choice, not a calibrated universal value. Perimeter strips follow exposed outer and courtyard facades. Shared ownership seams and reviewed party walls do not seed strips. Overlaps are allocated by inward perpendicular facade distance; remaining connected regions form cores. Narrow floorplates can have no core.

Height bands establish exposure; zones remain aligned to actual storeys. A facade exposed for part of a storey creates a full-storey perimeter region, while thermal surfaces preserve the actual neighbour height. Virtual zoning boundaries add no material mass. Area, volume, slabs and total prescribed loads are preserved. Unconditioned attics and basements retain their own zoning.

![Actual floor partitions for rectangles, courtyards and touching unequal-height wings, comparing per-storey with perimeter/core zoning.](figures/geometry-zoning.svg)

*Plans use the actual emitted floor surfaces at grade, with 4.5 m perimeter depth. Courtyard walls seed perimeter strips; the shared wing seam does not. Colours distinguish thermal regions, not different constructions.*

![Unequal-height wing geometry with different lower and upper-storey perimeter regions as the shared wall becomes exposed above the lower roof.](figures/geometry-height-exposure.svg)

*The lower wing ends at 6 m. Above its roof, the taller part's newly exposed facade participates in perimeter zoning. Storey elevations and physical slabs stay unchanged.*

Workload guards allow up to 512 exposed facade segments, 20,000 overlapping strip pairs and 4,096 thermal cells. Reflex mitres longer than five times the requested depth fail explicitly.

Procedural zoning fails explicitly by default. `ZoningSpec(mode="perimeter_core", on_failure="per_storey")` permits substitution for a whole building. Compilation and result diagnostics record requested/effective modes and the reason. Exclude substituted results when comparing the requested detail. The same policy applies to experimental apartment generation.

Apartment generation requires explicit residential use and dwelling/common partition constructions. It can add circulation, stair voids and common-space operations; it is a different modelling package from virtual perimeter subdivision. Type mix targets are soft, while footprint coverage and valid physical boundaries remain mandatory.

## Surrounding buildings

`ContextSpec` stores resolved neighbours; procedural helpers generate those objects before compilation. Custom neighbours can occupy courtyard holes, but positive-area overlapping footprints are rejected. Boundary contact is allowed and does not itself establish a thermal party wall.

| Synthetic preset | Grid spacing | Footprint dimensions | Height range | Target clearance |
| --- | ---: | ---: | ---: | ---: |
| `rural` | 64 m | 10–18 m | 3–9 m | 20 m |
| `urban_lowrise_dense` | 32 m | 20–26 m | 6–15 m | 10 m |
| `urban_highrise_dense` | 32 m | 20–26 m | 24–60 m | 10 m |

The default radius is 100 m, seed is zero and generated-building cap is 128. Parameters are configurable. The two urban presets have identical horizontal geometry for the same seed/settings. Generated contexts avoid target courtyards and existing neighbours. Reports include actual counts and assumptions. Workload-limit violations raise errors instead of silently truncating the scene.

| Custom neighbour | Rural |
| --- | --- |
| ![One supplied 18 m neighbour beside the 9 m target.](figures/viewer-custom.png) | ![Eight rural neighbours between 3 and 9 m high.](figures/viewer-rural.png) |
| Explicit footprint and 18 m height | Seed 0: 8 neighbours, 3–9 m |

| Urban low-rise dense | Urban high-rise dense |
| --- | --- |
| ![Twenty-five low-rise urban neighbours surrounding the target.](figures/viewer-urban_lowrise_dense.png) | ![The same twenty-five footprints extruded to high-rise heights, all with complete roof caps.](figures/viewer-urban_highrise_dense.png) |
| Seed 0: 25 neighbours, 6–15 m | Same footprints; heights 24–60 m |

*Screenshots from the current context example, with a 30 × 20 m target and three 3 m storeys. Each view fits its own scene, so image scale varies. The urban presets share footprints, ordering and orientation. Context roof caps remain at their actual elevations, including when target cutaway is enabled.*

These presets are controlled geometric scenarios. They do not change weather, wind exposure or EnergyPlus terrain settings. `DistrictPlan` uses actual neighbour roof maxima for conservative flat extrusions and discloses that approximation.

## What changed the results in the comparison cases?

The following plots summarize 27 accepted annual EnergyPlus cases across Gothenburg–Landvetter, Malmö–Sturup and Kiruna. These are controlled sensitivity examples, not evidence of accuracy for an individual building or a national stock. They use demonstration constructions, 30% scaled WWR, compact flat roofs, 21°C heating and 26°C cooling setpoints. The [retained plot data](figures/geometry-sensitivity-data.json) records the exact run IDs, source revision and weather identifiers.

![Changes in annual heating, cooling, transmitted solar and hourly heating and cooling peaks for three synthetic context choices in three climates.](figures/context-sensitivity.svg)

*Relative to the same rectangle with no neighbours, high-rise context increased annual heating by 7.6–13.2% and reduced transmitted solar by 28.8–34.2%. Cooling fell by 70.3–85.0% in Gothenburg and Malmö–Sturup; the Kiruna rectangle had zero baseline cooling. Context therefore mattered for solar access and cooling as well as heating in these cases.*

![Differences between perimeter/core and per-storey zoning for rectangle, courtyard and unequal-wing cases in three climates.](figures/zoning-sensitivity.svg)

*Across nine matched zoning comparisons, annual heating changed by less than 0.1%; hourly heating peaks changed by less than 0.07 kW. Cooling differences are plotted in kWh to keep near-zero Kiruna baselines interpretable. Peaks are hourly averages, not subhourly design loads. These results support per-storey zoning as an economical baseline for these cases; they do not establish that finer zoning is unnecessary for other envelopes, schedules or local comfort questions.*

Roof shape, recess depth, repeated windows and balcony detail were not varied in this 27-case comparison. The geometry illustrations above describe their implementation; they do not assign an energy benefit to each feature. Compare those features with matched physical inputs before choosing their level of detail for a workflow.
