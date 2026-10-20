"""Add reviewed teaching text and existing documentation figures without replacing code.

Notebooks are the editable source of truth. Only cells tagged epsm_teaching are
managed by this script; user code, comments, outputs and other Markdown survive.
Run again after changing NOTES to update these explanation cells in place.
"""
from pathlib import Path
import hashlib
import nbformat

ROOT = Path(__file__).resolve().parents[1]
# stem: (API guide, per-section reading notes, figure names)
NOTES = {}

def note(stem, guide, sections, figures):
    NOTES[stem] = (guide, sections, figures)

note('01_environment_and_learning_map',
'''A notebook runs in a **kernel**, which is a Python process with its own installed packages. Selecting a terminal environment does not necessarily select the same notebook kernel. Start by checking `sys.executable`, then the installed versions and `pip check`; together these establish what is available to this particular notebook.

EPSM has two useful starting points. `Footprint` and `GeometrySpec` describe shapes and can be inspected without an energy engine. A complete `BuildingSpec` adds climate, envelope and operations before `EnergyPlusCompiler` and `EnergyPlusRunner` can produce thermal results. The workflow figure shows this progression. The teaching helpers imported from `demo.support.common` belong to this repository, not the installed public API.''', [
'''The version table should point to the environment you selected as **EPSM Core Demo**. `backend_versions()` checks the optional skeleton distribution; a successful import alone would not demonstrate that a particular roof can be generated. The dedicated roof notebook supplies that geometric check. A clean `pip check` verifies dependency consistency, not physics or weather compatibility.''',
'''`engine()` and `epw()` are demo helpers that locate explicitly configured local inputs. An “available” path means a file was found; the engine version and EPW calendar are validated later. Configure `ENERGYPLUS_EXE` and `EPSM_WEATHER_DIR` when your files are elsewhere. There is no automatic weather download in these cells.''',
'''Read the catalogue as a set of modelling questions rather than a required sequence of 38 executions. Begin with geometry if you only have footprints and heights; use the quickstart simulation when you also have materials, use and weather. The embedded scene confirms rendering, while the static image makes the notebook understandable without a live kernel.'''], ['workflow.svg'])
note('02_first_building_to_results',
'''The central object is an immutable `BuildingSpec`: a validated description of **what building to model**, not a running simulation. The repository's `building()` helper constructs one using the assumptions in `examples/building.py`. Those demonstration values are not universal EPSM defaults.

The three stages return different evidence: `compile(b)` returns an epJSON dictionary and `CompilationReport`; `run(b, directory)` returns a `SimulationResult` after engine and output checks. `preview(b)` is a teaching helper that displays a static rendering and, by default, an embedded widget. Follow the workflow figure from geometry inspection to the full building before treating a displayed shape as an energy result.''', [
'''Read the input table before the plot: conditioned floor area is the denominator for EUI, wall U-value describes a nominal assembly, and the weather hash identifies the actual file contents. To change one input, use a validated replacement such as `b.updated(use=b.use.updated(heating_setpoint=ScheduleSpec.constant(20)))`; the original `b` remains unchanged. `preview(b)` displays its widget once; use `scene_widget(b.scene())` directly to retain a handle.''',
'''The number of entries in `model` counts EnergyPlus object **types**, while `len(model["Zone"])` counts zones. Neither is a measure of simulation accuracy. The report connects emitted geometry to its input ownership and records acceptance checks. Inspect it when a shape looks plausible but compilation rejects an opening or boundary.''',
'''The annual bars answer “how much thermal energy?”, the monthly bars show seasonality, and the first-week curves show timing. The equality assertion reconciles heating kWh across those time scales. It does not compare against metered energy. Keep the run ID and diagnostics alongside the plots when sharing a result.'''], ['workflow.svg','geometry-pipeline.svg'])
note('01_footprint_diversity_and_preparation',
'''`Footprint` represents one polygon with its holes. `GeometrySpec.from_footprint(...)` also accepts a Shapely `Polygon` or `MultiPolygon`, allowing disconnected components to become building parts without discarding them. Storeys then turn a planar outline into occupied volume.

`prepare_geometry` is exported from `epsm_core` and implemented in `epsm_core.preparation`. It returns a `GeometryPreparationResult` containing source and cleaned geometry, policy, metrics and a decision. A `GeometryPolicy` specifies tolerances in metres and fractional changes: `precision_m=0.001` is a **1 mm grid**, not a decimal-place count. `simplification_m` is a distance tolerance, not a Boolean switch.''', [
'''The equal-area assertion multiplies footprint area by two storeys. Holes remove floor area; disconnected pieces contribute their own areas. Compare the gallery's exposed perimeter as well as area: two equal-area footprints can have very different wall exposure. `plans()` only plots these shapes and performs no geometry preparation itself.''',
'''The fixtures live in this repository under `tests/fixtures`, not in a national database shipped with the wheel. `shape(...)` decodes their GeoJSON-like geometry. Inspect `prepared.status` and `reasons` before using `cleaned_geometry`; saving an artifact records the decision but does not approve it. The source CRS label records a metric coordinate system already supplied by the caller.''',
'''The bowtie crosses itself, making it a useful deliberately invalid source example. A repaired polygon can be mathematically valid while its intended physical outline is ambiguous. That is why the assertion expects a review or rejection decision. In a stock pipeline, count these records separately instead of quietly excluding them from the denominator.'''], ['geometry-pipeline.svg'])
note('02_massing_storeys_basements_and_party_walls',
'''A `BuildingPart` combines a footprint with elevation **boundaries**, including the roofline. `(0, 3, 6)` therefore describes two storeys, not three. `GeometrySpec(parts=...)` collects compatible parts and exposes conditioned area and volume properties.

`basement_depth_m` adds a full-footprint basement; `basement_conditioned` determines whether it belongs to the conditioned-area denominator. `PartyWall` declares reviewed contact on an existing facade ID. The height-exposure figure is especially useful here: an upper facade can be exposed even when a lower wing touches the same plan edge.''', [
'''Each wing occupies 300 m² in plan. Two storeys in the low wing and four in the high wing give `300 × 2 + 300 × 4 = 1800 m²`. Adjacent parts do not overlap in positive plan area. The visual seam is not an instruction to add another physical exterior wall between the two parts.''',
'''An unconditioned basement changes the thermal path between occupied rooms and ground without increasing conditioned floor area. Conditioning it adds 600 m² in this example. Compare total energy and area-normalized energy separately whenever you change this flag, because both numerator and denominator may change.''',
'''The helper `geometry()` creates a rectangular building with several facades. This cell selects just the first facade and assigns reviewed party-wall evidence to it. `contact_confirmed` and `neighbor_conditioning` express assumptions about physical contact; displaying a nearby `ContextBuilding` alone would only create shading.'''], ['geometry-height-exposure.svg','geometry-zoning.svg'])
note('03_thermal_zoning',
'''Thermal zones subdivide the calculation, while building parts describe physical form. `ZoningSpec(mode=...)` selects whole-building, per-storey or perimeter/core partitioning. The first two are not changes to the measured footprint or floor area. `depth_m` controls perimeter strips in metres.

Use the floor-partition figure to follow one footprint across zoning choices. Then inspect the dependency diagram: logical windows are resolved on physical facade runs and assigned to thermal parents, so more thermal panes do not necessarily mean more physical windows. Apartment zoning is a separate physical-layout model and is covered in its own lesson.''', [
'''Compare the zone counts only after checking the common area and volume columns. More zones create additional state variables and surface relationships. They can support different questions, but a higher count alone provides no evidence of improved national energy estimates. Retain the chosen depth with each perimeter/core case.''',
'''These plots use the generated ground-level floor faces, so their boundaries expose the actual partitioning. Internal lines are not necessarily material walls. The geometry figure includes courtyard and unequal-wing examples beyond this notebook's rectangle; use them to anticipate where exposure-based strips will differ across a diverse stock.''',
'''`on_failure="per_storey"` permits substitution; it does not force it. This simple example succeeds in the requested mode, as its assertion shows. Always read `effective_mode` and the substitution flag in a real batch. Exclude substituted cases from a comparison that claims to measure the failed zoning method.'''], ['geometry-zoning.svg','geometry-pipeline.svg'])
note('04_roofs_and_straight_skeleton',
'''`RoofSpec` separates roof **shape** from thermal **topology**. A compact flat roof is the occupied top boundary; a cold attic places an unconditioned buffer above a horizontal occupied ceiling. Pitched roofs use the latter representation. Pitch controls slope, while the footprint controls where ridges and facets can meet.

The hip-roof backend computes a straight skeleton from the polygon boundary. `roof_faces` uses that result to produce three-dimensional facets; it is a geometry helper, not an energy calculation. The existing roof-and-facade figure shows the horizontal ceiling beneath the roof so that ridge height is not mistaken for extra conditioned storey height.''', [
'''Read the resolved pitch and topology beside each rendering. Default slopes differ between mono-pitch and gable/hip examples. Maximum roof elevation is a geometric quantity; it is also useful when representing this building as conservative shading context for a neighbour. An identical storey count does not imply an identical roof maximum.''',
'''The skeleton lines show how the concave U-shaped boundary partitions roof facets. The assertion sums their horizontal projections and compares with the footprint area. It is one useful coverage check, not a proof that every possible input has a valid shell; the package's other geometry checks and regression tests address additional conditions.''',
'''The temporary patched import deliberately makes only this call behave as though the backend were absent. It leaves the installation intact. The expected error gives the optional-extra installation instruction rather than silently replacing the requested hip roof with a flat roof. Record true backend failures separately in a diversity study.'''], ['roof-and-facade.svg'])
note('05_facades_windows_and_shading',
'''A facade ID identifies an original part/ring/edge. Start with `g.facades()` and select IDs from that catalogue instead of guessing their names. `FacadeSpec` supplies defaults; `FacadeOverride` changes a selected facade or storey. `GlazingSpec` describes thermal and optical performance independently from opening shape.

`WindowLayoutSpec` chooses scaled, WWR-driven repeated, or dimension-driven openings. In dimension mode you must supply width, height and centre spacing. `OverhangSpec` and `BalconySpec` add attached shading. Follow the figure from opening geometry to shading detail, then use the pipeline diagram to distinguish a physical window from the panes assigned to separate thermal zones.''', [
'''Azimuth is already expressed in the rotated scene, so applying the orientation again would select the wrong direction. The override uses zero-based storey 0 and leaves other storeys at the default WWR. Inspect a specific facade's `wwr_for(...)` result when you need to confirm which input applies.''',
'''WWR is an area fraction, not a window count. Scaled and repeated layouts can therefore request the same ratio and yield different counts. Dimension mode defines openings by size and spacing rather than promising an exact WWR. The logical-window and thermal-pane counts report different objects; do not use pane counts as an inventory of installed windows.''',
'''Reveal depth describes recess shading through the package's geometric representation; it does not change the glazing U-value. Balcony screens and overhangs are opaque shade surfaces, not occupied volume. Keep any additional aggregate solar shading factor distinct from explicit geometry to avoid counting the same effect twice.'''], ['roof-and-facade.svg','geometry-pipeline.svg'])
note('06_experimental_apartment_layouts',
'''`ZoningSpec(mode="apartments")` requests a bounded procedural residential layout. `ApartmentLayoutSpec` defines circulation and access constraints; its `ApartmentType` entries supply acceptable area ranges and soft target shares. These targets do not reconstruct measured apartment plans.

A full building also needs residential occupancy and dwelling/common partition constructions. Repeated facade openings affect where window-clear cuts are possible. The shared geometry-pipeline figure explains why the layout, openings and thermal parents must remain compatible. Review the achieved plan before using a residential type mix as a stock assumption.''', [
'''The type table expresses desired ranges, not a guarantee of exact achieved shares. A valid specification can still fail during geometric generation when no complete layout satisfies the bounded search. Inspect the report and the actual floorplate rather than treating input validation as proof that the requested plan exists.''',
'''`infer_floorplate(...)` is a lower-level inspection helper. Its returned parts carry a polygon, role and type. The union assertion checks full coverage of this outline; the individual-area bars expose circulation and dwelling sizes. This isolated helper call is simpler than the complete opening-constrained building resolution used for the preview.''',
'''The effective-mode assertion confirms this example actually generated apartments. Merely constructing `fallback_policy` at the end does not demonstrate a fallback event; it shows how permission for whole-building substitution is represented. For a real failed case, retain the reason and achieved effective mode before deciding whether to include it.'''], ['geometry-pipeline.svg'])
note('07_neighbourhood_context',
'''`ContextBuilding` describes a neighbour's footprint and height. `ContextSpec` groups resolved neighbours, and `synthetic_context(...)` produces such an explicit group from a preset and seed. None of these objects create indoor thermal zones for the neighbours.

Use the documentation gallery to distinguish custom context from generated scenarios. The paired urban images use the same horizontal arrangement with different heights; their apparent screen scale can differ because each view fits its own extent. A neighbour can reduce direct solar access without changing the target's prescribed weather or ventilation.''', [
'''The custom rectangle is placed north of the target in their shared metric frame. Its identifier is retained on its shading surfaces for selection in the viewer. Boundary contact can be allowed geometrically, but a heated party-wall boundary requires a separate reviewed declaration.''',
'''The generation metadata reports what was actually achieved after clearance and overlap checks. Compare that count with your intended neighbourhood assumptions. Fixing the seed makes reruns reproducible; it does not turn the generated arrangement into a measured neighbourhood or guarantee a representative density.''',
'''Use cutaway to see the target's internals while keeping neighbour silhouettes complete. The final assertion isolates the intended high-rise/low-rise height comparison by confirming their footprints agree. The context sensitivity chart in the documentation reports separate retained runs, not the energy outcome of this geometry-only notebook.'''], ['viewer-custom.png','viewer-rural.png','viewer-urban_lowrise_dense.png','viewer-urban_highrise_dense.png'])
note('08_real_footprint_corpus_review',
'''This notebook is a review of **source diversity and preparation decisions**, not a miniature national dataset. Sorted fixture selection gives a repeatable six-record sample across three municipality codes. The polygons can be complex even when their number is small.

The acceptance table is as important as the gallery. `GeometrySpec.from_footprint(...)` receives only accepted cleaned outlines and explicitly assumed heights. In the workflow diagram, this stays in the describe-and-inspect stage: no weather, assembly or operational evidence has been attached yet.''', [
'''The municipality prefix and source stratum describe where each fixture came from and how it was selected for testing. They do not provide population weights. A roof-edge proxy may differ from the facade outline used in an energy model; record that interpretation instead of silently treating both as identical observations.''',
'''Translation is used only for the gallery, bringing each outline near its own plotting origin while preserving its dimensions. The geometries passed to EPSM retain their supplied coordinates and CRS metadata. Count accepted, review and rejected cases over all six source records before focusing on a successful preview.''',
'''The synthetic L-shape at the end is a **separate controlled-reference example** for `scaled_to_area(600)`. It answers how to compare forms at equal area; it neither repairs nor approximates the real outline shown above. The table juxtaposes a synthetic reference's area/perimeter with real-shape volume, so these values are not a before/after pair or a fidelity score.'''], ['workflow.svg','geometry-height-exposure.svg'])
note('01_epw_metadata_and_calendar',
'''`climate_from_epw(path, calendar_year=...)` reads local weather metadata and hashes the file into a `ClimateSpec`. The file path tells the runner where to read; the hash lets it detect changed contents. `hourly_axis` and `validate_epw_calendar` establish which hourly intervals a simulation may use.

An EPW TMY filename describes the period used to assemble typical weather. It is not the same thing as the simulation calendar year. The workflow figure places climate at the full-building stage, after geometry can already be inspected. Keep the distinction clear when reusing one shape under several climate inputs.''', [
'''The equality between the file hash and `ClimateSpec.weather_sha256` checks identity. The 8760-hour assertion checks the selected non-leap calendar. These are complementary: two weather files can have the same number of records and very different temperatures, while the correct file can still be paired with an incompatible calendar.''',
'''`weather_frame` is a plotting helper that reads a few EPW columns, not a replacement for package calendar validation. Temperature is in °C; horizontal solar data is reported as interval irradiation. In the heatmap, columns are weather days and rows are hour indices, which reveals diurnal and seasonal patterns that monthly averages conceal.''',
'''The 8784-hour leap-year axis contains an additional day. The failure example asks whether this particular non-leap weather file can supply it. Read the validation message instead of automatically duplicating a day: doing so would change the forcing and needs a separately documented weather-preparation decision.'''], ['workflow.svg'])
note('02_swedish_climate_diversity',
'''The three `ClimateSpec` objects isolate climate variation through explicit EPW identities. Gothenburg, Malmö and Kiruna illustrate a geographic span, but three stations do not establish national spatial coverage or a station-selection rule.

The coordinate scatter shows station locations, the distributions show hourly variability and the monthly curves show seasonality. The existing context-sensitivity figure extends this idea with a separate retained experiment: the same shading question can have different heating and cooling consequences under different climates. Its numerical results are reference evidence, not values computed by the cells below.''', [
'''Longitude and latitude are station metadata in degrees, unlike the metre coordinates required for building footprints. Do not pass this scatter's coordinates into `Footprint` without a caller-owned coordinate transformation. The filename and hash are the evidence needed to identify each forcing file again.''',
'''A broad temperature distribution tells you more about seasonal and diurnal variation than a single annual mean. Compare the monthly curves to locate the period of largest separation between climates. The same operational schedule can produce a different heating season even when the physical building is unchanged.''',
'''Annual global horizontal irradiation is a useful forcing summary, but it is not energy received by every facade. Orientation, tilt and shading affect surface exposure. Use the PV notebook or an actual building simulation for the corresponding modelled response rather than multiplying this total by arbitrary facade area.'''], ['context-sensitivity.svg'])
note('03_climate_and_ground_sensitivity',
'''This is a matched sensitivity experiment. A `BuildingSpec.updated(climate=...)` replacement changes weather while keeping the other inputs fixed. A separate `EnvelopeSpec` replacement changes the monthly ground-boundary temperatures, so the two effects can be interpreted separately.

Ground temperatures are explicit prescribed boundary conditions, not values inferred from the EPW and not a soil solver. The documentation's climate/context figure is a useful reading example: compare matched baselines within a climate and report absolute energy as well as relative change. The figure's experiment differs from this notebook's ground-temperature cases.''', [
'''Each call to `runner.run` receives the same geometry, envelope and operations with a new climate. The resulting heating EUI removes floor-area scale, which is already fixed here. It does not remove climate effects or make the values weather-normalized measured performance.''',
'''Read the actual twelve supplied temperatures and their source label before interpreting the result. A constant alternative tests sensitivity to a boundary assumption; it does not claim a calibrated ground temperature. The plotted lines make this input difference inspectable independently of the energy output.''',
'''Compare only the Gothenburg baseline with the changed-ground Gothenburg run to isolate the ground effect. `annual_absolute_ground_transfer_kwh` sums magnitudes over time; alternating gains and losses do not cancel in that metric. It therefore cannot be labelled net ground heat loss.'''], ['context-sensitivity.svg','workflow.svg'])
note('01_materials_layers_and_envelopes',
'''`MaterialSpec` stores physical properties, `LayerSpec` gives a material a thickness, and `ConstructionSpec` orders layers **outside to inside**. `EnvelopeSpec` assigns those constructions to wall, occupied top, ground, intermediate slab and other physical boundary roles.

For nominal U-value reporting, layer resistance is thickness divided by conductivity, and `U = 1 / (R_surface + Σ thickness/conductivity)`. EnergyPlus calculates convection dynamically; the nominal surface resistance is not a second material layer. The roof figure helps distinguish the occupied ceiling's `top` role from the attic's external `weather_shell`.''', [
'''Read conductivity in W/(m·K), density in kg/m³, specific heat in J/(kg·K) and thickness in metres. A material's conductivity does not tell you its assembly U-value until thickness and other layers are specified. The horizontal section shows order and depth; it is not a geometric wall extrusion in the energy model.''',
'''Increasing only the insulation layer changes nominal conductance while preserving the concrete layer. The assertion independently checks the series-resistance calculation. Thermal bridge uplift is a separate envelope assumption and is not automatically derived from the junctions in the rendered building.''',
'''The same construction can serve several roles in a teaching example, but each role remains explicit so observed buildings can differ. A cold attic's exterior roof shell and occupied ceiling need not have the same insulation. Use the pipeline figure to see how these physical roles feed both compilation and quantity reporting.'''], ['roof-and-facade.svg','geometry-pipeline.svg'])
note('02_glazing_and_thermal_mass',
'''`GlazingSpec` separates U-value, solar heat gain coefficient and visible transmittance. The first describes thermal transmission, the second solar heat gain and the third optical transmission. Changing all of them is a glazing package, not a pure U-value sensitivity.

A construction's nominal areal heat capacity is `Σ density × specific_heat × thickness`, in J/(m²·K). It describes stored heat per degree per square metre, unlike U-value, which describes a transfer rate. The geometry-pipeline figure shows where physical slabs and constructions remain present even when thermal zone boundaries change.''', [
'''Compare both U-value and solar heat gain coefficient in the table. Lower solar gain can reduce cooling but also reduce useful winter gains. The geometry of the opening is unchanged by these properties; opening size and WWR belong to `FacadeSpec` and its layout controls.''',
'''The heavy/light calculation compares nominal material capacity only. This notebook does not run a dynamic heavy-versus-light building experiment, so the bar chart should not be interpreted as measured time lag or cooling savings. Those effects also depend on exposure, controls and the rest of the building.''',
'''The real simulation compares the two glazing specifications with the same weather and area. Because both U-value and solar gain change, explain any heating difference as the combined glazing response. Do not infer a universal ranking for cooling-disabled or differently shaded buildings from this pair.'''], ['geometry-pipeline.svg','roof-and-facade.svg'])
note('03_physical_quantity_takeoff',
'''`quantity_takeoff(building)` returns typed `PhysicalQuantity` records for physical layers, glazing and equipment. These records distinguish area, volume, mass and count so that downstream assessment does not have to reconstruct them from a screenshot.

Trace the quantity branch in the geometry-pipeline figure. Virtual thermal partitions have no material inventory, whereas physical slabs remain counted. Neighbouring context has a shading path into compilation and preview but no path into the target's material quantities. This is why the two invariance assertions below are meaningful.''', [
'''A null quantity is “not supplied by this representation”, not a measured zero. Glazing may have area without an invented mass; equipment can have count without material volume. The role grouping is a useful summary, but keep item IDs and hashes for any downstream replacement or audit comparison.''',
'''Switching to perimeter/core adds calculation boundaries rather than new material walls. The mass equality tests that distinction. It does not imply apartment zoning has the same material inventory: physical dwelling partitions and circulation are a different modelling choice.''',
'''Adding shading neighbours changes a simulation input while keeping target quantities unchanged. The equality assertion verifies the inventory exclusion, not an absence of shading effects on energy. For a district inventory, sum each building's own takeoff once rather than counting its context again.'''], ['geometry-pipeline.svg','geometry-zoning.svg'])
note('01_schedules_and_calendars',
'''A `ScheduleSpec` is a 24-value daily profile. `ScheduleSpec.constant(value)` is shorthand for repeating one value across those hours. The same type can hold temperatures or dimensionless fractions; the owning field determines the physical meaning and additional validation.

In the workflow diagram, schedules enter through building operations, after a shape is already inspectable. The current API repeats the same daily pattern on the validated annual calendar. Week and year plots below expand it for explanation; they do not create weekday, weekend, holiday or stochastic occupancy support.''', [
'''The setback profile lowers heating control to 18°C overnight and keeps 21°C during the selected daytime hours. This is a control input, not a prediction of indoor temperature. `len(values) == 24` checks the shape of the schedule rather than proving the setpoints are suitable for a particular use.''',
'''`np.tile` repeats a profile for plotting. Identical columns in the annual heatmap are expected because this example has no seasonal schedule change. A school with holiday shutdowns cannot be represented faithfully by these repeated-day plots alone; that is a limit to disclose in a diversity study.''',
'''The deliberately short input tests early rejection of a malformed schedule. Valid fraction ranges and setpoint relationships are checked through their owning specifications as well. Keep units visible in plots so that a schedule of 0–1 fractions is not confused with a temperature curve.'''], ['workflow.svg'])
note('02_occupancy_gains_setpoints_and_dhw',
'''`UseSpec` supplies prescribed people, equipment, lighting, setpoints and DHW. Density is people per conditioned m²; activity is W/person; equipment and lighting intensities are W/m². Fraction schedules multiply their respective intensities over the repeated day.

Prescribed gains per area can be read as `people_density × activity × occupancy_fraction + equipment_intensity × equipment_fraction + lighting_intensity × lighting_fraction`. Annual DHW intensity is in kWh/(m²·year), a different quantity. These inputs occupy the operations stage of the workflow; the simulation determines how the building responds to them.''', [
'''“Residential” and “office-like” are labels for the explicit assumptions shown here, not a lookup into a national use catalogue. The daytime profile repeats every day. Inspect density, gain intensity and DHW separately before reusing this example for an observed building with another operating pattern.''',
'''The gain curve adds people, equipment and lighting powers per area; it does not include heating-system delivery. The prescribed total is not an indoor air-temperature prediction because storage, transmission and ventilation also affect the zone balance. Its purpose is to verify the intended operation before running the engine.''',
'''DHW should reconcile with intensity times conditioned area to within the stated tolerance. Heating also changes as internal gains change, so lower heating alone is not proof of lower total building energy. This comparison deliberately changes a use package, including DHW, and should be labelled that way.'''], ['workflow.svg'])
note('03_dwelling_and_common_space_operations',
'''Apartment zoning distinguishes dwelling and common-space roles. `common_use` and `common_airflow` let the building specify operations for circulation rather than applying every dwelling assumption uniformly. The apartment controls also disclose whether prescribed residential loads are conserved across the generated plan.

This differs from virtual perimeter/core zoning: apartment layouts can introduce physical partitions and separate operations. Follow the thermal-partition branch in the pipeline diagram, then inspect the actual compiled zone roles before interpreting the common-area setpoint or lighting assumptions.''', [
'''The demonstration common space has an 18°C heating setpoint and no prescribed occupants, equipment or DHW. Those zeroes are explicit modelling choices, not proof that real stairs and corridors have no gains. The conserved-load control matters when distributing residential loads over a generated rather than measured layout.''',
'''Both plotted temperatures are setpoints. Whether every zone reaches them is an engine result, not a property of the input curve. The lighting bars have units of W/m² of the relevant role area; compare achieved role areas before translating them into whole-building power.''',
'''The compilation report lists generated zones and the achieved layout. Confirm the effective zoning mode before calling this a dwelling/common-space comparison. A fallback to per-storey would represent a different model and should not be included under the requested apartment label.'''], ['geometry-pipeline.svg'])
note('01_airflow_and_heat_recovery',
'''`AirflowSpec` separates leakage, natural exchange and mechanical ventilation. The topology codes represent natural ventilation (`S`), mechanical exhaust (`F`), supply/exhaust (`FT`) and supply/exhaust with recovery (`FTX`). Infiltration and natural exchange use air changes per hour; the mechanical rate uses L/(s·m²).

To compare the scales, `ACH × volume / 3600` gives m³/s, while `mechanical_rate × floor_area / 1000` gives m³/s. They need not be equivalent. These prescribed flows enter operations in the workflow; EPSM does not infer wind/stack leakage or fan electricity from the geometry.''', [
'''The inputs table makes the unit and topology differences visible before simulation. Recovery effectiveness is a fraction, not a COP. The natural case includes a prescribed ACH, whereas the mechanical cases share an area-based rate; compare them as stated assumption packages rather than identical flows with different names.''',
'''All runs share the building's other inputs. F, FT and FTX therefore isolate compatible mechanical-system assumptions more closely than the natural-versus-mechanical comparison. Inspect accepted diagnostics for each case, and do not infer purchased energy from the heating-demand bars.''',
'''Monthly energy can reveal whether a system difference matters mostly during the heating season. It does not report equipment sizing or fan consumption. The acceptance assertion concerns the engine's numerical and output contract, not empirical evidence that the assumed airflow occurs in real buildings.'''], ['workflow.svg'])
note('02_delivery_and_exhaust_air_heat_pumps',
'''`DeliverySpec(fvp=FVPSpec(...))` adds the package's exhaust-air heat-pump estimate to a compatible building. FVP production is limited by demand, nominal thermal capacity and sensible heat available in the prescribed exhaust flow. The model uses a supplied constant COP rather than solving a refrigerant cycle.

Separate the thermal demands from delivery components: `fvp_heat_kwh` is produced heat, `fvp_electricity_kwh` is its electrical input, and `backup_input_kwh` is residual demand divided by backup efficiency. The workflow figure's result stage therefore contains several related streams, not one interchangeable energy total.''', [
'''The exhaust-only `F` airflow is a compatibility choice for this example. Read thermal capacity in kW and the exhaust threshold in °C. `dhw_priority` decides which thermal load gets available production first; it does not increase available source heat or installed capacity.''',
'''In the hourly plot, generated heat and electricity are related components, so summing every displayed column would double count energy. Backup supplies residual demand with its own input definition. The array units are kWh per one-hour interval; a capacity limit in kW is comparable over that fixed interval.''',
'''The independent balance is `heat = electricity + extracted_exhaust_heat`. It checks the constant-COP accounting for the supplied small arrays. It does not demonstrate seasonal COP calibration, latent heat extraction or a detailed compressor model. Interpret the annual totals within those stated assumptions.'''], ['workflow.svg'])
note('03_photovoltaics',
'''`PVSpec` describes a system's DC capacity, tilt, azimuth, losses and inverter settings. `RenewablesSpec` groups systems; `run_pvwatts(pv, climate)` explicitly invokes the optional PySAM backend and returns generation arrays and summary metrics.

PV generation is an AC output stream, not thermal demand or automatically avoided grid energy. The workflow diagram helps locate this distinction at the output stage. This API does not place panels on the rendered roof, infer usable roof area or translate the geometry viewer's neighbour meshes into detailed PV shading.''', [
'''South-facing azimuth is 180° in this specification. DC capacity is the installed nameplate power, while the inverter and losses shape AC generation. The table is the complete input evidence for the scenario; no measured roof survey is implied by creating a `PVSpec`.''',
'''The heatmap shows daylight and seasonal timing in generated interval energy. Finite and nonnegative values are necessary data-quality checks. PVWatts also validates the annual/hourly energy reconciliation internally. Keep the weather checksum with the system inputs because generation depends on both.''',
'''The azimuth comparison keeps capacity, tilt and weather fixed, which makes orientation the intended sensitivity. Its annual totals do not reveal how much electricity is consumed on site. Self-consumption needs a compatible electrical-demand time series and an explicit matching calculation outside this example.'''], ['workflow.svg'])
note('01_individual_measures',
'''The renovation API separates a **measure description** from applying it. `AddInsulation`, `ReplaceGlazing`, `ChangeAirflow`, `InstallFVP` and `InstallPV` describe the requested operation; `apply_renovation(building, measure, effective_date=...)` returns a new validated `BuildingSpec` with a dated audit record.

The original building is retained for a matched baseline. The physical-quantity branch in the pipeline figure explains why these operations can record material and equipment changes even when the exterior preview looks unchanged. A new physical hash means changed inputs, not demonstrated energy savings.''', [
'''Insulation targets a named envelope element and supplies a layer. Glazing and airflow replacements provide complete new specifications, so check every field you intend to retain. An FVP installation also requires compatible airflow; the example deliberately uses a compatible source for that measure rather than quietly modifying the baseline system.''',
'''Each variant starts from its stated source and receives one new renovation record. The FVP variant has a different compatible source from the other variants, so these objects are not yet a matched energy-savings comparison. The original record count assertion protects the baseline from accidental mutation.''',
'''The quantity-change count is an audit size, not a performance score. Wall U-value can change without a visible change in the resolved shell, and PV is an explicit generation system rather than automatically drawn panels. Run matched simulations before attributing an energy effect to these operations.'''], ['geometry-pipeline.svg','roof-and-facade.svg'])
note('02_packages_and_building_diversity',
'''A renovation package is a sequence of immutable `apply_renovation` calls. Here the insulation operation produces an intermediate building, then glazing replacement produces the final case. Dates and ordering remain visible in its renovation records.

The rectangle and elongated form have equal floor area, but different exposed perimeter. That isolates one important source of stock diversity while using the same measure package. The existing facade/roof figure is a reminder that envelope properties, window geometry and shading are separate inputs; this comparison changes properties while retaining its stated geometry.''', [
'''The two shapes each have 400 m² per storey and two storeys, giving 800 m². Equal area does not imply equal facade area or solar exposure. Keep baseline and package objects together for each form so the subsequent subtraction uses a matched pair.''',
'''Each output row retains form, scenario and run ID. The grouped chart should therefore be read within each form first: baseline versus package. A cross-form difference combines geometry and retrofit response, and should not be labelled a pure measure effect.''',
'''Absolute saving is baseline minus package in kWh/year; relative saving divides that difference by baseline energy. Positive savings indicate a reduction under these assumptions. This notebook does not compute costs, embodied impacts or uptake, all of which would be needed for a national retrofit decision.'''], ['roof-and-facade.svg'])
note('03_provenance_and_quantity_changes',
'''`SourceRecord` documents evidence for an input field and `ProvenanceSpec` collects those records. `DatasetReference` and `AssessmentReference` identify caller-owned sources and assessment context; constructing them does not fetch factors, prices or catalogue entries.

`RenovationRecord` joins a dated measure, before/after hashes and typed `QuantityChange` entries. The pipeline diagram's physical-quantity branch shows where the material evidence comes from. Administrative provenance and physical identity are distinct so a corrected source citation need not masquerade as a new physical building.''', [
'''The confidence value is a caller-supplied statement, not a score calculated by EPSM. The illustrative factor reference has no numerical carbon factor attached. Inspect these fields when reusing the record: a reference name alone does not establish that a lifecycle calculation has been performed.''',
'''The hash assertion changes only provenance and expects physical identity to remain stable. Adding insulation then changes physical inputs and produces before/after quantity evidence. A `QuantityChange` can contain only one side for added or removed items, so interpret null before/after entries according to the action.''',
'''The mass difference is a physical result of the supplied layer, density and affected area. It is not automatically embodied carbon or cost. The JSON roundtrip verifies that the edited input and audit remain serializable for an external assessment workflow.'''], ['geometry-pipeline.svg'])
note('04_measure_interactions',
'''This four-case experiment contains baseline, insulation only, glazing only and their combination. Every case shares the original geometry, weather and use, so the effect of combining measures can be distinguished from accidentally changing other inputs.

Define independent savings as `(baseline − insulation) + (baseline − glazing)` and combined savings as `baseline − combined`. Their difference is the interaction quantity used below. The workflow figure puts simulation between edited inputs and comparison: input changes alone cannot tell you whether savings will add linearly.''', [
'''The two individual variants are each derived from the baseline; the combined case is derived from the insulation variant and then receives glazing replacement. The input table checks that the intended parameters changed. The audit dates express sequence, not staged simulation of building use over several years.''',
'''The four annual outputs use independent directories to prevent accidental reuse of old engine files. Read the baseline beside each single-measure case before interpreting the combined value. A small single-measure saving can still interact with controls or other envelope changes.''',
'''A positive interaction means the combined saving exceeds the sum of individual savings under this definition; a negative interaction means it is smaller. Neither sign by itself establishes good or bad performance. State the definition and baseline whenever presenting the quantity to avoid ambiguous “synergy” claims.'''], ['workflow.svg'])
note('01_specifications_schema_and_roundtrips',
'''`BuildingBuilder` applies caller-supplied assumptions and observed replacements to construct a validated building. `BuildingSpec.model_dump_json()` serializes it; `model_validate_json()` reconstructs and validates it. `model_json_schema()` describes the accepted structure for other software.

The workflow figure identifies the full-building boundary this notebook exercises. Validation checks the input contract. Compilation adds emitted-surface and engine-schema checks, while a run adds engine/output acceptance. These are distinct levels of evidence; a schema-valid JSON document is not automatically a successful energy simulation.''', [
'''The demonstration starts with explicit assumptions from a known example, not an implicit registry. The builder's assumption profile records where defaults came from. Replacing the identifier or provenance can change administrative context without changing physical inputs, which is why the physical hash is a separate field to inspect.''',
'''The roundtrip assertion checks equality of the validated objects and their physical identity. Unknown fields are rejected so misspelled parameters do not silently become unused data. Use `.updated(...)` for a checked replacement; an unvalidated generic model-copy update does not enforce the same guarantees.''',
'''The CLI exposes the same input boundary to non-notebook tooling. `schema` prints the input contract and `validate` checks a saved specification. The artifact table shows their inspectable files, not proof of a national ingestion capability. Preserve the source specification alongside later engine outputs.'''], ['workflow.svg'])
note('02_compilation_and_engine_exports',
'''`EnergyPlusCompiler` resolves an explicit building into engine objects. `compile` returns an in-memory model and report; `write` emits the model, original building and compilation report to a chosen directory. `CompilerSettings` contains engine controls that also participate in simulation identity.

The geometry-pipeline figure maps domain inputs into emitted surfaces and shows why logical openings, thermal parents and physical quantities retain separate meanings. IDF export is another engine interchange form of the compiled input. It does not replace the original `BuildingSpec` or its provenance.''', [
'''The shadow-figure setting controls an engine workload limit, not the radius or number of neighbours. Check `len(model["Zone"])` for zones and object-type inventories for emitted complexity. Increasing a limit should not be interpreted as evidence that arbitrary scene complexity is appropriate for stock modelling.''',
'''Use the adjacent `compilation.json` to interpret a surface selected in the compiled widget. A geometry-only preview cannot provide assigned construction layers that were never attached. Matching report/run identities verifies that the written evidence describes the intended compilation.''',
'''The CLI compile and export commands provide a reproducible boundary for external callers. The resulting IDF is a generated artifact; edits there are not automatically reflected in the immutable Python input. Keep the original input and report as the auditable description of the case.'''], ['geometry-pipeline.svg','viewer-controls.png'])
note('03_execution_artifacts_and_failures',
'''`EnergyPlusRunner.run(spec, directory, timeout_seconds=...)` owns one isolated execution and checks its diagnostics and result arrays. A successful return is a `SimulationResult`; failures preserve evidence in the run directory. The caller chooses what to do next.

The workflow figure's final stage contains both execution and interpretation. It is not enough that the process starts or a results file exists. Keep accepted diagnostics and reconcile hourly/annual values before comparing cases. This notebook deliberately demonstrates an occupied-directory failure separately from an engine physics failure.''', [
'''The run receives an empty destination beneath the notebook's new output root. The returned artifact paths identify the evidence actually produced. The plotted demands are thermal quantities and are only available after the runner's acceptance checks, not merely after the executable exits.''',
'''Rerunning into the same occupied directory is intentionally rejected to prevent stale results from being mistaken for new results. The preserved files still belong to the first accepted run. This failure does not demonstrate an EnergyPlus convergence problem or the package's warning-exception policy.''',
'''The CLI example performs another real annual run in its own destination. It verifies that the serialized input can pass through an external command boundary. Retrying, resuming and distributing thousands of such tasks are orchestration policies owned by the caller, not inferred by core.'''], ['workflow.svg'])
note('01_embedded_geometry_widget',
'''`GeometrySpec.scene()` and `BuildingSpec.scene()` return portable data; pass it to optional `epsm_viewer.scene_widget(scene)` for live display. `display(widget)` creates a notebook view. The scene is based on the same resolved geometry as the standalone viewer, but does not require a browser to contact a loopback server on the kernel machine.

The retained pre-extraction screenshot below is an orientation guide to the controls, not a live instance and not this notebook's U-shaped model. Use the live output to orbit, isolate storeys, inspect surfaces and change cutaway. Use the static image to understand the intended geometry in a non-executing notebook reader.''', [
'''The MIME assertion checks that Python produced a widget view descriptor. It cannot prove that WebGL actually rendered in the notebook frontend. The scene equality check later connects the payload to the shared geometry representation. A static image can remain readable even when no kernel is running.''',
'''Choose a surface in the widget, then rerun the selection-reading cell to inspect `selected_surface` in Python. An empty string before selection is expected. Names and available metadata describe resolved surfaces; geometry-only scenes have no thermal construction assignments to inspect.''',
'''Changing `height` updates the existing widget view. Closing a handle releases its live frontend resources, so do not close the visible example until you finish inspection. Multiple displays of one handle are views of the same widget model; create separate widgets when you want independent selection state.'''], ['viewer-controls.png','geometry-pipeline.svg'])
note('02_compiled_model_inspection',
'''Core's `scene_data(model, report)` converts explicitly loaded World-coordinate model data. Viewer's `scene_widget` displays it inline, `write_scene` writes a standalone bundle, and `view_scene` returns a server handle. These interfaces inspect an existing artifact; they do not run EnergyPlus.

The viewer screenshot identifies the controls shared by both inspection routes. The important extra evidence in a compiled model is the assigned thermal construction and engine object metadata. Select a wall and compare the displayed layers and U-values with the original envelope assumptions rather than judging only the shell's appearance.''', [
'''`compiler.write` prepares the three related artifacts together. The example explicitly reads that model and passes its loaded report to Core before display. A missing acceptance flag is not a successful simulation flag: compilation and geometry inspection can happen before an annual run exists.''',
'''The table groups constructions by their compiled roles. Nominal and applied U-values can differ when a declared conductance adjustment is applied. Layer metadata explains what material model produced the surface; it is not a measured wall survey inferred from the geometry.''',
'''The short context manager checks that a local standalone server responds, then closes it. Its printed success is an HTTP check, not a live-browser rendering check. For prolonged inspection, keep the handle alive. The notebook widget follows a separate lifetime through its own `close()` method.'''], ['viewer-controls.png','geometry-pipeline.svg'])
note('03_comparative_geometry_review',
'''Each call to `epsm_viewer.scene_widget(value.scene())` creates a separate model and view state. Place two handles in an `HBox` to compare cases while keeping the original geometry immutable. The model IDs and selection properties make their independence inspectable from Python.

The partition and viewer figures explain two different comparisons: geometric detail can change the number of resolved surfaces, while a cutaway changes only what is displayed. Neither an opacity change nor camera motion changes energy inputs. This notebook changes roof and zoning together for visual teaching; a causal energy experiment should vary them separately.''', [
'''The left and right widget handles are independent, even though the right geometry was derived from the left through a validated update. You can orbit or select one without using the other as a camera controller. Their static references also preserve the comparison when the notebook is read without active widgets.''',
'''Object count measures scene complexity, not area, mass or accuracy. Read it alongside the roof and zoning choices to understand why it changes. The selection table is a snapshot: rerun it after interacting if you want the current chosen surface names.''',
'''`epsm_viewer.view_scene(value.scene(), directory=...)` provides the standalone browser-server interface. These short checks close their handles promptly. Use the embedded widget for inline interaction and keep the server handle open only when you intentionally need its URL in a standalone workflow.'''], ['geometry-zoning.svg','viewer-controls.png'])
note('01_district_context_and_parallel_runs',
'''`DistrictPlan(buildings=...)` groups explicit target buildings in one metric coordinate frame. `resolved_buildings()` returns each target with the others represented as shading context. `run(..., workers=2)` executes their independent simulations with a bounded number of workers.

The context gallery shows the distinction between a target and its neighbours. District context is not a coupled urban thermal model: neighbours have shading geometry, not exchanged indoor heat or shared HVAC. The helper considers every other target, making it appropriate for a small district demonstration rather than a national all-to-all neighbourhood search.''', [
'''Identifiers must be unique and orientation must already be resolved in the common coordinate frame. The example positions footprints with a 50 m spacing and changes storey count explicitly. Inspect the neighbour count before running to confirm that each target receives the intended context.''',
'''Two workers limit simultaneous tasks rather than changing the simulated physics. A worker failure propagates while completed artifacts remain available. Runtime and failure handling become important as detail grows; scaling this example should not begin by loading an entire national stock as one district.''',
'''Coincident aggregation requires matching calendars and intervals. The peak of the summed profile is less than or equal to the sum of individual peaks; equality occurs only when their maxima coincide. The result is hourly-average power, not a subhourly design load for a real district network.'''], ['viewer-custom.png','geometry-pipeline.svg'])
note('02_building_stock_diversity_matrix',
'''A diversity matrix is a caller-owned list of explicit modelling cases, not a new core API. Each row resolves into a `BuildingSpec` with a footprint, storeys, insulation, use label, climate and ventilation. The examples demonstrate which variations the current package can accept.

Read the one-hot coverage matrix as “which categories appear in these rows?”. It does not show population prevalence or cover every joint combination. The existing geometry figures supply additional examples of form and exposure diversity that a purely rectangular matrix can miss.''', [
'''The row labels are synthetic case IDs. The residential/non-residential field here changes the occupancy category while the shared factory supplies the remaining use values; this is not by itself a calibrated contrast in occupancy schedules. Audit the actual numeric inputs before calling two rows different operational archetypes.''',
'''Immutable nested replacements keep the remaining building inputs explicit. Each physical hash should differ because at least one physical input differs, but a unique hash is not a measure of useful diversity. Check that varied assumptions answer a modelling question instead of merely increasing the number of combinations.''',
'''A coloured cell indicates category presence in a specific case. Empty combinations can still matter even when each individual category appears somewhere. Saved JSON files make those gaps reviewable upstream; core does not attach national sample weights or infer missing records.'''], ['geometry-zoning.svg','geometry-height-exposure.svg'])
note('03_diversity_capstone',
'''The capstone repeats the core unit of work across six explicit buildings and one insulation retrofit per building. Twelve annual cases demonstrate variation in form, height, climate and wall insulation. They are independent examples, not a geographically connected district.

The workflow figure describes the repeated unit: input, inspect, complete, compile/run and compare. The documentation sensitivity chart shows why retained assumptions and matched comparisons matter across climates. Its published example values are a separate reference study, not the expected numerical output of this capstone.''', [
'''Keep each baseline and retrofit paired by building index. Only the added insulation should differ within a pair; the cross-building inputs deliberately vary. The six-case gallery is a diversity check, not proof that the chosen cases reproduce the country's joint distribution of size, age, use and location.''',
'''The exception handler records failed cases rather than inventing successful results. The subsequent assertion stops the comparison if any pair is incomplete. This preserves the original denominator of twelve attempted cases and leaves the run manifest available for review. It is a small experiment loop, not a retry service.''',
'''Read absolute savings within each accepted pair. Comparing across buildings reveals heterogeneous response, but summing the six savings does not create a national estimate. Population weights, observed distributions and sampling uncertainty would need separate evidence before extrapolation.'''], ['workflow.svg','context-sensitivity.svg'])
note('01_scalars_hourly_signals_and_units',
'''`SimulationResult` contains `scalars`, `hourly`, `units`, `time_axis`, `diagnostics` and artifact paths. Scalars summarize a run; hourly arrays preserve timing; units and the validated calendar tell you how those arrays can be interpreted and combined.

The workflow figure ends at comparison because execution alone does not explain an output. Thermal heating, cooling and DHW are distinct from delivery electricity or PV generation. A raw requested engine signal can also use different units from a normalized `_kwh` array, so inspect `result.units` rather than assuming every column is energy.''', [
'''The scalar table includes aggregate demands; the units table previews raw and normalized signals. Some raw names contain an engine variable and a zone key. Avoid adding unrelated signal types just because they have equal array lengths. The quantity definition and unit are both part of the interface.''',
'''Heating EUI is annual heating kWh divided by conditioned floor area in m². The assertions check that hourly, annual and normalized forms agree. Monthly and first-week plots reveal temporal structure that an annual scalar omits; they use the validated result calendar rather than a guessed date index.''',
'''Sorting produces a load-duration curve and discards chronological coincidence. Its maximum is an hourly-average kW because each value covers one hour. Use the original time-indexed series, not the sorted curve, when combining multiple buildings or comparing simultaneous demand and generation.'''], ['workflow.svg'])
note('02_comparisons_and_aggregation',
'''A building EUI and an aggregate stock EUI use different weighting logic. With count weights `wᵢ`, aggregate EUI is `Σ(wᵢ Eᵢ) / Σ(wᵢ Aᵢ)`, where energy is in kWh and conditioned area in m². It is not generally the simple mean of building EUIs.

The example weights are illustrative counts, not Swedish stock data. The workflow figure's compare stage is performed here with pandas using core results. EPSM supplies building-level simulation evidence; the caller remains responsible for the validity of the population weights and aggregation question.''', [
'''The two sizes share other inputs, making floor area and exposure the intended contrast. Read absolute kWh alongside EUI: a larger building can consume more total energy and less per square metre. These are complementary findings rather than a contradiction.''',
'''The alternative weighted-average assertion uses weights proportional to count times area, which reproduces the ratio of totals. Replacing those with counts alone would average building intensities differently. Always state whether a weight represents buildings, floor area, sample expansion or another quantity.''',
'''Matching time axes is necessary before summing weighted hourly profiles. Missing values would indicate an alignment problem rather than zero demand. The coincident-peak inequality is a useful consistency check but does not provide measured simultaneity or a network sizing margin.'''], ['workflow.svg','context-sensitivity.svg'])
note('03_quality_sensitivity_and_interpretation',
'''This notebook compares requested per-storey and perimeter/core zoning under matched physical inputs. Diagnostics identify the effective mode and any substitution; energy arrays then describe the accepted result. “Accepted” means the declared engine/output checks passed, not that the building has been calibrated against observations.

Read the existing zoning-sensitivity figure as an example of reporting matched differences across shapes and climates. Its retained runs have their own assumptions and provenance. The curves and bars below are a separate small experiment, so exact agreement with that documentation figure is not a notebook acceptance criterion.''', [
'''The effective-mode and substitution assertions protect the meaning of the comparison. If a requested perimeter/core case fell back to per-storey, labelling its result perimeter/core would conceal the failure and bias the study. Keep both requested and achieved modelling detail in any exported table.''',
'''Near-zero cooling makes relative percentages unstable or undefined. Absolute kWh differences remain interpretable, provided the baseline and subtraction direction are explicit. A small difference in these cases does not establish that zoning detail is irrelevant for all envelopes, schedules or local comfort questions.''',
'''Run IDs and weather/input hashes let another analyst locate the exact experiment. The interpretation string correctly separates sensitivity from calibration. Add independent measured-energy evidence before making claims about predictive accuracy; the acceptance diagnostics alone cannot supply it.'''], ['zoning-sensitivity.svg','geometry-zoning.svg'])

