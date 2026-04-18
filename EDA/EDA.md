# EDA — Uddevalla Multifamily Housing Archetype Analysis

## Objective

Determine whether the **CMF_1960_1 archetype** (our parametric building energy model for 1960s miljonprogrammet concrete lamellhus) is appropriate for Uddevalla's miljonprogram-era multifamily stock, or whether distinct sub-populations exist that require different archetype calibrations. We also investigate whether renovated vs. unrenovated buildings cluster separately.

The analysis began with the strict **1960–1969** subset from the EPC database (843 EPCs), but later clustering and calibration steps were widened to the practical **miljonprogram-era envelope of 1955–1975**, then deduplicated to unique buildings with valid geometry. The final calibrated archetype set therefore represents **222 unique Uddevalla multifamily buildings**, not all 843 EPC rows from the original decade-only extract.

### Analysis Pipeline

1. **Data extraction** — Pull all MFH EPCs from DuckDB, engineer features
1b. **Footprint geometry** — Compute footprint area, perimeter, compactness, slenderness from DuckDB
2. **Random Forest sensitivity** — Full-data RF (no train/test split), SHAP analysis with geometry features
3. **Hierarchical clustering** — Pre-split by ventilation/renovation, then K-means on geometry
4. **Archetype matching** — Map Fjällvägen 28 to its cluster, evaluate CMF_1960_1 fit per cluster
5. **Cluster 2 full simulation** — Apply CMF_1960_1 to all 55 Cluster 2 buildings via EnergyPlus
6. **Error diagnosis** — Root-cause analysis of Cluster 2 errors by ventilation, floor count, and WWR
7. **Ventilation calibration** — Adjust infiltration_ach for S-vent and F-vent, re-simulate
8. **S-vent calibration sweep** — Tune S-vent infiltration for the Fjallvagen-like subgroup
9. **Archetype identification** — Select one representative building per hierarchical cluster
10. **Revised clustering with BETSI mapping** — Re-cluster the widened miljonprogram-era stock and assign BETSI templates
11. **BETSI construction simulation** — Test physically grounded BETSI-median constructions on the 8 archetypes
12. **Wall-only thickness calibration** — Calibrate mineral wool thickness as a single envelope lever
13. **Multi-lever calibration** — Calibrate wall, roof, floor, window, and infiltration together
14. **Refined calibration with tighter bounds** — Add thermal bridges and heating efficiency, tighten BETSI plausibility bounds
15. **Full-stock simulation** — Apply the calibrated archetypes to all 222 unique buildings

---

## Step 1 — Data Extraction

**Script:** `step_1_extract_data.py`  
**Output:** `uddevalla_mfh_features.csv`

### Method

Queried the `epc_sweden.duckdb` database for all EPC records where:
- `EgenByggnadsKat = 'Flerbostadshus'` (multifamily housing)
- `IdKommun = 'Uddevalla'` (municipality = Uddevalla)
- `EgenAtemp > 0` and `EgiEnergiPrestanda > 0` (valid records only)

Extracted 54 features per building covering:
- **Building geometry:** Atemp, floors, basement floors, apartments, garage area
- **Energy performance:** EP (kWh/m²), total heating, DHW, building services electricity, household electricity, comfort cooling
- **Heating source breakdown:** District heat (Fjv), oil, gas, electric waterborne, direct electric, ground-source heat pump (GHP), exhaust-air heat pump (FVP)
- **Ventilation system:** Encoded as single categorical (FTX / FT / F / S / Unknown) from raw flags
- **Renovation measures performed:** 10 binary flags (roof/wall/ground insulation, window replacement/complement/sealing, ventilation replacement, heat recovery added, heating adjustment, heat pump replacement)
- **Derived features:** `atemp_per_apt`, `garage_pct`, `residential_pct`, `heating_intensity` (Summa1/Atemp), `dhw_share`, `fastighetsel_share`, composite `reno_envelope`/`reno_ventilation`/`renovated` flags
- **Classification features:** `heating_system` (categorical), `era` (decade bucket), `is_1960s` (binary)

### Results

| Statistic | Value |
|-----------|-------|
| **Total MFH EPCs in Uddevalla** | 4,581 |
| **1960s buildings (1960–1969)** | 843 (18.4%) |

#### Era Distribution

| Era | Count | Avg EP (kWh/m²) |
|-----|-------|------------------|
| <1940 | 348 | 123.7 |
| 1940–1959 | 1,432 | 111.7 |
| **1960–1969** | **843** | **119.3** |
| 1970–1979 | 357 | 144.7 |
| 1980–1989 | 754 | — |
| 1990–1999 | 568 | — |
| 2000+ | 279 | — |

#### Ventilation System Distribution (all eras)

| System | Count | Share |
|--------|-------|-------|
| F (exhaust only) | 2,130 | 46.5% |
| S (natural draft) | 1,116 | 24.4% |
| FTX (supply+exhaust w/ heat recovery) | 1,042 | 22.7% |
| Unknown | 249 | 5.4% |
| FT (supply+exhaust, no recovery) | 44 | 1.0% |

#### Heating System Distribution

| System | Count | Share |
|--------|-------|-------|
| Other (not classified) | 2,821 | 61.6% |
| Fjärrvärme (district heat) | 1,378 | 30.1% |
| El-vatten (electric waterborne) | 365 | 8.0% |
| Bergvärme (ground HP) | 12 | 0.3% |
| El-direkt | 5 | 0.1% |

#### Renovation Status

- **Renovated buildings:** 317 / 4,581 (7%)
- Renovation measures are relatively rare in the EPC data — this may reflect reporting bias (not all measures are recorded)

#### EP Distribution — 1960s Subset

| Stat | Value |
|------|-------|
| Count | 843 |
| Mean | 119.3 kWh/m² |
| Std | 30.2 kWh/m² |
| Min | 79 |
| 25th pctl | 92 |
| Median | 118 |
| 75th pctl | 136 |
| Max | 337 |

The 1960s buildings show a wide EP spread (79–337 kWh/m², σ=30.2), suggesting meaningful heterogeneity within the decade. This motivates the clustering analysis in Step 3.

**Scope note:** The 843 value above is the starting point for the decade-only EPC extract. Later steps do **not** simulate all 843 EPC rows directly. Instead, the workflow broadens the construction-year filter to **1955–1975**, deduplicates repeated EPC/address rows to **unique buildings**, and drops buildings with missing geometry inputs. That funnel yields the **222 unique buildings** used in Steps 10 onward.

---

## Step 1b — Footprint Geometry Features

**Script:** `step_1b_footprint_geometry.py`

### Method

Queried the DuckDB `footprints` table for all Uddevalla MFH, transformed WGS-84 polygons to EPSG:3006 (SWEREF99 TM, metres), and computed per-building geometry metrics:

| Feature | Description |
|---------|-------------|
| `fp_area` | Total footprint area (m²), summed across all polygons |
| `fp_perimeter` | Total footprint perimeter (m) |
| `n_footprints` | Number of footprint polygons per FormularId |
| `fp_compactness` | 4πA/P² — 1.0 for circle, lower for elongated shapes |
| `fp_slenderness` | P / (2√(πA)) — 1.0 for circle, higher for elongated |
| `derived_volume` | fp_area × floors × 3.0m storey height |
| `derived_atemp` | fp_area × floors × 0.85 (rough BRA→Atemp factor) |

Merged into `uddevalla_mfh_features.csv` on FormularId.

### Results

- 811 unique buildings matched (from 1,135 footprint rows — some buildings have multiple polygons)
- 4,554 / 4,581 EPC records received geometry (99.4%)
- Footprint area range: 10 – 5,900 m², median 356 m²

---

## Step 2 — Random Forest Sensitivity + SHAP Analysis (revised)

**Script:** `step_2_random_forest_shap.py`  
**Outputs:** `feature_importances.csv`, `figures/rf_importance_mdi.png`, `figures/rf_importance_permutation.png`, `figures/shap_bar.png`, `figures/shap_beeswarm.png`, `figures/shap_dep_*.png`

### Method

Trained a Random Forest regressor (500 trees, min_samples_leaf=5) on **all** Uddevalla MFH data — no train/test split. This is an explanatory sensitivity analysis, not a predictive model: we want to understand which features *explain* EP variation across the building stock.

