# ParametricBuildingGenerator (Simple)

Yes — this is possible, and this repo is now set up as a **minimal** parametric IDF workflow.

It can vary:
- window opening behavior (temperature setpoint)
- envelope U-values (wall/roof/floor/window)
- orientation
- length, width, height, number of floors
- window-to-wall ratio (WWR)
- optional operation inputs: `g_value`, heating/cooling setpoints, infiltration ACH, internal gains
- ventilation/infiltration controls: `infiltration_on`, `natvent_on`, `natvent_opening_factor`

It can run sensitivity with:
- `oat` (one-at-a-time)
- `random`
- `lhs` (latin hypercube)
- `factorial`
- `grid` (min/max/step)

## 1) Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) Set weather file

Put an EPW file at `./weather.epw` or change `paths.weather_file` in `config.json`.

## 3) Run

Generate + simulate + report:

```bash
python run.py --method lhs --samples 32
```

Lightweight parallel run across multiple EPW files:

```bash
python run.py --config config.json --method lhs --samples 24 --weather-dir epw --workers 4
```

You can also set weather in JSON config (no CLI weather args needed):

- Single weather: `paths.weather_file`
- List of weathers: `paths.weather_files`
- Folder of EPWs: `paths.weather_dir`

Grid-based GSA from min/max/step JSON:

```bash
python run.py --config gsa_min_max_step.example.json --method grid
```

Run over a JSON list of simplified archetypes (e.g., TABULA-like):

```bash
python run.py --method lhs --samples 24 --archetypes-json tabula_archetypes.example.json
```

Run with prebuilt Swedish era archetypes (villa + apartment, 10 cases):

```bash
python run.py --method lhs --samples 24 --archetypes-json swedish_era_archetypes.json
```

Quick dry-run (only generate IDFs):

```bash
python run.py --method oat --dry-run
```

## 4) Outputs

In `results/`:
- `case_XXXX/in.idf` (each generated model)
- `results.csv` (all input params + outputs)
- `report.md` (ranked sensitivity summary)
- `sensitivity_site_gj.png` (simple ranking chart)
- `archetypes_map.csv` (only when `--archetypes-json` is used)
- `weather_map.csv` (only when `--weather-dir` has multiple EPWs)

## Notes (kept intentionally simple)

- Single-zone rectangular geometry.
- Simple no-mass envelope representation from target U-values.
- Loads and operational schedules are included by default (people/lights/equipment + thermostat).
- Envelope leakage uses BBR/Boverket q₅₀ [l/(s·m²) at 50 Pa] converted via n₅₀/20 (SS-EN ISO 13789).
- Extended output requests are included by default (hourly variables, meters, and SQLite output).
- Reporting uses annual tabular outputs from EnergyPlus SQL.
- Only parameters present in `parameter_space` are sampled; others stay at baseline values.

## Archetypes JSON format

Pass a list of objects. Each object can use either flat keys or nested `geometry` + `baseline`.

- Geometry keys: `width_m`, `depth_m`
- Baseline keys: any of
	`orientation_deg`, `height_m`, `wwr`, `wall_u`, `roof_u`, `floor_u`, `window_u`,
	`g_value`, `t_heating`, `t_cooling`, `q50_envelope`,
	`occupant_density`, `lighting_w_m2`, `equipment_w_m2`
- Optional: `parameter_space` per archetype (overrides global ranges)

See [tabula_archetypes.example.json](tabula_archetypes.example.json).
Also see [swedish_era_archetypes.json](swedish_era_archetypes.json) for the era ranges you shared.

For min/max/step style GSA, see [gsa_min_max_step.example.json](gsa_min_max_step.example.json).
Use this parameter format:

```json
"wall_u": { "min": 0.15, "max": 0.45, "step": 0.1 }
```

You can organize `parameter_space` into:
- `geometry`
- `envelope`
- `behaviour`
- `heating_system`

Both grouped and legacy flat formats are supported.

Note: `grid` builds the full Cartesian combination, so case count grows fast.
For floor count, use integer-like steps (e.g. `{"min":1,"max":5,"step":1}`); values are rounded to integers.

If you want next steps without making it bloated, add only one at a time:
1. multi-zone geometry,
2. Sobol indices (SALib),
3. uncertainty bands / bootstrap.