FIGURES = {
    'workflow.svg': ('From observed geometry to an accepted energy comparison', 'usage.md',
        'Follow the arrows from footprint and storeys to geometry inspection, then to a complete BuildingSpec. Weather, constructions and operations enter before compilation and execution. The diagram explains responsibility boundaries; it is not an automatic one-call workflow.'),
    'geometry-pipeline.svg': ('How geometry feeds compilation, physical quantities and inspection', 'architecture.md',
        'Trace logical openings and thermal partitions into their shared resolved geometry. Window panes acquire thermal parents without changing the original logical opening. Notice that context reaches shading and preview but not physical material quantities. These are conceptual dependencies, not the chronological order of Python calls.'),
    'roof-and-facade.svg': ('Resolved roof shells, openings and attached shading', 'geometry.md',
        'Compare the horizontal occupied ceiling with the pitched shell above it, then identify repeated windows, reveals, overhangs and balconies. These panels show geometric representations; they do not assign an energy saving to any detail or imply occupied pitched rooms.'),
    'geometry-zoning.svg': ('The same forms under different thermal partitions', 'geometry.md',
        'Read each footprint across the zoning alternatives. Internal coloured regions are calculation zones, not automatically new construction walls. Courtyard edges and exposed parts seed perimeter strips. The shown 4.5 m perimeter depth is a declared example assumption, not a universally calibrated value.'),
    'geometry-height-exposure.svg': ('Exposure changes above an adjoining lower wing', 'geometry.md',
        'The lower wing ends at 6 m. Above it, the taller part has a newly exposed facade, so its perimeter subdivision can change by height. Physical slabs remain at actual storeys. This explains why a single plan outline or total height cannot describe all exposure in a multi-part building.'),
    'viewer-controls.png': ('Existing viewer controls and target/context separation', 'usage.md',
        'Use Focus building and Fit context to change framing; use storey isolation and cutaway to inspect the target. Grey neighbours retain their complete silhouettes. This documentation screenshot shows a 30 × 20 m, three-storey target with 25 synthetic high-rise neighbours; it is not a live widget or a simulation result from this notebook.'),
    'viewer-custom.png': ('An explicitly supplied shading neighbour', 'geometry.md',
        'The documentation example supplies one 18 m neighbour beside a 9 m target. Its position and dimensions are inputs, rather than a generated density label. The picture shows shading geometry only, not a thermally coupled adjacent building.'),
    'viewer-rural.png': ('A seeded illustrative rural context', 'geometry.md',
        'This documentation screenshot has eight generated neighbours for its stated seed and settings. The actual count in the cells below can differ when their seed or target changes. Read the generation report instead of treating the picture as a required output.'),
    'viewer-urban_lowrise_dense.png': ('Illustrative dense low-rise surroundings', 'geometry.md',
        'This reference scene contains 25 neighbours. Compare their footprints with the high-rise counterpart: the horizontal pattern is shared for matched generation settings, making height the intended difference. Each image fits its own scene, so apparent pixel scale is not a metric comparison.'),
    'viewer-urban_highrise_dense.png': ('Illustrative dense high-rise surroundings', 'geometry.md',
        'The high-rise counterpart raises neighbours while retaining the matched horizontal pattern. Complete roof caps help assess their shading silhouette. The preset does not also change EPW weather, wind exposure or EnergyPlus terrain.'),
    'context-sensitivity.svg': ('Retained example: context sensitivity across three climates', 'geometry.md',
        'Read each response against its matched no-neighbour baseline within the stated climate. Heating, cooling, solar transmission and hourly peaks are different metrics. This figure comes from a separate 27-case documentation experiment with its own inputs; it is not newly calculated by this notebook and is not evidence of national representativeness.'),
    'zoning-sensitivity.svg': ('Retained example: zoning differences across shapes and climates', 'geometry.md',
        'Compare per-storey with perimeter/core while holding each case’s other inputs fixed. Read the actual units: absolute differences remain useful when baseline cooling is near zero. This separate documentation experiment cannot establish that finer zoning is unnecessary for every building or use.'),
}