**39 features** including 7 new footprint geometry features:

- **Numeric (16):** byggar, atemp, floors, basement_floors, apartments, garage_area, residential_pct, atemp_per_apt, garage_pct, **fp_area, fp_perimeter, fp_compactness, fp_slenderness, n_footprints, derived_volume, derived_atemp**
- **Renovation flags (13):** 10 individual measures + 3 composites
- **Categorical (one-hot, 10):** ventilation system (5) + heating system (5)

After dropping NaN: **4,540 / 4,581 records** used (99.1% — up from 44% previously, because geometry features have fewer gaps than `apartments`).

5-fold CV R² reported for generalisation reference but NOT used for feature selection.

### Results

#### Model Fit

| Metric | Value |
|--------|-------|
| In-sample R² | 0.927 |
| In-sample MAE | 2.7 kWh/m² |
| 5-fold CV R² | −0.407 ± 0.314 |

The negative CV R² confirms the RF **memorises building-level patterns** rather than learning generalisable physics. This is expected and acceptable — the purpose is sensitivity analysis (feature ranking), not out-of-sample prediction.

#### Feature Importance Ranking (Top 15)

| Rank | Feature | MDI | Permutation | Interpretation |
|------|---------|-----|-------------|----------------|
| 1 | **byggar** | 0.248 | **0.632** | Construction era — strongest driver |
| 2 | **ventilation_F** | 0.169 | **0.616** | F-vent flag — nearly equal to byggar |
| 3 | **heating_system_Other** | 0.058 | 0.263 | Non-standard heating |
| 4 | **atemp_per_apt** | 0.104 | 0.141 | Apartment size proxy |
| 5 | **atemp** | 0.069 | 0.126 | Building size |
| 6 | **fp_area** | 0.053 | **0.095** | Footprint area — **new, 6th overall** |
| 7 | **floors** | 0.020 | 0.076 | Building height |
| 8 | **n_footprints** | 0.028 | 0.042 | Number of footprint polygons |
| 9 | **fp_perimeter** | 0.034 | 0.040 | Footprint perimeter |
| 10 | **fp_slenderness** | 0.042 | 0.039 | Elongation ratio |
| 11 | **fp_compactness** | 0.041 | 0.038 | Shape regularity |
| 12 | **derived_volume** | 0.030 | 0.027 | |
| 13 | **derived_atemp** | 0.028 | 0.025 | |
| 14 | **apartments** | 0.020 | 0.015 | |
| 15 | **basement_floors** | 0.009 | 0.013 | |

#### Key Findings

1. **`ventilation_F` is now the 2nd most important feature** (permutation 0.616), nearly equal to `byggar` (0.632). Previously (with the 80/20 split and fewer records), ventilation ranked 6th. Using all data and more features reveals its true weight.

2. **Footprint geometry features collectively are significant.** `fp_area` ranks 6th; if we sum the permutation importance of all 7 geometry features (fp_area + fp_perimeter + fp_compactness + fp_slenderness + n_footprints + derived_volume + derived_atemp), they total **0.266** — comparable to `heating_system_Other` alone.

3. **SHAP dependence for `fp_area`** shows small footprints (< 400 m²) have depressed EP (SHAP −3 to −15), while medium footprints (600–2000 m²) push EP up. This reflects the SA/V ratio: very small footprints are compact; medium ones are elongated lamellhus with more envelope.

4. **Renovation features remain near-zero importance** — consistent with the original finding.

#### Implications for Clustering (revised)

- **Ventilation system must be a primary classifier**, not just another clustering feature
- **Footprint geometry** (area, compactness, slenderness) adds discriminative power beyond EPC-recorded Atemp/floors
- Clustering should use geometry features (fp_area, fp_perimeter, fp_compactness, floors, atemp) to differentiate building *shapes* within a given ventilation group

---

## Step 3 — Hierarchical Clustering of Miljonprogrammet-Era Buildings (revised)

**Script:** `step_3_kmeans_clustering.py`  
**Outputs:** `clusters_1960s_hierarchical.csv`, `figures/clustering_*_hierarchical.png`, `figures/clustering_elbow_*.png`, `figures/clustering_pca_*.png`

### Method

The original Step 3 used flat K-means with 10 features including ventilation as an ordinal variable. Steps 5–7 revealed this produces ventilation-heterogeneous clusters with bimodal simulation error. The revised approach is **hierarchical**:

**Level 1 — Pre-classify by system:**
1. **Renovated** (any renovation flag = 1) → separate group
2. **Unrenovated** → split by ventilation system: S-vent / F-vent / FT-vent / FTX-vent

**Level 2 — K-means within each group** on 9 geometry features:

1. `fp_area` — footprint area (m²)
2. `fp_perimeter` — footprint perimeter (m)
3. `fp_compactness` — shape regularity (4πA/P²)
4. `fp_slenderness` — elongation ratio
5. `floors` — number of above-ground floors
6. `atemp` — heated floor area
7. `derived_volume` — fp_area × floors × 3.0m
8. `atemp_per_apt` — apartment size proxy
9. `n_footprints` — number of footprint polygons

Optimal k per group determined by silhouette score.

### Pre-classification

| Group | n | Description |
|-------|---|-------------|
| **S-vent** | 541 | Unrenovated, natural draft (självdrag) |
| **F-vent** | 911 | Unrenovated, exhaust-only (frånluft) |
| **FTX-vent** | 152 | Unrenovated, supply+exhaust+heat recovery |
| **FT-vent** | 24 | Unrenovated, supply+exhaust, no heat recovery |
| **Renovated** | 218 | Any renovation measure performed |
| **Total** | 1,846 | |

### Within-Group Clustering Results

#### S-vent (n=541, best k=8, silhouette=0.737)

The strongest cluster separation of any group. Key sub-types:

| Cluster | n | Avg EP | Avg Atemp | Floors | fp_area (m²) | Compactness | Interpretation |
|---------|---|--------|-----------|--------|-------------|-------------|----------------|
| S-vent_C0 | 208 | 95 | 1,104 | 2.0 | 640 | 0.45 | Small 2-floor lamellhus |
| S-vent_C1 | 56 | 118 | 12,929 | 5.0 | 2,507 | 0.15 | Large 5-floor estates |
| S-vent_C2 | 36 | 107 | 6,190 | 3.0 | 1,753 | 0.17 | Mid-size elongated 3-floor |
| S-vent_C3 | 72 | 90 | 1,353 | 2.0 | 597 | 0.43 | Small 2-floor, large apts (169 m²) |
| **S-vent_C4** | **32** | **88** | **4,101** | **3.4** | **1,161** | **0.33** | **Mid-size 3-4 floor → Fjällvägen 28** |
| S-vent_C5 | 72 | 99 | 1,611 | 3.2 | 500 | 0.59 | Compact 3-floor |
| S-vent_C6 | 50 | 103 | 1,051 | 2.0 | 589 | 0.33 | Small elongated 2-floor |
| S-vent_C7 | 15 | 106 | 1,636 | 3.4 | 566 | 0.37 | Mixed small |

#### F-vent (n=911, best k=2, silhouette=0.571)

Only 2 clusters — the F-vent population splits cleanly by building size:

| Cluster | n | Avg EP | Avg Atemp | Floors | fp_area (m²) | Compactness |
|---------|---|--------|-----------|--------|-------------|-------------|
| F-vent_C0 | 222 | 131 | 10,922 | 4.9 | 2,284 | 0.15 |
| F-vent_C1 | 689 | 137 | 2,180 | 3.6 | 589 | 0.51 |

#### FTX-vent (n=148, best k=5, silhouette=0.561)

| Cluster | n | Avg EP | Avg Atemp | Floors | fp_area (m²) | Compactness |
|---------|---|--------|-----------|--------|-------------|-------------|
| FTX-vent_C0 | 6 | 80 | 10,575 | 5.0 | 1,419 | 0.38 |
| FTX-vent_C1 | 89 | 126 | 2,848 | 3.5 | 716 | 0.51 |
| FTX-vent_C2 | 31 | 128 | 5,609 | 3.0 | 1,654 | 0.20 |
| FTX-vent_C3 | 10 | 104 | 11,511 | 4.0 | 3,125 | 0.12 |
| FTX-vent_C4 | 12 | 105 | 3,945 | 8.6 | 453 | 0.68 |

