"""
Step 2 (revised) — Full Random Forest sensitivity analysis.

Trains a Random Forest on ALL Uddevalla MFH data (no train/test split)
to *explain* which features drive EP variation. This is a sensitivity
analysis, not a predictive model — we want feature importances computed
on the full population.

Cross-validation R² is reported for generalisability reference but is
NOT used for feature selection.

Now includes footprint-derived geometry features:
  fp_area, fp_perimeter, fp_compactness, fp_slenderness,
  derived_volume, derived_atemp, n_footprints

Outputs:
  - MDI importance ranking
  - Permutation importance (full data)
  - SHAP bar + beeswarm + dependence plots
  - feature_importances.csv
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import shap
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import cross_val_score
from sklearn.inspection import permutation_importance
from sklearn.metrics import r2_score, mean_absolute_error
from pathlib import Path

EDA_DIR = Path(__file__).resolve().parent
DATA_PATH = EDA_DIR / "uddevalla_mfh_features.csv"
FIG_DIR = EDA_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)


def run():
    df = pd.read_csv(DATA_PATH)
    print(f"Loaded {len(df)} records, {df.shape[1]} columns")

    # ── Select features for RF ──────────────────────────────────────────
    # EPC-recorded features + footprint-derived geometry.
    # Exclude identifiers, raw energy breakdowns that are part of EP,
    # and derived ratios that are circular with the target.

    numeric_features = [
        "byggar",             # construction year
        "atemp",              # heated floor area (from EPC)
        "floors",             # number of floors
        "basement_floors",    # basement floors
        "apartments",         # number of apartments
        "garage_area",        # heated garage area (m²)
        "residential_pct",    # % Atemp residential
        "atemp_per_apt",      # Atemp per apartment
        "garage_pct",         # garage share of Atemp
        # Footprint geometry
        "fp_area",            # total footprint area (m²)
        "fp_perimeter",       # total perimeter (m)
        "fp_compactness",     # 4πA/P² (circularity)
        "fp_slenderness",     # P / (2√(πA))
        "n_footprints",       # number of footprint polygons
        "derived_volume",     # fp_area × floors × 3.0m
        "derived_atemp",      # fp_area × floors × 0.85
    ]

    # Renovation flags (binary)
    reno_features = [
        "reno_roof", "reno_wall", "reno_ground",
        "reno_window_replace", "reno_window_add", "reno_window_seal",
        "reno_vent_replace", "reno_heat_recovery",
        "reno_heating_adjust", "reno_heat_pump",
        "reno_envelope", "reno_ventilation", "renovated",
    ]

    # Categorical → one-hot
    cat_features = ["ventilation", "heating_system"]

    # Build feature matrix
    X = df[numeric_features + reno_features].copy()

    # One-hot encode categoricals
    for cat in cat_features:
        dummies = pd.get_dummies(df[cat], prefix=cat, drop_first=False)
        X = pd.concat([X, dummies], axis=1)

    y = df["ep"].copy()

    # Drop rows with NaN in features or target
    mask = X.notna().all(axis=1) & y.notna()
    X = X.loc[mask].reset_index(drop=True)
    y = y.loc[mask].reset_index(drop=True)
    print(f"After dropping NaNs: {len(X)} records, {X.shape[1]} features")
    print(f"Features: {list(X.columns)}")

    # ── Cross-validation (generalisation reference, NOT for feature selection)
    cv_scores = cross_val_score(
        RandomForestRegressor(n_estimators=500, min_samples_leaf=5,
                              random_state=42, n_jobs=-1),
        X, y, cv=5, scoring="r2",
    )
    print(f"\n  5-fold CV R²: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")

    # ── Train on ALL data (explanatory, not predictive) ─────────────────
    rf = RandomForestRegressor(
        n_estimators=500,
        max_depth=None,
        min_samples_leaf=5,
        random_state=42,
        n_jobs=-1,
    )
    rf.fit(X, y)

    # In-sample R² (for reference — NOT a performance claim)
    y_pred = rf.predict(X)
    r2 = r2_score(y, y_pred)
    mae = mean_absolute_error(y, y_pred)
    print(f"\n{'='*50}")
    print(f"Full-data RF (explanatory, in-sample)")
    print(f"  R²  = {r2:.3f}")
    print(f"  MAE = {mae:.1f} kWh/m²")
    print(f"{'='*50}")

    # ── Feature Importance (MDI) ────────────────────────────────────────
    importances = pd.Series(rf.feature_importances_, index=X.columns)
    importances = importances.sort_values(ascending=False)

    print(f"\n{'='*50}")
    print("Mean Decrease Impurity (MDI) — Top 20")
    print(f"{'='*50}")
    for feat, imp in importances.head(20).items():
        print(f"  {feat:35s} {imp:.4f}")

    # Plot MDI
    fig, ax = plt.subplots(figsize=(10, 8))
    importances.head(20).sort_values().plot.barh(ax=ax, color="steelblue")
    ax.set_xlabel("Mean Decrease Impurity")
    ax.set_title("RF Feature Importance (MDI) — Full data, Uddevalla MFH → EP")
    plt.tight_layout()
    fig.savefig(FIG_DIR / "rf_importance_mdi.png", dpi=150)
    plt.close()
    print(f"  → Saved rf_importance_mdi.png")

    # ── Permutation Importance (on full data) ───────────────────────────
    perm = permutation_importance(rf, X, y, n_repeats=20,
                                  random_state=42, n_jobs=-1)
    perm_imp = pd.Series(perm.importances_mean, index=X.columns).sort_values(ascending=False)

    print(f"\n{'='*50}")
    print("Permutation Importance — Top 20")
    print(f"{'='*50}")
    for feat, imp in perm_imp.head(20).items():
        print(f"  {feat:35s} {imp:.4f}")

    # Plot
    fig, ax = plt.subplots(figsize=(10, 8))
    top_perm = perm_imp.head(20)
    perm_std = pd.Series(perm.importances_std, index=X.columns)[top_perm.index]
    top_perm.sort_values().plot.barh(
        ax=ax, xerr=perm_std[top_perm.sort_values().index].values,
        color="darkorange",
    )
    ax.set_xlabel("Mean R² decrease")
    ax.set_title("Permutation Importance — Full data, Uddevalla MFH → EP")
    plt.tight_layout()
    fig.savefig(FIG_DIR / "rf_importance_permutation.png", dpi=150)
    plt.close()
    print(f"  → Saved rf_importance_permutation.png")

    # ── SHAP Values ─────────────────────────────────────────────────────
    print("\nComputing SHAP values (TreeExplainer)...")
    explainer = shap.TreeExplainer(rf)

    # Subsample for SHAP if dataset is large (faster)
    if len(X) > 2000:
        X_shap = X.sample(n=2000, random_state=42)
    else:
        X_shap = X
    shap_values = explainer.shap_values(X_shap)

    # SHAP bar plot (mean |SHAP|)
    fig, ax = plt.subplots(figsize=(10, 8))
    shap.summary_plot(shap_values, X_shap, plot_type="bar", show=False, max_display=20)
    plt.title("SHAP Feature Importance (mean |SHAP value|)")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "shap_bar.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  → Saved shap_bar.png")

    # SHAP beeswarm plot
    fig, ax = plt.subplots(figsize=(12, 10))
    shap.summary_plot(shap_values, X_shap, show=False, max_display=20)
    plt.title("SHAP Beeswarm — Feature impact on EP (kWh/m²)")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "shap_beeswarm.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  → Saved shap_beeswarm.png")

    # SHAP dependence plots for top 6 features
    top_features = importances.head(6).index.tolist()
    for feat in top_features:
        fig, ax = plt.subplots(figsize=(8, 5))
        shap.dependence_plot(feat, shap_values, X_shap, show=False, ax=ax)
        ax.set_title(f"SHAP Dependence — {feat}")
        plt.tight_layout()
        fname = f"shap_dep_{feat.replace('/', '_')}.png"
        fig.savefig(FIG_DIR / fname, dpi=150)
        plt.close()
        print(f"  → Saved {FIG_DIR / fname}")

    # ── Save importance tables ──────────────────────────────────────────
    # Build SHAP column index mapping against X_shap columns
    shap_mean_abs = np.abs(shap_values).mean(axis=0)
    shap_lookup = dict(zip(X_shap.columns, shap_mean_abs))

    imp_df = pd.DataFrame({
        "feature": importances.index,
        "mdi_importance": importances.values,
        "permutation_importance": perm_imp.reindex(importances.index).values,
        "mean_abs_shap": [shap_lookup.get(f, np.nan) for f in importances.index],
    })
    imp_df.to_csv(EDA_DIR / "feature_importances.csv", index=False)
    print(f"\n  → Saved feature_importances.csv")

    return rf, importances, perm_imp


if __name__ == "__main__":
    run()