def managed(text, key):
    cell = nbformat.v4.new_markdown_cell(text)
    cell.id = hashlib.sha256(('teaching:' + key).encode()).hexdigest()[:12]
    cell.metadata['epsm_teaching'] = key
    return cell


def figure_cell(filename, stem):
    title, document, reading = FIGURES[filename]
    owners = {
        'workflow.svg': '01_environment_and_learning_map',
        'geometry-pipeline.svg': '01_footprint_diversity_and_preparation',
        'geometry-zoning.svg': '03_thermal_zoning',
        'geometry-height-exposure.svg': '02_massing_storeys_basements_and_party_walls',
        'roof-and-facade.svg': '04_roofs_and_straight_skeleton',
        'viewer-controls.png': '01_embedded_geometry_widget',
        'viewer-custom.png': '07_neighbourhood_context',
        'viewer-rural.png': '07_neighbourhood_context',
        'viewer-urban_lowrise_dense.png': '07_neighbourhood_context',
        'viewer-urban_highrise_dense.png': '07_neighbourhood_context',
        'zoning-sensitivity.svg': '03_quality_sensitivity_and_interpretation',
        'context-sensitivity.svg': '03_quality_sensitivity_and_interpretation',
    }
    if owners.get(filename) != stem:
        return managed(f'Reference: [{title}](../../docs/figures/{filename}). '
                       'This linked documentation illustration is separate from the outputs computed below.',
                       stem + ':figure:' + filename)
    alt = f'{title}; reference figure from EPSM documentation'
    text = (f'### Figure guide — {title}\n\n'
            f'![{alt}](../../docs/figures/{filename})\n\n'
            f'**How to read this figure.** {reading}\n\n'
            f'*Source: [EPSM {document.removesuffix(".md")} documentation](../../docs/{document}); '
            f'[open the original figure](../../docs/figures/{filename}).*')
    if 'sensitivity' in filename:
        text += '\n\nThe [retained experiment data](../../docs/figures/geometry-sensitivity-data.json) records run identities, climate files and assumptions for this reference figure.'
    return managed(text, stem + ':figure:' + filename)