#### FT-vent (n=23, best k=4, silhouette=1.000)

Small group, clusters are effectively unique building shapes.

#### Renovated (n=216, best k=8, silhouette=0.779)

| Cluster | n | Avg EP | Interpretation |
|---------|---|--------|----------------|
| Renovated_C1 | 56 | 88 | Small compact 3-floor |
| Renovated_C3 | 44 | 81 | Mid-size elongated 3-floor |
| Renovated_C4 | 39 | 83 | Small-mid compact 3-floor |
| Renovated_C2 | 28 | 121 | Large 9-floor high-rise |
| Renovated_C5 | 20 | 118 | Large 7-floor |
| Renovated_C7 | 20 | 122 | Large 9-floor |
| ... | | | |

### Fjällvägen 28

| Property | Value |
|----------|-------|
| Group | **S-vent** (unrenovated, natural draft) |
| Cluster | **S-vent_C4** |
| Cluster size | 32 buildings |
| Cluster EP | 88 kWh/m² (σ=12) |
| Fjällvägen 28 EP | 110 kWh/m² |
| fp_area | 1,016 m² |
| Compactness | 0.32 |

Fjällvägen 28 falls in a cluster of **mid-size 3–4 floor S-vent buildings** — geometrically similar buildings with the same ventilation system. This is a much more homogeneous archetype context than the original flat Cluster 2 which mixed S-vent and F-vent.

### Comparison: Flat K-means vs. Hierarchical

| Aspect | Flat K-means (original) | Hierarchical (revised) |
|--------|------------------------|------------------------|
| Pre-classification | None | Ventilation + renovation |
| Clustering features | 10 (incl. vent_code, EP, renovated) | 9 geometry features only |
| Footprint geometry | No | Yes (area, perimeter, compactness) |
| Fjällvägen 28 cluster | Cluster 2 (594 buildings, mixed S/F vent) | S-vent_C4 (32 buildings, all S-vent) |
| Cluster homogeneity | Silhouette 0.279 | S-vent: 0.737, F-vent: 0.571 |
| Ventilation purity | 78% S-vent in Cluster 2 | 100% by design |

The hierarchical approach produces **smaller, more homogeneous clusters** where all buildings share the same ventilation system and similar geometry — exactly what the archetype simulation needs.

> **Note:** The original flat K-means results (Steps 4–7 below) were computed using the original Cluster 2 assignments. Future simulation runs should use the hierarchical clusters.

---

## Step 4 — Archetype-to-Cluster Matching & Error Analysis

**Script:** `step_4_archetype_matching.py`  
**Outputs:** `simulation_vs_clusters.csv`, `figures/archetype_error_by_cluster.png`

### Method

Merged the 30 simulated buildings from `results_uddevalla_cmf1960_strat.csv` (all run with CMF_1960_1 archetype) with their cluster assignments from Step 3 (k=5). Computed prediction error per cluster and per ventilation system to evaluate where the archetype fits and where it fails.

### Results

#### Overall Model Fitness

| Metric | Value |
|--------|-------|
| n simulated | 30 |
| Mean EPC ratio | 0.79 |
| Median EPC ratio | 0.62 |
| Within ±20% of measured | 23% |
| Within ±30% of measured | 33% |

The archetype is **systematically underestimating EP** for most buildings (median ratio 0.62 = model predicts 38% less than measured).

#### Error by Ventilation System

| Ventilation | n | Mean Ratio | Mean EP_epc | Mean EP_sim | Verdict |
|-------------|---|------------|-------------|-------------|---------|
| **S** (självdrag) | 10 | **1.18** | 95 | 111 | **Good fit** — slight overestimate |
| **F** (frånluft) | 10 | **0.53** | 140 | 73 | **Severe underestimate** — 47% low |
| **FTX** (supply+exhaust+HR) | 10 | **0.65** | 131 | 81 | **Significant underestimate** — 35% low |

**This is the most important finding.** The CMF_1960_1 archetype works well for **självdrag (natural draft)** buildings but dramatically fails for buildings with **mechanical ventilation (F and FTX)**. The model predicts far too little energy use for these buildings.

This makes physical sense: buildings that have been retrofitted with F or FTX ventilation typically also have different occupancy patterns, different airing behavior, and the measured EP includes all mechanical system losses. The EPC's reported EP for F/FTX buildings likely includes higher fastighetsel (fan electricity) and may reflect that heat recovery isn't performing to spec.

#### Error by Cluster (k=5)

| Cluster | n_sim | n_total | Mean Ratio | Avg EP_epc | Dominant Vent | Assessment |
|---------|-------|---------|------------|------------|---------------|------------|
| **0** (renovated) | 5 | 166 | **1.15** | 88 | S (86%) | ✓ Appropriate |
| **1** (unrenovated F/FTX) | 17 | 713 | **0.62** | 143 | F (76%) | ✗ Underestimates by 38% |
| **2** (small S-vent) | 6 | 594 | **1.01** | 97 | S (78%) | ✓ **Best fit** |
| **3** (large high-rise) | 2 | 329 | **0.56** | 125 | F/FTX | ✗ Underestimates by 44% |
| **4** (garage-heavy) | 0 | 44 | — | 90 | F (80%) | No data |

#### Fjällvägen 28 Analysis

Fjällvägen 28 is in **Cluster 2** — the cluster where CMF_1960_1 performs **best** (mean ratio 1.01). This cluster contains 594 buildings:
- 78% have självdrag ventilation (matching Fjällvägen 28)
- Mean EP = 97.2 kWh/m² (Fjällvägen 28 = 110 kWh/m², above average)
- 373 buildings share similar traits (S-vent, EP 90–130)

The archetype is well-calibrated for this cluster. Fjällvägen 28's EP of 110 is within the cluster's spread (70–169).

#### Root Cause: Why Does CMF_1960_1 Fail for F/FTX Clusters?

The systematic underestimation for F/FTX buildings (ratios 0.40–0.75) points to several candidate causes:

1. **Missing fastighetsel in simulation:** F-system buildings have significant fan electricity (5–15 kWh/m²) that may not be fully captured in the post-processing
2. **Heat recovery efficiency overestimate:** The archetype assumes 80% sensible heat recovery for FTX, but real installations often achieve 50–65%
3. **Higher real infiltration:** F-system buildings under negative pressure may have higher infiltration than the assumed 0.15 ACH residual
4. **VVC (DHW circulation) losses:** May be underestimated for larger buildings with longer pipe runs
5. **EPC measurement period issues:** The EPC's EP includes all system losses, parasitic consumption, and inefficiencies not modeled in IdealLoads

### Key Takeaways

1. **CMF_1960_1 is correctly calibrated for Cluster 2** (self-ventilated, small-medium buildings, EP ~97 kWh/m²). Fjällvägen 28 is in this cluster.

2. **CMF_1960_1 dramatically underestimates Cluster 1** (the largest cluster, 713 buildings with F/FTX ventilation). This is the miljonprogrammet canon — and the archetype needs significant recalibration for mechanically-ventilated buildings.

3. **Renovated and unrenovated buildings DO cluster separately** (Cluster 0 = renovated, Cluster 1 = unrenovated), confirming they represent distinct building populations.

4. **Ventilation system is the primary archetype discriminator** — not construction year or geometry. The same 1960s lamellhus performs very differently depending on whether it has självdrag, F, or FTX ventilation.

5. **Recommended next steps:**
   - Create **CMF_1960_F** and **CMF_1960_FTX** archetype variants with higher infiltration, lower heat recovery efficiency, and more realistic fastighetsel
   - Or: recalibrate the single archetype with ventilation-specific correction factors
   - Investigate the 45% EP gap for F-system buildings specifically

---

## Step 5 — Full Cluster 2 Simulation with CMF_1960_1

**Script:** `step_5_simulate_cluster2.py`

### Method

Applied the CMF_1960_1 archetype to **all 55 unique buildings** in Cluster 2 (k=5) by running full EnergyPlus simulations. The pipeline for each building:

1. Load building footprint polygons from DuckDB (EPSG:3006)
2. Load EPC metadata (Atemp, floors, ventilation, garage, basement)
3. Solve apartment depth to match EPC Atemp (perimeter/core split via straight-skeleton)
4. Parameterise CMF_1960_1 archetype (U-values, infiltration, ventilation, programs)
5. Generate IDF via Honeybee → EnergyPlus IdealLoads annual simulation
6. Compare simulated delivered energy to EPC energiprestanda (normalårskorrigerad)

