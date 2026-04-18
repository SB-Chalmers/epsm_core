"""
Step 3 (revised) — Hierarchical clustering of 1960s Uddevalla MFH.

Lessons from Steps 5-7 showed that flat K-means treats ventilation as
one of many features, producing ventilation-heterogeneous clusters with
bimodal simulation error.  The revised approach:

  1. **Pre-classify** by ventilation system (S / F / FT / FTX)
     and renovation status (renovated → separate group)
  2. **Within each group**, K-means on geometry + footprint features
     that SHAP identified as important for EP variation

Clustering features (informed by Step 2 SHAP):
  - fp_area         (footprint area, m²)
  - fp_perimeter    (footprint perimeter, m)
  - fp_compactness  (4πA/P², shape regularity)
  - fp_slenderness  (P / 2√(πA), elongation)
  - floors          (number of above-ground floors)
  - atemp           (heated floor area from EPC)
  - derived_volume  (fp_area × floors × 3.0m)
  - atemp_per_apt   (apartment size proxy)
  - n_footprints    (number of footprint polygons)

Outputs:
  - Cluster assignments per ventilation group
  - PCA scatter plots per group
  - Combined cluster profile table
  - Fjällvägen 28 assignment
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from pathlib import Path

EDA_DIR = Path(__file__).resolve().parent
DATA_PATH = EDA_DIR / "uddevalla_mfh_features.csv"
FIG_DIR = EDA_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)

# Fjällvägen 28 / ÄGIR 17
FJALLVAGEN_FORMULAR_ID = 1033661

# Features to cluster on — geometry + size only (NOT ventilation, NOT EP)
CLUSTER_FEATURES = [
    "fp_area",
    "fp_perimeter",
    "fp_compactness",
    "fp_slenderness",
    "floors",
    "atemp",
    "derived_volume",
    "atemp_per_apt",
    "n_footprints",
]


def _elbow_and_cluster(df_group, group_name, features, k_range=range(2, 9)):
    """Run elbow analysis and K-means for a ventilation/renovation group."""
    df_work = df_group.dropna(subset=features).copy()
    if len(df_work) < 10:
        print(f"  {group_name}: only {len(df_work)} buildings, skipping clustering")
        df_work["cluster"] = 0
        return df_work, 1

    X = df_work[features].values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Clamp k_range to data size
    max_k = min(max(k_range), len(df_work) - 1)
    k_range = range(2, max_k + 1)

    inertias = []
    silhouettes = []
    for k in k_range:
        km = KMeans(n_clusters=k, n_init=20, random_state=42)
        labels = km.fit_predict(X_scaled)
        inertias.append(km.inertia_)
        silhouettes.append(silhouette_score(X_scaled, labels))

    # Pick k with best silhouette
    best_idx = np.argmax(silhouettes)
    best_k = list(k_range)[best_idx]

    print(f"  {group_name} (n={len(df_work)}): best k={best_k} "
          f"(silhouette={silhouettes[best_idx]:.3f})")

    # ── Elbow + silhouette plot ─────────────────────────────────────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))
    ax1.plot(list(k_range), inertias, "bo-", linewidth=2, markersize=6)
    ax1.axvline(best_k, color="red", linestyle="--", alpha=0.7)
    ax1.set_xlabel("k")
    ax1.set_ylabel("Inertia")
    ax1.set_title(f"{group_name} — Elbow")
    ax1.grid(True, alpha=0.3)

    ax2.plot(list(k_range), silhouettes, "rs-", linewidth=2, markersize=6)
    ax2.axvline(best_k, color="red", linestyle="--", alpha=0.7)
    ax2.set_xlabel("k")
    ax2.set_ylabel("Silhouette")
    ax2.set_title(f"{group_name} — Silhouette")
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    safe_name = group_name.replace(" ", "_").replace("/", "_")
    fig.savefig(FIG_DIR / f"clustering_elbow_{safe_name}.png", dpi=150)
    plt.close()

    # ── Final clustering with best_k ────────────────────────────────
    km = KMeans(n_clusters=best_k, n_init=30, random_state=42)
    df_work["cluster"] = km.fit_predict(X_scaled)

    # ── PCA scatter ─────────────────────────────────────────────────
    if X_scaled.shape[1] >= 2:
        pca = PCA(n_components=2)
        X_pca = pca.fit_transform(X_scaled)

        fig, axes = plt.subplots(1, 2, figsize=(14, 5))

        scatter = axes[0].scatter(
            X_pca[:, 0], X_pca[:, 1],
            c=df_work["cluster"].values,
            cmap="tab10", alpha=0.6, s=30, edgecolors="k", linewidths=0.3,
        )
        axes[0].set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0]*100:.0f}%)")
        axes[0].set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1]*100:.0f}%)")
        axes[0].set_title(f"{group_name} — k={best_k} clusters")
        plt.colorbar(scatter, ax=axes[0], label="Cluster")

        # Mark Fjällvägen 28
        fjv_mask = df_work["FormularId"] == FJALLVAGEN_FORMULAR_ID
        if fjv_mask.any():
            idx = df_work.index.get_indexer(df_work.loc[fjv_mask].index)
            axes[0].scatter(X_pca[idx, 0], X_pca[idx, 1], c="red", s=200,
                           marker="*", zorder=5, label="Fjällvägen 28",
                           edgecolors="k")
            axes[0].legend()

        # Color by EP
        scatter2 = axes[1].scatter(
            X_pca[:, 0], X_pca[:, 1],
            c=df_work["ep"].values,
            cmap="RdYlGn_r", alpha=0.6, s=30, edgecolors="k", linewidths=0.3,
        )
        axes[1].set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0]*100:.0f}%)")
        axes[1].set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1]*100:.0f}%)")
        axes[1].set_title(f"{group_name} — EP (kWh/m²)")
        plt.colorbar(scatter2, ax=axes[1], label="EP")

        plt.suptitle(f"{group_name} (n={len(df_work)})", fontsize=13)
        plt.tight_layout()
        fig.savefig(FIG_DIR / f"clustering_pca_{safe_name}.png", dpi=150)
        plt.close()

    # ── Cluster profiles ────────────────────────────────────────────
    profile_cols = features + ["ep", "byggar"]
    available = [c for c in profile_cols if c in df_work.columns]
    summary = df_work.groupby("cluster")[available].agg(["mean", "count"])
    print(f"\n  Cluster profiles for {group_name}:")
    for c in range(best_k):
        sub = df_work[df_work["cluster"] == c]
        print(f"    Cluster {c} (n={len(sub)}): "
              f"EP={sub['ep'].mean():.0f}, "
              f"Atemp={sub['atemp'].mean():.0f}, "
              f"floors={sub['floors'].mean():.1f}, "
              f"fp_area={sub['fp_area'].mean():.0f} m², "
              f"compactness={sub['fp_compactness'].mean():.2f}")

    return df_work, best_k


def run():
    df = pd.read_csv(DATA_PATH)

    # ── Filter to CMF_1960 range (1955-1975) ────────────────────────────
    df_60s = df[(df["byggar"] >= 1955) & (df["byggar"] <= 1975)].copy()
    print(f"Buildings in CMF_1960 range (1955-1975): {len(df_60s)}")

    # ── Step 1: Pre-classify by renovation + ventilation ────────────────
    # Renovated buildings → separate group (regardless of vent system)
    # Then split unrenovated by ventilation system

    df_60s["group"] = "Other"
    df_60s.loc[df_60s["renovated"] == 1, "group"] = "Renovated"
    df_60s.loc[(df_60s["renovated"] == 0) & (df_60s["ventilation"] == "S"), "group"] = "S-vent"
    df_60s.loc[(df_60s["renovated"] == 0) & (df_60s["ventilation"] == "F"), "group"] = "F-vent"
    df_60s.loc[(df_60s["renovated"] == 0) & (df_60s["ventilation"] == "FT"), "group"] = "FT-vent"
    df_60s.loc[(df_60s["renovated"] == 0) & (df_60s["ventilation"] == "FTX"), "group"] = "FTX-vent"
    df_60s.loc[(df_60s["renovated"] == 0) & (df_60s["ventilation"] == "Unknown"), "group"] = "F-vent"  # default

    print(f"\nPre-classification:")
    print(df_60s["group"].value_counts().to_string())

    # ── Step 2: K-means within each group ───────────────────────────────
    results = []

    for group_name in ["S-vent", "F-vent", "FTX-vent", "FT-vent", "Renovated"]:
        df_group = df_60s[df_60s["group"] == group_name].copy()
        if len(df_group) == 0:
            continue

        print(f"\n{'='*60}")
        print(f"  GROUP: {group_name} (n={len(df_group)})")
        print(f"{'='*60}")

        df_clustered, best_k = _elbow_and_cluster(
            df_group, group_name, CLUSTER_FEATURES
        )
        # Create global cluster label: e.g. "S-vent_C0", "F-vent_C1"
        df_clustered["global_cluster"] = (
            group_name + "_C" + df_clustered["cluster"].astype(str)
        )
        results.append(df_clustered)

    # ── Combine all groups ──────────────────────────────────────────────
    df_all = pd.concat(results, ignore_index=True)

    # ── Fjällvägen 28 ──────────────────────────────────────────────────
    fjv_mask = df_all["FormularId"] == FJALLVAGEN_FORMULAR_ID
    if fjv_mask.any():
        fjv = df_all.loc[fjv_mask].iloc[0]
        print(f"\n{'='*60}")
        print(f"  ★ FJÄLLVÄGEN 28 (FormularId={FJALLVAGEN_FORMULAR_ID})")
        print(f"    Group:   {fjv['group']}")
        print(f"    Cluster: {fjv['global_cluster']}")
        print(f"    EP={fjv['ep']}, Atemp={fjv['atemp']}, floors={fjv['floors']}")
        print(f"    fp_area={fjv['fp_area']:.0f} m², compactness={fjv['fp_compactness']:.2f}")
        print(f"{'='*60}")

    # ── Global summary table ────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  GLOBAL CLUSTER SUMMARY")
    print(f"{'='*60}")
    summary = df_all.groupby("global_cluster").agg(
        n=("FormularId", "count"),
        avg_ep=("ep", "mean"),
        std_ep=("ep", "std"),
        avg_atemp=("atemp", "mean"),
        avg_floors=("floors", "mean"),
        avg_fp_area=("fp_area", "mean"),
        avg_compactness=("fp_compactness", "mean"),
        avg_slenderness=("fp_slenderness", "mean"),
        avg_atemp_per_apt=("atemp_per_apt", "mean"),
    ).round(1)
    print(summary.to_string())

    # ── Feature heatmap (all clusters) ──────────────────────────────────
    heatmap_cols = ["atemp", "floors", "fp_area", "fp_compactness",
                    "atemp_per_apt", "ep", "n_footprints"]
    available_hm = [c for c in heatmap_cols if c in df_all.columns]
    cluster_means = df_all.groupby("global_cluster")[available_hm].mean()
    cluster_z = (cluster_means - cluster_means.mean()) / cluster_means.std()

    fig, ax = plt.subplots(figsize=(12, max(4, len(cluster_means) * 0.6)))
    sns.heatmap(cluster_z.T, annot=cluster_means.T.round(1).values, fmt="",
                cmap="RdBu_r", center=0, ax=ax, linewidths=0.5)
    ax.set_xlabel("Cluster")
    ax.set_ylabel("Feature")
    ax.set_title("Hierarchical Cluster Profiles — values = means, color = z-score")
    plt.tight_layout()
    fig.savefig(FIG_DIR / "clustering_heatmap_hierarchical.png", dpi=150)
    plt.close()
    print(f"  → Saved clustering_heatmap_hierarchical.png")

    # ── EP boxplot by global cluster ────────────────────────────────────
    fig, ax = plt.subplots(figsize=(max(10, len(summary) * 1.2), 6))
    order = sorted(df_all["global_cluster"].unique())
    df_all.boxplot(column="ep", by="global_cluster", ax=ax, grid=False,
                   positions=range(len(order)))
    ax.set_xticklabels(order, rotation=45, ha="right")
    ax.set_xlabel("Cluster")
    ax.set_ylabel("EP (kWh/m²)")
    ax.set_title("EP Distribution by Hierarchical Cluster")
    plt.suptitle("")
    plt.tight_layout()
    fig.savefig(FIG_DIR / "clustering_ep_boxplot_hierarchical.png", dpi=150)
    plt.close()
    print(f"  → Saved clustering_ep_boxplot_hierarchical.png")

    # ── Save assignments ────────────────────────────────────────────────
    out_cols = ["FormularId", "IdFastBet", "IdAdr", "group", "cluster",
                "global_cluster", "ep", "atemp", "floors", "apartments",
                "ventilation", "renovated", "fp_area", "fp_perimeter",
                "fp_compactness", "fp_slenderness", "n_footprints",
                "derived_volume", "derived_atemp", "atemp_per_apt"]
    available_out = [c for c in out_cols if c in df_all.columns]
    df_all[available_out].to_csv(
        EDA_DIR / "clusters_1960s_hierarchical.csv", index=False
    )
    print(f"  → Saved clusters_1960s_hierarchical.csv")

    return df_all


if __name__ == "__main__":
    run()