# Surgical corrections to the wording of existing user comments; do not replace
# the code cells with the original generator's less explanatory versions.
COMMENT_CORRECTIONS = {
    '# This will create a building with default parameters. ': '# This uses explicit demo assumptions from examples/building.py, not universal package defaults.',
    '# You can modify the parameters in the building() function to create different types of buildings.': '# Use validated b.updated(...) replacements to vary one input while retaining the baseline.',
    "# Non-interactive preview of the building's geometry.": '# preview() shows a static image and, by default, an embedded interactive widget.',
    '# prepare_geometry is a function imported from epsm_core.geometry.': '# prepare_geometry is exported by epsm_core and implemented in epsm_core.preparation.',
    '# Precision: The number of decimal places to round coordinates to.': '# precision_m: coordinate grid spacing in metres (0.001 m is a 1 mm grid).',
    '# Simplification: Whether to simplify the geometry to reduce the number of vertices.': '# simplification_m: distance tolerance in metres for simplifying the outline.',
    '# Max Displacement m: The maximum distance that a vertex can be moved during simplification. and so on..': '# max_displacement_m: the permitted boundary displacement; area and perimeter limits are separate.',
    '# But retrieving a GeometryPreparedResult object is useful because it contains information': '# The returned GeometryPreparationResult is useful because it contains information',
    '# epsm core comes loaded with a set of fixtures for testing. ': '# This repository includes footprint fixtures under tests/fixtures for geometry checks.',
    '# Use the common demo function geometry to create a simple geometry with a single facade and a party wall.': '# Create a rectangular demo geometry, then select one of its facades for a reviewed party wall.',
    '#TODO: Why are we showing the L shape footprint here?': '# Separate synthetic reference: scaled_to_area enables equal-area shape comparisons.\n# This L-shape neither replaces nor approximates the real footprint above.',
}