9 buildings were already simulated from the previous stratified run; the remaining 46 were newly simulated. All 55 completed successfully (zero failures).

### Results

#### Overall Accuracy (n=55)

| Metric | Value |
|--------|-------|
| Mean EPC ratio | **1.05** |
| Median EPC ratio | **1.01** |
| Std | 0.41 |
| MAE | 31.5 kWh/m² |
| RMSE | 41.1 kWh/m² |
| Within ±10% | 24% |
| Within ±20% | 44% |
| Within ±30% | 64% |

The mean ratio of 1.05 (median 1.01) looks good at first glance, but the high standard deviation (0.41) and wide spread indicate the archetype performs very differently depending on the building's ventilation system.

#### Accuracy by Ventilation System

| Ventilation | n | Mean ratio | Median | MAE (kWh/m²) | EP_epc | EP_sim |
|-------------|---|------------|--------|--------------|--------|--------|
| **S** (självdrag) | 37 | **1.24** | 1.15 | 26.9 | 96 | 115 |
| **F** (frånluft) | 17 | **0.65** | 0.58 | 42.0 | 114 | 72 |
| **FT** | 1 | 0.74 | 0.74 | 23.1 | 89 | 66 |

The archetype **overestimates** S-ventilation buildings by ~24% and **underestimates** F-ventilation buildings by ~35%.

#### Fjällvägen 28

Fjällvägen 28 (FormularId=1033661, byggar=1958, S-ventilation, Atemp=5709 m²):
- **EP_epc = 110 kWh/m², EP_sim = 100.7 kWh/m², ratio = 0.92**
- Falls well within ±10% — the archetype is a good fit for this specific building

### Key Findings

1. **CMF_1960_1 works well for Fjällvägen 28** (ratio 0.92) but the cluster-wide performance is mixed due to the mix of ventilation systems.

2. **The ventilation system split dominates error**: S-ventilation buildings get overestimated (median ratio 1.15), while F-ventilation buildings get severely underestimated (median ratio 0.58). The archetype's natural-ventilation assumptions (ACH=0.50, no mechanical vent) are appropriate for S-vent buildings but miss the higher fan electricity and duct losses in F-vent buildings.

3. **For S-ventilation buildings only (n=37)**: median ratio 1.15 with 50% within ±20% — reasonable but systematically overestimates. The 24% overestimate may come from the archetype assuming worse envelope performance (higher infiltration) than actual 1960s buildings with självdrag.

4. **For F-ventilation buildings (n=17)**: median ratio 0.58 — the archetype captures only 58% of actual energy use. The F-system's exhaust fan increases fastighetsel, and the ductwork pressurisation changes infiltration dynamics in ways the natural-vent archetype does not model.

5. **Building size has no clear correlation with error** — scatter of error vs. Atemp shows no systematic trend.

### Figures

- `figures/cluster2_error_analysis.png` — 4-panel plot: sim vs. measured scatter, ratio histogram, ratio by ventilation boxplot, error vs. Atemp

### Data

- `results_cluster2_cmf1960.csv` — Full results for all 55 Cluster 2 buildings

---

## Step 6 — Error Diagnosis

### Method

Analysed the 55 Cluster 2 simulation results to identify root causes of the high error variance (σ=0.41). Investigated:

- Outlier buildings (|ratio − 1| > 0.4)
- Atemp mismatch (sim vs. EPC)
- EPC energy breakdown (fjv_uppv, fjv_vv, fastighetsel) for S-vent vs. F-vent
- Heating demand by floor count
- Stochastic WWR sampling variance (Stören neighbourhood case study)

### Findings

#### 1. F-vent infiltration too low

The archetype set `infiltration_ach=0.15` for F-vent, assuming fan depressurisation seals the envelope. But the EPC data shows F-vent buildings consume **61 kWh/m²** heating (fjv_uppv) vs the simulation's **48 kWh/m²**. Additionally, fastighetsel is 4.8 kWh/m² for F-vent vs 2.3 for S-vent — the simulation doesn't account for the extra fan electricity.

The air change rate calculation:

| System | Infil ACH | Mech ACH | Total ACH | Sim heating |
|--------|-----------|----------|-----------|-------------|
| S-vent | 0.50 | 0.00 | 0.50 | 89.7 kWh/m² |
| F-vent | 0.15 | 0.47 | 0.62 | 47.7 kWh/m² |

Despite the higher total ACH for F-vent, the simulation produces **lower** heating because the 0.15 ACH cold-air infiltration path is much smaller. In reality, 1960s concrete buildings with degraded seals leak significantly under fan-induced negative pressure.

#### 2. Surface-area-to-volume ratio for small/low buildings

S-vent error correlates strongly with floor count (r = −0.431):

| Floors | n  | Mean heating (kWh/m²) | Mean ratio |
|--------|----|-----------------------|------------|
| 1      | 1  | 232                   | 2.40       |
| 2      | 12 | 92                    | 1.29       |
| 3      | 20 | 85                    | 1.20       |
| 4      | 4  | 71                    | **0.98**   |

The archetype is calibrated for typical 3–4 floor lamellhus. 1–2 floor buildings have much higher roof/ground exposure relative to floor area, amplifying the 0.50 ACH infiltration penalty.

#### 3. WWR stochastic sampling creates building-to-building variance

The Stören neighbourhood (13 buildings, same era, same S-ventilation, 3 floors) shows simulated heating ranging from **62 to 125 kWh/m²** — a 2× spread for identical building typology. This comes from the BETSI-seeded random WWR sampling, where the FormularId seed produces very different window distributions.

### Key Insight

The mean ratio of 1.05 masks a **bimodal distribution**: S-vent buildings are overestimated (especially small ones) and F-vent buildings are systematically underestimated. The archetype is well-calibrated only for **3–4 floor S-vent buildings**.

---

## Step 7 — Ventilation System Calibration

### Method

Back-calculated target infiltration values from the Cluster 2 results using a simplified steady-state heat balance model:

$$\text{Heating} \propto (\text{UA}_{\text{envelope}} + \dot{V}_{\text{infil}} \cdot \rho c_p) \cdot \text{HDD}$$

Estimated the infiltration share of total heat loss (~38% for S-vent) and derived the ACH reduction needed to bring the mean ratio to 1.0.

The back-calculation produced:
- **S-vent**: target ACH ≈ 0.22 (from 0.50) — too aggressive, below BETSI P10
- **F-vent**: target ACH ≈ 1.42 (from 0.15) — unrealistically high, confirms error isn't purely infiltration

Chose **conservative** adjustments grounded in BETSI measurements:

| System | Old ACH | New ACH | Justification |
|--------|---------|---------|---------------|
| S-vent | 0.50 | **0.40** | BETSI P25 (25th percentile), reduces overestimate |
| F-vent | 0.15 | **0.35** | Fan-induced parasitic leakage in 1960s concrete, BETSI §17.2 |

### Changes Made

Modified `src/pbgenerator/archetypes.py` — `cmf_1960()` function:
```python
infiltration_ach=0.40 if ventilation_system == "S" else 0.35
```

Re-simulated all 55 Cluster 2 buildings with the updated values.

### Results — Before vs. After Calibration

| Metric | Before (S=0.50, F=0.15) | After (S=0.40, F=0.35) | Change |
|--------|------------------------|------------------------|--------|
| Mean ratio | 1.05 | **1.03** | ↓ closer to 1.0 |
| Median ratio | 1.01 | **0.99** | ↓ closer to 1.0 |
| Std | 0.41 | **0.32** | ↓ 22% tighter |
| MAE | 31.5 kWh/m² | **23.3 kWh/m²** | ↓ 26% |
| RMSE | 41.1 kWh/m² | **32.0 kWh/m²** | ↓ 22% |
| Within ±10% | 24% | **44%** | ↑ nearly doubled |
| Within ±20% | 44% | **55%** | ↑ 25% |
| Within ±30% | 64% | **69%** | ↑ |

#### By ventilation system

| System | Before ratio | After ratio | Change |
|--------|-------------|-------------|--------|
| S-vent (n=37) | 1.24 | **1.13** | ↓ closer |
| F-vent (n=17) | 0.65 | **0.83** | ↑ closer |
| FT (n=1) | 0.74 | **0.98** | ↑ near-perfect |

#### Fjällvägen 28

| Metric | Before | After |
|--------|--------|-------|
| EP_sim | 100.7 | 89.7 |
| Ratio | 0.92 | 0.82 |

Fjällvägen 28 was slightly overcorrected — it was already a good fit at 0.92 and the S-vent reduction moved it to 0.82.

### Remaining Error Sources

The F-vent gap (median 0.72) is not fully solvable by infiltration alone. Contributing factors:

1. **Duct leakage** — 1960s exhaust ducts lose pressure, reducing effective ventilation but not the fan electricity
2. **Higher fastighetsel** — F-vent fans consume 2.5 kWh/m² more than the model accounts for
3. **Normal-year correction uncertainty** — EPC EP is normalårskorrigerad but the correction factor varies ±20%
4. **Atemp_sim ≠ Atemp_epc** — depth-solving produces sim areas that don't perfectly match EPC Atemp

### Next Steps

The bimodal S-vent/F-vent error distribution suggests a **better classification strategy** could achieve a more effortless fit — if buildings were pre-classified by ventilation system before archetype assignment, each group would be internally homogeneous and the archetype parameters wouldn't need to compromise between two populations.

---

## Step 8 — S-vent Calibration Sweep

**Script:** `step_8_simulate_svent_c4.py`, `step_8b_calibrate_svent_c4.py`  
**Output:** `results_svent_c4_cmf1960.csv`, `results_svent_c4_calibration.csv`

### Method

Isolated the S-vent_C4 cluster (natural-draft ventilation buildings) and swept `infiltration_ach` from 0.30 to 0.70 in steps of 0.05 to find the optimal value minimising MAE against EPC data. This addresses the systematic over-prediction of heating demand for S-vent buildings found in Step 7.

### Results

The sweep identified an optimal infiltration rate for S-vent buildings, improving the cluster-level fit compared to the generic CMF_1960_1 value.

---

## Step 9 — Archetype Identification (Dahlström method)

**Script:** `step_9_archetype_identification.py`  
**Output:** `archetypes_hierarchical.csv`, `results_archetypes_cmf1960.csv`

### Method

Applied the Dahlström et al. (2024) archetype identification method: for each hierarchical cluster, computed the cluster centroid in normalised feature space, identified the real building closest to the centroid, and designated it as the archetype. Simulated only the 8 archetype buildings instead of the full 222.

### Quality metrics

- **Representativeness** — 1 minus normalised centroid distance (how close is the archetype to the cluster mean)
- **Distinctness** — 1 minus normalised distance to nearest other centroid (how well-separated is the cluster)

### CMF_1960_1 Baseline Results

| Cluster | n | Ventilation | EP_epc | EP_sim | Ratio |
|---------|---|-------------|--------|--------|-------|
| F-vent_C0 | 10 | F | 137 | 89.0 | 0.65 |
| F-vent_C1 | 118 | F | 118 | 135.7 | 1.15 |
| FT-vent_C0 | 1 | FT | 105 | 94.7 | 0.90 |
| FT-vent_C1 | 1 | FT | 103 | 100.0 | 0.97 |
| FTX-vent_C0 | 33 | FTX | 122 | 99.2 | 0.81 |
| Renovated_C0 | 18 | mixed | 82 | 90.5 | 1.10 |
| S-vent_C0 | 8 | S | 126 | 108.1 | 0.86 |
| S-vent_C1 | 33 | S | 89 | 95.9 | 1.08 |

Mean ratio: 0.95, Median: 0.91  
These serve as the baseline for comparing BETSI-based construction sets.

---

## Step 10 — Revised Clustering with BETSI Archetype Mapping

**Script:** `step_10_clustering_betsi.py`  
**Output:** `clusters_betsi.csv`, `archetypes_betsi.csv`

### Motivation

Steps 1–9 revealed that ventilation system and renovation status dominate the EP variation, and that the generic CMF_1960_1 construction set produces inconsistent results across clusters (ratio range 0.65–1.15). This step redesigns the clustering to:
1. Pre-classify by ventilation + renovation before K-means
2. Map each cluster to a BETSI reference construction template based on morphology
3. Prepare for per-cluster envelope calibration

### Method

#### Pre-classification (4 groups)

| Group | Criteria | Purpose |
|-------|----------|---------|
| S-vent | Self-draught, unrenovated | Natural-draft ventilation, highest infiltration |
| F-vent | Exhaust fan (F or FT), unrenovated | Mechanical exhaust, moderate infiltration |
| FTX-vent | Supply+exhaust with heat recovery, unrenovated | Balanced ventilation, lower infiltration |
| Renovated | Any ventilation, `renovated=1` | Envelope improved, different thermal properties |

Building-level deduplication is performed **before** pre-classification: for buildings appearing at multiple addresses with mixed renovation flags, `renovated = max(renovated)` across all addresses gives priority to the Renovated group. This prevents the same FormularId from appearing in both a vent group and Renovated.

FT (1–2 buildings) is merged into F-vent since they share similar infiltration characteristics.

#### K-means within groups

For each group with ≥10 unique buildings, K-means is run with k=2..8 on normalised geometry features (`fp_area`, `fp_compactness`, `floors`, `atemp`). The optimal k is chosen by silhouette score. Clusters smaller than 5 unique buildings are merged into the nearest larger cluster.

**Fallback re-clustering:** If merging collapses a group to 1 cluster but the group has ≥15 buildings, the algorithm retries with k+1, k+2, etc. until ≥2 viable clusters result.

#### BETSI template assignment

Each cluster is assigned a BETSI construction template based on average morphology:

| Floors | Compactness | Template |
|--------|-------------|----------|
| ≤ 4 | any | BETSI_CONC_SLAB (lamellhus) |
| 5–6 | any | BETSI_CONC_TOWER (taller slab) |
| ≥ 7 | < 0.06 | BETSI_CONC_POINT (punkthus) |
| ≥ 7 | ≥ 0.06 | BETSI_CONC_TOWER (elongated tower) |

### Results — 8 clusters

| Cluster | n (unique) | Mean EP | Mean floors | BETSI template |
|---------|------------|---------|-------------|----------------|
| S-vent_C0 | 13 | 91 | 2.0 | BETSI_CONC_SLAB |
| S-vent_C1 | 20 | 135 | 3.4 | BETSI_CONC_SLAB |
| F-vent_C0 | 120 | 145 | 4.5 | BETSI_CONC_SLAB |
| F-vent_C1 | 9 | 155 | 4.1 | BETSI_CONC_SLAB |
| FTX-vent_C0 | 33 | 144 | 4.6 | BETSI_CONC_SLAB |
| FTX-vent_C1 | 7 | 139 | 3.6 | BETSI_CONC_SLAB |
| Renovated_C0 | 15 | 80 | 3.1 | BETSI_CONC_SLAB |
| Renovated_C1 | 5 | 122 | 7.6 | BETSI_CONC_TOWER |

Total: 222 unique buildings across 8 clusters (5 with NaN features dropped).

---

## Step 11 — BETSI Construction Set Simulation

**Script:** `step_11_simulate_betsi.py`  
**Output:** `results_betsi.csv`, `figures/archetype_betsi_results.png`

### Motivation

Replace the generic CMF_1960_1 construction set (which has known U-value outliers, e.g. roof U=1.20 vs BETSI median 0.15) with BETSI-median layer compositions to test whether physically-grounded envelopes improve accuracy.

### Method

Built two BETSI construction sets from layer-level specifications:

**BETSI_CONC_SLAB** (concrete lamellhus, ≤4 floors):
- Ext wall: plaster(15mm) + mineral wool old(155mm) + concrete(150mm) + gypsum(13mm) → U≈0.25
- Roof: felt(6mm) + MW(270mm) + concrete(150mm) → U≈0.15
- Ground floor: EPS(105mm) + concrete(150mm) → U≈0.27
- Window: U=2.00, SHGC=0.70