def enrich(path):
    notebook = nbformat.read(path, as_version=4)
    if notebook.metadata.get("epsm_demo", {}).get("custom_teaching"):
        return
    guide, sections, figure_names = NOTES[path.stem]
    # Stable generated cells are replaceable; every other cell remains user-owned.
    original = [c for c in notebook.cells if not c.metadata.get('epsm_teaching')]
    for cell in original:
        if cell.cell_type == 'code':
            for old, new in COMMENT_CORRECTIONS.items():
                cell.source = cell.source.replace(old, new)
    cells = []
    step = 0
    for index, cell in enumerate(original):
        cells.append(cell)
        if index == 0:
            cells.append(managed('## Understanding the API in this lesson\n\n' + guide, path.stem + ':guide'))
            if figure_names:
                cells.append(figure_cell(figure_names[0], path.stem))
            cells.append(managed(
                '### Before the first code cell\n\n'
                'The setup cell finds the repository, imports the package and plotting tools, and creates a fresh `OUT` directory. '
                '`building()` and `geometry()` are **demo input factories**; `table()`, `plans()`, `bars()` and `preview()` are **presentation helpers**, '
                'not public `epsm_core` entry points. In particular, `preview()` already displays its output and returns no handle, avoiding duplicate widget display. '
                'The public specification and simulation calls remain visible in the lesson cells. '
                'Run the setup once per fresh kernel, then follow the cells in order.', path.stem + ':setup'))
        elif cell.cell_type == 'markdown' and cell.source.startswith('## ') and not cell.source.startswith('## Interpretation'):
            if step < len(sections):
                cells.append(managed('### Read the code and output\n\n' + sections[step], path.stem + ':step:' + str(step)))
                if step+1 < len(figure_names):
                    cells.append(figure_cell(figure_names[step+1], path.stem))
                step += 1
    if step != 3:
        raise ValueError(f'{path}: expected three reviewed teaching sections, found {step}')
    notebook.cells = cells
    notebook.metadata['epsm_demo']['teaching_review'] = '2026-09-07'
    nbformat.validate(notebook)
    nbformat.write(notebook, path)


if __name__ == '__main__':
    notebooks = sorted((ROOT / 'demo').glob('*/*.ipynb'))
    assert {p.stem for p in notebooks} == set(NOTES), 'Every notebook needs an explicit teaching review'
    for filename in FIGURES:
        assert (ROOT / 'docs/figures' / filename).is_file()
    for notebook in notebooks:
        enrich(notebook)
    print(f'Enriched {len(notebooks)} notebooks using {len(FIGURES)} existing documentation figures.')