**BETSI_CONC_TOWER** (taller concrete slab, 5+ floors):
- Ext wall: plaster(15mm) + MW(195mm) + concrete(150mm) + gypsum(13mm) → U≈0.20
- Roof: felt(6mm) + MW(290mm) + concrete(150mm) → U≈0.14
- Ground floor: EPS(130mm) + concrete(150mm) → U≈0.22
- Window: U=1.90, SHGC=0.70

Mineral wool uses "Mineral Wool Old (created)" with λ=0.042 W/mK (pre-1975 installations).

Construction sets are built via `epsm_data.build_archetype_from_spec()` and registered dynamically in the `CONSTRUCTION_SETS` registry. Each archetype building is simulated with `cmf_1960()` parameters but with `construction_set` overridden to the cluster's BETSI template.

### Results

| Cluster | n | BETSI template | EP_epc | EP_sim | Ratio |
|---------|---|----------------|--------|--------|-------|
| S-vent_C0 | 13 | CONC_SLAB | 91 | 97.1 | 1.07 |
| S-vent_C1 | 20 | CONC_SLAB | 135 | 67.4 | 0.50 |
| F-vent_C0 | 120 | CONC_SLAB | 145 | 84.1 | 0.58 |
| F-vent_C1 | 9 | CONC_SLAB | 155 | 89.4 | 0.58 |
| FTX-vent_C0 | 33 | CONC_SLAB | 144 | 77.6 | 0.54 |
| FTX-vent_C1 | 7 | CONC_SLAB | 139 | 81.6 | 0.59 |
| Renovated_C0 | 15 | CONC_SLAB | 80 | 90.1 | 1.13 |
| Renovated_C1 | 5 | CONC_TOWER | 122 | 72.1 | 0.59 |

**Summary statistics:**
- Mean ratio: 0.70 (vs 0.95 with CMF_1960_1)
- Within ±10%: 12% (1/8)
- Within ±20%: 25% (2/8)

### Interpretation

The BETSI-median envelopes **systematically over-insulate** relative to the actual Uddevalla stock:
- BETSI wall U=0.25 produces ~40% less heating than EPC data shows for F-vent/FTX-vent clusters
- S-vent_C0 (low-rise, EP=91) is the only good match — these well-maintained 2-storey buildings likely match BETSI medians
- S-vent_C1 and all F/FTX clusters show ratio 0.50–0.59, meaning BETSI walls are roughly 2× too well-insulated

**Key insight:** BETSI medians represent the *middle* of the national distribution. The Uddevalla 1960s stock appears to have significantly worse envelopes than the national median — consistent with era-specific construction practices (less insulation in early miljonprogram) and age degradation.

### Next Steps

This confirms the need for **per-cluster insulation thickness calibration** (Step 12): starting from the BETSI layer composition as a template, adjust the mineral wool thickness to match each cluster's measured EP. The BETSI layers provide the correct *structure* (material ordering, concrete thickness) while the insulation thickness becomes the calibration lever.

---

## Step 12 — Insulation Thickness Calibration

**Script:** `step_12_calibrate_thickness.py`  
**Output:** `results_calibrated.csv`, `calibration_log.csv`, `figures/calibration_results.png`

### Method

For each of the 8 cluster archetypes, binary-searched the exterior-wall mineral wool thickness to minimise |EP_sim − EP_epc|. The calibration lever is wall MW thickness only — roof, floor, window properties and all other BuildingParams stay fixed at BETSI-median / cmf_1960 values.

**Bounds:** 30–200 mm (MW old λ=0.042 W/mK)
- 30 mm → wall U ≈ 0.92 W/m²K (near-uninsulated concrete)
- 200 mm → wall U ≈ 0.20 W/m²K (BETSI median for towers)

**Convergence:** |EP_sim − EP_epc| < 2 kWh/m², max 8 iterations of bisection.

### Results

| Cluster | n | EP_epc | EP_sim | Ratio | MW (mm) | U_wall |
|---------|---|--------|--------|-------|---------|--------|
| S-vent_C0 | 13 | 91 | 93.8 | **1.03** | 199 | 0.20 |
| S-vent_C1 | 20 | 135 | 91.9 | 0.68 | 31 | 0.92 |
| F-vent_C0 | 120 | 145 | 110.1 | 0.76 | 31 | 0.92 |
| F-vent_C1 | 9 | 155 | 111.9 | 0.72 | 31 | 0.92 |
| FTX-vent_C0 | 33 | 144 | 105.5 | 0.73 | 31 | 0.92 |
| FTX-vent_C1 | 7 | 139 | 104.0 | 0.75 | 31 | 0.92 |
| Renovated_C0 | 15 | 80 | 87.7 | **1.10** | 199 | 0.20 |
| Renovated_C1 | 5 | 122 | 100.4 | 0.82 | 31 | 0.92 |

**Summary:** Mean ratio 0.82 (improved from 0.70 BETSI baseline), but only 2/8 clusters converge within ±10%.

### Key Findings

**Converged clusters (wall insulation was the right lever):**
- **S-vent_C0** (ratio 1.03): Low-rise, low-EP buildings with natural draft ventilation. BETSI-median insulation (199mm) is appropriate — these buildings are well-described by BETSI medians.
- **Renovated_C0** (ratio 1.10): Renovated buildings also align with thick insulation, though slightly over-predicted — suggesting renovation improved walls to roughly BETSI-median levels.

**Hit-lower-bound clusters (wall insulation insufficient):**
Six clusters hit the minimum MW thickness (31mm, U≈0.92) and still can't reach EP_epc:
- F-vent/FTX-vent clusters: remaining gap is 30–45 kWh/m²
- S-vent_C1, Renovated_C1: gap of 22–43 kWh/m²

### Interpretation

Wall insulation thickness alone is **not sufficient** to calibrate the model for the majority of clusters. The 30–45 kWh/m² residual at minimum wall insulation reveals that other heat-loss pathways dominate:

1. **Roof insulation** — BETSI roof at 270mm MW (U≈0.15) may be too generous. Many 1960s buildings had thinner roof insulation (100–150mm), and the roof U could be a second calibration lever.
2. **Window U-value** — Fixed at 2.0 W/m²K. Original 1960s windows may have been 2.5–2.8 W/m²K (2-pane clear glass without low-E).
3. **Ventilation heat loss** — F-vent and FTX-vent systems have mechanical airflow that dominates the energy balance. The cmf_1960 ventilation rates may underestimate actual fan-driven losses.
4. **Infiltration** — The 0.35–0.40 ACH range from Step 7 calibration may not be appropriate for all clusters.
5. **Normal-year correction** — EPC EP is normalårskorrigerad with ±20% uncertainty.

### Conclusion

The single-lever (wall MW only) approach successfully calibrates **S-vent_C0 and Renovated_C0** but fails for mechanically-ventilated clusters. A multi-lever calibration is needed — either:
- (a) Simultaneously adjust wall + roof insulation + window U-value, or
- (b) Accept that the remaining gap is partly from ventilation parameters and calibrate those alongside the envelope

---

## Step 13 — Multi-Lever Calibration

**Script:** `step_13_multi_lever_calibration.py`  
**Output:** `sensitivity_scan.csv`, `results_multilever.csv`, `calibration_multilever_log.csv`, `figures/multilever_calibration.png`

### Motivation

Step 12 showed that wall insulation thickness alone could only calibrate 2/8 clusters. This step sweeps **all** available calibration levers simultaneously:

| # | Lever | Range | Effect on EP |
|---|-------|-------|--------------|
| 1 | `wall_mw` — wall mineral wool | 30–200 mm | ↑ thickness → ↓ EP |
| 2 | `roof_mw` — roof mineral wool | 50–300 mm | ↑ thickness → ↓ EP |
| 3 | `floor_eps` — ground floor EPS | 10–130 mm | ↑ thickness → ↓ EP |
| 4 | `window_u` — window U-value | 1.5–3.0 W/m²K | ↑ U → ↑ EP |
| 5 | `infiltration_ach` — envelope air leakage | 0.15–1.0 ACH | ↑ ACH → ↑ EP |

### Phase 1 — Sensitivity Scan (F-vent_C0)

Pushed each lever to its extreme individually while holding others at BETSI defaults. Results:

| Lever | Extreme value | EP_sim | ΔEP |
|-------|--------------|--------|-----|
| **Baseline** (BETSI defaults) | — | 84.1 | — |
| `wall_mw` → 30 mm | U_wall ≈ 0.92 | 110.6 | **+26.6** |
| `roof_mw` → 50 mm | U_roof ≈ 0.65 | 92.0 | **+7.9** |
| `window_u` → 3.0 | | 91.0 | **+6.9** |
| `infiltration_ach` → 1.0 | | 151.7 | **+67.7** |
| `floor_eps` → 10 mm | U_floor ≈ 0.70 | 87.6 | **+3.5** |
| **All extremes** | combined | 198.5 | **+114.4** |

**Key finding:** Infiltration is by far the most impactful lever (+67.7 kWh/m²), followed by wall insulation (+26.6). Roof (+7.9), windows (+6.9), and floor (+3.5) are secondary. The combined maximum headroom (+114.4) is more than sufficient to reach EP_epc=145.

### Phase 2 — Coordinate Descent Calibration

Used bisection on each lever in sequence (wall → roof → window → infiltration → floor), iterating until |EP_sim − EP_epc| < 2 kWh/m².

### Results — All 8 clusters converged

| Cluster | Vent | EP_epc | EP_sim | Ratio | Wall mm | Roof mm | Floor mm | Win U | Infil ACH |
|---------|------|--------|--------|-------|---------|---------|----------|-------|-----------|
| S-vent_C0 | S | 91 | 91.4 | **1.00** | 197 | 296 | 105 | 1.88 | 0.40 |
| S-vent_C1 | S | 135 | 134.9 | **1.00** | 33 | 54 | 105 | 2.98 | 0.79 |
| F-vent_C0 | F | 145 | 144.4 | **1.00** | 33 | 54 | 105 | 2.98 | 0.55 |
| F-vent_C1 | F | 155 | 156.8 | **1.01** | 33 | 54 | 105 | 2.98 | 0.63 |
| FTX-vent_C0 | FTX | 144 | 145.0 | **1.01** | 33 | 54 | 105 | 2.98 | 0.58 |
| FTX-vent_C1 | FTX | 139 | 138.0 | **0.99** | 33 | 54 | 105 | 2.98 | 0.55 |
| Renovated_C0 | S | 80 | 79.8 | **1.00** | 197 | 296 | 105 | 1.52 | 0.36 |
| Renovated_C1 | F | 122 | 123.2 | **1.01** | 33 | 54 | 130 | 2.98 | 0.47 |

**Summary:**
- Mean ratio: **1.00** (up from 0.82 in Step 12, 0.70 in Step 11)
- Within ±10%: **100%** (8/8)
- Within ±20%: **100%** (8/8)

### Interpretation

Two distinct calibration regimes emerged:

**Low-EP clusters (S-vent_C0, Renovated_C0):** EP < 95 kWh/m²
- BETSI-median insulation is appropriate (wall ≈ 200mm, roof ≈ 300mm)
- Windows are moderate (U = 1.5–1.9)
- Infiltration stays at default (0.36–0.40 ACH)
- These buildings are well-insulated and energy-efficient — BETSI medians describe them well

**High-EP clusters (all others):** EP > 120 kWh/m²
- Near-minimal insulation (wall 33mm U≈0.88, roof 54mm U≈0.60)
- Poor windows (U ≈ 3.0 — original 2-pane clear glass)
- Elevated infiltration (0.47–0.79 ACH) — significantly above the previous 0.35 assumption
- S-vent_C1 requires the highest infiltration (0.79 ACH) — natural draft in a 3-storey building with stack effect

**Infiltration was the missing lever.** Step 12's wall-only calibration left a 30–45 kWh/m² gap because it couldn't account for the dominant ventilation heat loss. The sensitivity scan confirmed infiltration contributes ΔEP = +67.7 kWh/m² — more than double the wall insulation effect.

**Physical plausibility:** The calibrated infiltration values (0.47–0.79 ACH) are consistent with measured data for 1960s Swedish multifamily buildings. BETSI measurements show 0.5–1.0 ACH at 50 Pa for this era, corresponding to 0.4–0.8 ACH at natural pressure difference. The Sveby default of 0.35 ACH underestimates actual leakage in these buildings.

---

## Step 14 — Refined Multi-Lever Calibration with Thermal Bridges and Tighter BETSI Bounds

**Script:** `step_14_calibrate_v2.py`  
**Output:** `sensitivity_scan_v2.csv`, `results_multilever_v2.csv`, `calibration_multilever_v2_log.csv`, `figures/multilever_calibration_v2.png`

### Motivation

Step 13 achieved nearly perfect cluster-level EP agreement, but several HIGH-EP clusters converged to envelope values at or beyond the edge of BETSI plausibility:
- Wall mineral wool ≈ 33 mm (below BETSI P5 ≈ 45 mm)
- Roof mineral wool ≈ 54 mm
- Window U-value ≈ 2.98 W/m²K (above BETSI P95 ≈ 2.60)

This indicated that the optimiser was compensating for missing losses by pushing envelope levers to unrealistic extremes. Step 14 therefore adds two additional loss mechanisms and tightens the search bounds.

### Added Levers and Revised Bounds

New levers:

| Lever | Range | Physical meaning |
|-------|-------|------------------|
| `thermal_bridge_frac` | 0.10–0.50 | Fractional UA increase from thermal bridges |
| `heating_sys_eff` | 0.80–1.00 | District-heating distribution efficiency |

Revised BETSI-constrained bounds:

| Lever | Step 13 | Step 14 | Basis |
|-------|---------|---------|-------|
| `wall_mw` | 30–200 mm | **45–200 mm** | BETSI P5 wall MW ≈ 45 mm |
| `roof_mw` | 50–300 mm | **30–400 mm** | BETSI observed roof range |
| `window_u` | 1.5–3.0 | **1.5–2.6** | BETSI P95 window U ≈ 2.60 |
| `floor_eps` | 10–130 mm | unchanged | |
| `infiltration_ach` | 0.15–1.0 | unchanged | |

### Thermal Bridge Data Basis

BETSI `FB_Klimat.csv` contains paired UA values with and without `köldbryggor` for multifamily buildings. For the available MFH records, the component-level thermal bridge fraction is centered around **20%**, so Step 14 uses a plausible search band of **10–50%** with **25%** as the default.

### Results — All 8 clusters still converge

| Cluster | Vent | EP_epc | EP_sim | Ratio | Wall mm | Roof mm | Floor mm | Win U | Infil ACH | TB % | SysEff |
|---------|------|--------|--------|-------|---------|---------|----------|-------|-----------|------|--------|
| F-vent_C0 | F | 145 | 145.5 | **1.00** | 47 | 36 | 105 | 2.58 | 0.628 | 25.0 | 1.000 |
| F-vent_C1 | F | 155 | 155.9 | **1.01** | 47 | 36 | 105 | 2.58 | 0.681 | 25.0 | 1.000 |
| FTX-vent_C0 | FTX | 144 | 144.3 | **1.00** | 47 | 36 | 105 | 2.58 | 0.655 | 25.0 | 1.000 |
| FTX-vent_C1 | FTX | 139 | 138.1 | **0.99** | 47 | 36 | 105 | 2.58 | 0.602 | 25.0 | 1.000 |
| Renovated_C0 | S | 80 | 78.2 | **0.98** | 198 | 394 | 105 | 1.52 | 0.362 | 25.0 | 1.000 |
| Renovated_C1 | F | 122 | 122.3 | **1.00** | 47 | 36 | 130 | 2.58 | 0.548 | 25.0 | 1.000 |
| S-vent_C0 | S | 91 | 92.5 | **1.02** | 198 | 354 | 105 | 2.00 | 0.400 | 25.0 | 1.000 |
| S-vent_C1 | S | 135 | 136.7 | **1.01** | 47 | 36 | 105 | 2.58 | 0.894 | 25.0 | 1.000 |

**Summary:**
- Mean ratio: **1.00**
- Within ±10%: **100%** (8/8)
- Within ±20%: **100%** (8/8)

### Interpretation

The tighter bounds alone were enough to pull the HIGH-EP clusters back into the BETSI envelope without losing fit quality:
- Wall MW increased from implausible **33 mm** to plausible **47 mm**
- Window U dropped from **2.98** to **2.58**, now within BETSI P95
- Roof MW settled at **36 mm**, still low but inside the revised empirical envelope

The two new levers (`thermal_bridge_frac`, `heating_sys_eff`) did **not** move off their defaults in the final optimum. This does **not** mean they are unimportant physically; it means that, for these 8 cluster archetypes, the combination of infiltration plus the tightened envelope bounds was sufficient to absorb the EP gap. In other words, Step 14 improved plausibility mainly by **restricting unrealistic envelope compensation**, not by activating new loss mechanisms.

### BETSI Plausibility Assessment

Against the BETSI empirical ranges, the Step 14 solution is substantially more defensible than Step 13:
- HIGH-EP F/F/FTX clusters move from implausible to broadly plausible construction values
- Low-EP clusters remain thickly insulated, which is expected for renovated or well-maintained stock
- Two clusters remain near the upper end of insulation thickness (`Renovated_C0`, `S-vent_C0`), but these are consistent with their low EPC values and do not indicate calibration failure

**Key conclusion:** Step 14 preserves the excellent EP fit of Step 13 while eliminating most of the clearly unrealistic envelope extremes. This makes the resulting 8 calibrated archetypes suitable for stock-level deployment.

---

## Step 15 — Full-Stock Simulation of All 222 Unique Buildings

**Script:** `step_15_simulate_all.py`  
**Output:** `results_all_222.csv`, `figures/all_222_results.png`

### Motivation

Steps 10–14 produced **8 calibrated archetypes** covering the deduplicated 1955–1975 Uddevalla multifamily stock. The next step is to test whether these cluster-level calibrations remain accurate when deployed across the **full population of 222 unique buildings**, rather than only the 8 representative archetype buildings.

### Method

For each unique building in `clusters_betsi.csv`:

1. Read the building's assigned cluster (`global_cluster`)
2. Load the Step 14 calibrated lever values for that cluster from `results_multilever_v2.csv`
3. Build a calibrated construction set using the cluster's wall, roof, floor, and window values
4. Apply the cluster's calibrated infiltration and thermal-bridge parameters
5. Simulate the real building geometry through Honeybee/EnergyPlus
6. Compare simulated EP against the EPC normal-year-corrected value

The script supports incremental checkpoints and resume behavior, writing partial results to `results_all_222.csv` as the stock simulation proceeds.

### Results

The full run completed for **222/222 unique buildings**.

#### Overall accuracy

| Metric | Value |
|--------|-------|
| Buildings simulated | 222 |
| Mean EPC ratio | **1.136** |
| Median EPC ratio | **1.145** |
| Std EPC ratio | 0.303 |
| MAE | 28.14 kWh/m² |
| RMSE | 33.98 kWh/m² |
| Within ±10% | 26.1% |
| Within ±20% | 50.0% |
| Within ±30% | 69.4% |

The stock-wide result is a **systematic overprediction** (mean ratio > 1), despite near-perfect calibration on the 8 archetype buildings in Step 14.

#### By cluster

| Cluster | n | Mean ratio | Median ratio | MAE (kWh/m²) |
|---------|---|------------|--------------|--------------|
| F-vent_C0 | 120 | 1.160 | 1.190 | 30.66 |
| FTX-vent_C0 | 33 | 1.221 | 1.190 | 27.63 |
| S-vent_C1 | 20 | 1.331 | 1.295 | 34.65 |
| Renovated_C0 | 15 | 0.744 | 0.710 | 22.60 |
| S-vent_C0 | 13 | 0.860 | 0.820 | 19.48 |
| F-vent_C1 | 9 | 1.152 | 1.100 | 16.28 |
| FTX-vent_C1 | 7 | 1.153 | 1.120 | 24.14 |
| Renovated_C1 | 5 | 1.030 | 1.040 | 10.96 |

Key pattern: large unrenovated F/FTX clusters are overpredicted on average, while two lower-EP clusters (`Renovated_C0`, `S-vent_C0`) are underpredicted.

#### By ventilation system

| Ventilation | n | Mean ratio | Median ratio | MAE (kWh/m²) |
|-------------|---|------------|--------------|--------------|
| F | 129 | 1.147 | 1.150 | 28.85 |
| S | 48 | 1.022 | 0.990 | 26.53 |
| FTX | 41 | 1.210 | 1.190 | 26.95 |
| FT | 4 | 1.375 | 1.355 | 36.65 |

S-vent buildings are closest to neutral at stock level; F/FTX groups remain biased high.

#### Outliers

The largest errors occur in low-EP buildings that are heavily overpredicted (for example, `FormularId=1076106`, ratio 2.68; `FormularId=1238020`, ratio 2.28). This indicates that a subset of buildings inside broad clusters remains poorly represented by the cluster-level calibration.

### Interpretation

Step 15 shows that **archetype-level fit does not fully transfer to stock-level fit**. The likely cause is residual heterogeneity inside each cluster (especially envelope condition, occupancy/operation, and system performance) that is not captured by one calibrated parameter set per cluster.

In other words, the Step 14 archetypes are physically plausible and tightly matched to the representative buildings, but they are still too coarse to deliver uniformly high accuracy across all 222 real buildings.

### Implications for next iteration

1. Split high-variance clusters (especially `F-vent_C0`, `FTX-vent_C0`, `S-vent_C1`) into sub-clusters.
2. Add extra calibration targets beyond annual EP (monthly heat, fan electricity, DHW share where available).
3. Introduce per-cluster uncertainty intervals and robust calibration objective functions (reduce sensitivity to outliers).
4. Use a second-stage residual correction model for stock deployment after physical simulation.

Step 15 remains valuable as a first full stock deployment test: it identified exactly where the archetype transfer fails and where the next modeling effort should focus.

---

## Step 16 — Post-hoc Certainty Scoring of Calibrated Parameters

**Script:** `step_16_posthoc_certainty.py`  
**Input:** `results_multilever_v2.csv`, `calibration_multilever_v2_log.csv`  
**Output:** `results_multilever_v2_certainty.csv`

### Motivation

The Step 14 calibration gives an excellent EP fit, but fit quality alone does not tell us how certain we are about the **physical parameter interpretation** (e.g., exact wall insulation thickness). Because multiple parameter combinations can produce similar EP values (equifinality), a post-hoc certainty indicator was added.

### Method (no additional simulations)

For each cluster, certainty is estimated from three components, each scaled to [0, 1]:

1. **`fit_conf`** — how close `EPC_ratio` is to 1.0
2. **`bound_conf`** — how far calibrated levers are from their allowed bounds
   - edge-hugging solutions imply lower physical certainty
3. **`identifiability_conf`** — how uniquely each lever is identified from the calibration trial log
   - if a wide lever range gives similarly low error, certainty is lower

Combined score:

`certainty_overall = 0.35*fit_conf + 0.35*bound_conf + 0.30*identifiability_conf`

Banding:
- `low`: < 0.40
- `medium`: 0.40–0.65
- `high`: 0.65–0.85
- `very_high`: > 0.85

### Results

All 8 clusters are currently in the **medium** certainty band:

| Cluster | fit_conf | bound_conf | identifiability_conf | certainty_overall | band |
|---------|----------|------------|-----------------------|-------------------|------|
| F-vent_C0 | 1.00 | 0.306 | 0.373 | 0.569 | medium |
| F-vent_C1 | 0.95 | 0.288 | 0.373 | 0.545 | medium |
| FTX-vent_C0 | 1.00 | 0.297 | 0.430 | 0.583 | medium |
| FTX-vent_C1 | 0.95 | 0.315 | 0.429 | 0.571 | medium |
| Renovated_C0 | 0.90 | 0.252 | 0.402 | 0.524 | medium |
| Renovated_C1 | 1.00 | 0.255 | 0.429 | 0.568 | medium |
| S-vent_C0 | 0.90 | 0.421 | 0.324 | 0.559 | medium |
| S-vent_C1 | 0.95 | 0.216 | 0.373 | 0.520 | medium |

Mean `certainty_overall`: **0.555**.

### Interpretation

The model is highly confident about **matching EP** (high `fit_conf`) but only moderately confident about the **exact decomposition of envelope/system parameters** (`bound_conf` and `identifiability_conf`). This is expected for archetype calibration from aggregate EPC data, where multiple physical configurations can produce similar annual EP.

For reporting and downstream scenario analysis, Step 14 calibrated values should therefore be treated as **plausible parameter sets** rather than exact as-built specifications.

---
