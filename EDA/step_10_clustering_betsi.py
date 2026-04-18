"""
Step 10 — Revised clustering with BETSI archetype mapping.

Key changes from Step 3 (hierarchical clustering):
  1. Merge FT-vent into F-vent (both mechanical exhaust, no heat recovery)
  2. Enforce minimum cluster size ≥ 5 unique buildings per cluster
  3. Assign each cluster a BETSI construction template by morphology
    4. Include Dahlström et al. (2024) archetype identification
    5. Use a divergence-aware cluster quality score when selecting k

Groups (4):
  S-vent:    Unrenovated, natural draft (självdrag)
  F-vent:    Unrenovated, mechanical exhaust (F + FT + Unknown, no HR)
  FTX-vent:  Unrenovated, supply + exhaust with heat recovery
  Renovated: Any renovation measure performed

BETSI template mapping (Uddevalla miljonprogram 1955-1975):
  ≤ 4 floors            → BETSI_CONC_SLAB  (lamellhus, wall U=0.25)
  5-6 floors            → BETSI_CONC_TOWER (skivhus,   wall U=0.20)
  ≥ 7 floors, compact   → BETSI_CONC_POINT (punkthus,  wall U=0.19)
  ≥ 7 floors, elongated → BETSI_CONC_TOWER

Outputs:
  clusters_betsi.csv          — all building rows with cluster + BETSI template
  archetypes_betsi.csv        — one row per cluster: archetype + quality metrics
  figures/clustering_*_betsi.png
"""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
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

FJALLVAGEN_FORMULAR_ID = 1033661

# Geometry-only clustering features (EP excluded — it's the outcome variable)
CLUSTER_FEATURES = [
    "fp_area", "fp_perimeter", "fp_compactness", "fp_slenderness",
    "floors", "atemp", "derived_volume", "atemp_per_apt", "n_footprints",
]

MIN_CLUSTER_SIZE = 5  # minimum unique FormularIds per cluster

# BETSI template reference U-values (from build_betsi_archetypes.py)
BETSI_TEMPLATES = {
    "BETSI_CONC_SLAB": {
        "wall": 0.25, "roof": 0.15, "floor": 0.27, "window": 2.00,
        "display": "Concrete slab block (1960-75)",
    },
    "BETSI_CONC_TOWER": {
        "wall": 0.20, "roof": 0.14, "floor": 0.22, "window": 1.90,
        "display": "Concrete tower slab (1960-75)",
    },
    "BETSI_CONC_POINT": {
        "wall": 0.19, "roof": 0.15, "floor": 0.36, "window": 1.90,
        "display": "Concrete point block (1960-75)",
    },
}


# ═══════════════════════════════════════════════════════════════════
# BETSI TEMPLATE ASSIGNMENT
# ═══════════════════════════════════════════════════════════════════

def assign_betsi_template(avg_floors, avg_compactness):
    """Map cluster average morphology to best BETSI construction template.

    Rules based on Uddevalla miljonprogram building stock:
      ≤ 4 floors              → BETSI_CONC_SLAB  (lamellhus / low-rise slab)
      5-6 floors              → BETSI_CONC_TOWER (skivhus / mid-rise tower)
      ≥ 7 floors, compact     → BETSI_CONC_POINT (punkthus)
      ≥ 7 floors, elongated   → BETSI_CONC_TOWER (skivhus)
    """
    if avg_floors >= 7:
        return "BETSI_CONC_POINT" if avg_compactness >= 0.40 else "BETSI_CONC_TOWER"
    elif avg_floors >= 5:
        return "BETSI_CONC_TOWER"
    else:
        return "BETSI_CONC_SLAB"


# ═══════════════════════════════════════════════════════════════════
# CLUSTERING HELPERS
# ═══════════════════════════════════════════════════════════════════

def _merge_small_clusters(labels, X_scaled, min_size):
    """Merge clusters smaller than min_size into their nearest neighbour."""
    labels = labels.copy()

    while True:
        unique_labels, counts = np.unique(labels, return_counts=True)
        small_mask = counts < min_size
        if not small_mask.any():
            break
        if small_mask.all():
            labels[:] = 0
            break

        small_labels = unique_labels[small_mask]
        small_counts = counts[small_mask]
        smallest = small_labels[small_counts.argmin()]

        other_labels = unique_labels[~small_mask]
        centroids = {lab: X_scaled[labels == lab].mean(axis=0)
                     for lab in other_labels}
        centroid_small = X_scaled[labels == smallest].mean(axis=0)

        nearest = min(centroids,
                      key=lambda l: np.linalg.norm(centroids[l] - centroid_small))

        n_small = int(counts[unique_labels == smallest][0])
        print(f"      Merging C{smallest} (n={n_small}) → C{nearest}")
        labels[labels == smallest] = nearest

    # Relabel to 0, 1, 2, ...
    unique_final = sorted(np.unique(labels))
    remap = {old: new for new, old in enumerate(unique_final)}
    labels = np.array([remap[l] for l in labels])
    return labels


def _separation_ratio(X_scaled, labels):
    """Return between-centroid separation divided by within-cluster spread."""
    unique_labels = sorted(np.unique(labels))
    if len(unique_labels) <= 1:
        return 0.0

    centroids = []
    within_vals = []
    for lab in unique_labels:
        pts = X_scaled[labels == lab]
        c = pts.mean(axis=0)
        centroids.append(c)
        d = np.linalg.norm(pts - c, axis=1)
        within_vals.append(float(d.mean()) if len(d) else 0.0)

    within = float(np.mean(within_vals))
    if within <= 1e-12:
        return 0.0

    centroids = np.vstack(centroids)
    pairwise = []
    for i in range(len(centroids)):
        for j in range(i + 1, len(centroids)):
            pairwise.append(float(np.linalg.norm(centroids[i] - centroids[j])))

    if not pairwise:
        return 0.0
    between = float(np.mean(pairwise))
    return between / within


def _cluster_unique(df_unique, group_name, features, min_size=MIN_CLUSTER_SIZE):
    """Cluster unique buildings with min-size enforcement.

    *df_unique* must already be deduplicated (one row per FormularId)
    and free of NaN in *features*.
    """
    n = len(df_unique)
    print(f"\n  {group_name}: {n} unique buildings")

    if n < min_size * 2:
        print(f"    → Too few for sub-clustering, single cluster")
        df_unique = df_unique.copy()
        df_unique["cluster"] = 0
        return df_unique, 1

    X = df_unique[features].values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    max_k = min(8, n // min_size)
    max_k = max(max_k, 2)
    k_range = range(2, max_k + 1)

    inertias, silhouettes = [], []
    candidates = []
    for k in k_range:
        km = KMeans(n_clusters=k, n_init=20, random_state=42)
        labs = km.fit_predict(X_scaled)
        inertias.append(km.inertia_)
        silhouettes.append(silhouette_score(X_scaled, labs))

    # Final selection uses silhouette + divergence-aware separation ratio.
    # This avoids selecting k values that look good by silhouette but produce
    # weakly separated archetype centroids.
    for try_k in k_range:
        km = KMeans(n_clusters=try_k, n_init=30, random_state=42)
        merged = _merge_small_clusters(km.fit_predict(X_scaled), X_scaled, min_size)
        n_clusters = len(np.unique(merged))
        sil = silhouette_score(X_scaled, merged) if n_clusters > 1 else -1.0
        sep_ratio = _separation_ratio(X_scaled, merged)
        quality = 0.7 * sil + 0.3 * np.tanh(sep_ratio / 2.0)
        candidates.append({
            "k_input": int(try_k),
            "k_final": int(n_clusters),
            "silhouette": float(sil),
            "sep_ratio": float(sep_ratio),
            "quality": float(quality),
            "labels": merged,
        })

    if not candidates:
        final_labels = np.zeros(n, dtype=int)
        best_k = 1
        print("    No valid clustering candidates; single cluster")
    else:
        best = max(candidates, key=lambda c: c["quality"])
        final_labels = best["labels"]
        best_k = best["k_final"]
        print(
            "    Selected "
            f"k_input={best['k_input']} -> k_final={best['k_final']} "
            f"(sil={best['silhouette']:.3f}, sep={best['sep_ratio']:.3f}, "
            f"quality={best['quality']:.3f})"
        )

    df_unique = df_unique.copy()
    df_unique["cluster"] = final_labels

    # ── Elbow + silhouette plot ────────────────────────────────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))
    ax1.plot(list(k_range), inertias, "bo-", lw=2, ms=6)
    ax1.axvline(best_k, color="red", ls="--", alpha=0.7)
    ax1.set(xlabel="k", ylabel="Inertia",
            title=f"{group_name} — Elbow")
    ax1.grid(True, alpha=0.3)

    ax2.plot(list(k_range), silhouettes, "rs-", lw=2, ms=6)
    ax2.axvline(best_k, color="red", ls="--", alpha=0.7)
    ax2.set(xlabel="k", ylabel="Silhouette",
            title=f"{group_name} — Silhouette")
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    safe = group_name.replace(" ", "_")
    fig.savefig(FIG_DIR / f"clustering_elbow_{safe}_betsi.png", dpi=150)
    plt.close()

    # ── PCA scatter ────────────────────────────────────────────
    if X_scaled.shape[1] >= 2:
        pca = PCA(n_components=2)
        X_pca = pca.fit_transform(X_scaled)

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

        scatter = ax1.scatter(
            X_pca[:, 0], X_pca[:, 1], c=final_labels,
            cmap="tab10", alpha=0.6, s=40,
            edgecolors="k", linewidths=0.3,
        )
        ax1.set(
            xlabel=f"PC1 ({pca.explained_variance_ratio_[0]*100:.0f}%)",
            ylabel=f"PC2 ({pca.explained_variance_ratio_[1]*100:.0f}%)",
            title=f"{group_name} — Clusters (k={best_k})",
        )
        plt.colorbar(scatter, ax=ax1, label="Cluster")

        # Mark Fjällvägen 28
        fjv_mask = df_unique["FormularId"] == FJALLVAGEN_FORMULAR_ID
        if fjv_mask.any():
            fjv_idx = df_unique.index.get_loc(
                df_unique.loc[fjv_mask].index[0])
            ax1.scatter(
                X_pca[fjv_idx, 0], X_pca[fjv_idx, 1], c="red", s=200,
                marker="*", zorder=5, label="Fjällvägen 28",
                edgecolors="k",
            )
            ax1.legend()

        sc2 = ax2.scatter(
            X_pca[:, 0], X_pca[:, 1],
            c=df_unique["ep"].values, cmap="RdYlGn_r",
            alpha=0.6, s=40, edgecolors="k", linewidths=0.3,
        )
        ax2.set(
            xlabel=f"PC1 ({pca.explained_variance_ratio_[0]*100:.0f}%)",
            ylabel=f"PC2 ({pca.explained_variance_ratio_[1]*100:.0f}%)",
            title=f"{group_name} — EP (kWh/m²)",
        )
        plt.colorbar(sc2, ax=ax2, label="EP")

        plt.suptitle(f"{group_name} (n={n})", fontsize=13)
        plt.tight_layout()
        safe = group_name.replace(" ", "_")
        fig.savefig(FIG_DIR / f"clustering_pca_{safe}_betsi.png", dpi=150)
        plt.close()

    # Cluster profiles
    for c in sorted(df_unique["cluster"].unique()):
        sub = df_unique[df_unique["cluster"] == c]
        template = assign_betsi_template(
            sub["floors"].mean(), sub["fp_compactness"].mean())
        print(f"    C{c} (n={len(sub)}): "
              f"EP={sub['ep'].mean():.0f}, "
              f"Atemp={sub['atemp'].mean():.0f}, "
              f"floors={sub['floors'].mean():.1f}, "
              f"fp_area={sub['fp_area'].mean():.0f}, "
              f"compact={sub['fp_compactness'].mean():.2f} "
              f"→ {template}")

    return df_unique, best_k


# ═══════════════════════════════════════════════════════════════════
# ARCHETYPE IDENTIFICATION (Dahlström et al. 2024)
# ═══════════════════════════════════════════════════════════════════

def identify_archetypes(df):
    """For each cluster, find the building closest to the centroid."""
    results = []

    unique_all = df.drop_duplicates(subset="FormularId").copy().reset_index(drop=True)
    feat_all = unique_all[CLUSTER_FEATURES].values
    scaler_all = StandardScaler()
    feat_all_std = scaler_all.fit_transform(feat_all)

    centroid_map = {}
    for cluster_name, group in unique_all.groupby("global_cluster"):
        idx = group.index.values
        centroid_map[cluster_name] = feat_all_std[idx].mean(axis=0)

    centroid_names = list(centroid_map.keys())
    max_centroid_dist = 1e-12
    if len(centroid_names) > 1:
        dvals = []
        for i in range(len(centroid_names)):
            for j in range(i + 1, len(centroid_names)):
                a = centroid_map[centroid_names[i]]
                b = centroid_map[centroid_names[j]]
                dvals.append(float(np.linalg.norm(a - b)))
        if dvals:
            max_centroid_dist = max(dvals)

    for cluster_name, group in unique_all.groupby("global_cluster"):
        unique = group
        feat = unique[CLUSTER_FEATURES].values
        feat_std = feat_all_std[unique.index.values]

        if len(unique) <= 1:
            arch = unique.iloc[0].copy()
            arch["dist_to_centroid"] = 0.0
            arch["cluster_size"] = len(unique)
            arch["representativeness"] = 100.0
            arch["cluster_spread"] = 0.0
            arch["distinctness"] = 100.0
            arch["divergence"] = 100.0
            arch["rep_div_score"] = 100.0
        else:
            centroid = feat_std.mean(axis=0)
            dists = np.sqrt(((feat_std - centroid) ** 2).sum(axis=1))
            idx = int(dists.argmin())

            arch = unique.iloc[idx].copy()
            arch["dist_to_centroid"] = dists[idx]
            arch["cluster_size"] = len(unique)

            # Representativeness (Eq. 7)
            feat_norm = ((feat - feat.min(0))
                         / (feat.max(0) - feat.min(0) + 1e-12))
            centroid_norm = feat_norm.mean(0)
            arch_norm = feat_norm[idx]
            R_i = np.mean(1 - np.abs(centroid_norm - arch_norm)) * 100
            arch["representativeness"] = round(R_i, 1)

            # Cluster spread (Eq. 10)
            S_tot = np.mean(feat_norm.std(0)) * 100
            arch["cluster_spread"] = round(S_tot, 1)

            # Distinctness (Eq. 11)
            D_i = 0.5 * (R_i / 100) + 0.5 * (1 - S_tot / 100)
            arch["distinctness"] = round(D_i * 100, 1)

            # Divergence: nearest-centroid distance vs all-cluster max.
            other = [c for c in centroid_names if c != cluster_name]
            if other:
                nearest = min(
                    float(np.linalg.norm(centroid_map[cluster_name] - centroid_map[c]))
                    for c in other
                )
                div = (nearest / max_centroid_dist) * 100
            else:
                div = 100.0
            arch["divergence"] = round(div, 1)
            arch["rep_div_score"] = round(
                0.5 * arch["distinctness"] + 0.5 * arch["divergence"], 1
            )

        results.append(arch)

    return pd.DataFrame(results)


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def run():
    df = pd.read_csv(DATA_PATH)

    # ── Filter to CMF_1960 era (1955-1975) ─────────────────────────
    df_60s = df[(df["byggar"] >= 1955) & (df["byggar"] <= 1975)].copy()
    print(f"Buildings in CMF_1960 range (1955-1975): {len(df_60s)}")

    # ── Deduplicate to unique buildings FIRST ──────────────────────
    # Some FormularIds have mixed renovated flags across address rows;
    # resolve at building level before pre-classification.
    bldg_reno = df_60s.groupby("FormularId")["renovated"].max()
    bldg_vent = df_60s.groupby("FormularId")["ventilation"].first()

    df_bldg = (df_60s
               .drop_duplicates(subset="FormularId")
               .copy()
               .reset_index(drop=True))
    df_bldg["renovated"] = df_bldg["FormularId"].map(bldg_reno)
    df_bldg["ventilation"] = df_bldg["FormularId"].map(bldg_vent)

    # ── Pre-classify: 4 groups (FT merged into F) ──────────────────
    # Priority order: Renovated > FTX > F > S
    df_bldg["group"] = "Other"
    df_bldg.loc[df_bldg["ventilation"] == "S", "group"] = "S-vent"
    df_bldg.loc[
        df_bldg["ventilation"].isin(["F", "FT", "Unknown"]), "group"
    ] = "F-vent"
    df_bldg.loc[
        df_bldg["ventilation"].isin(["FTX", "FVP"]), "group"
    ] = "FTX-vent"
    # Renovation overrides ventilation group
    df_bldg.loc[df_bldg["renovated"] == 1, "group"] = "Renovated"

    df_bldg = df_bldg[df_bldg["group"] != "Other"]

    print(f"\nPre-classification (4 groups, unique buildings):")
    for g in ["S-vent", "F-vent", "FTX-vent", "Renovated"]:
        n = len(df_bldg[df_bldg["group"] == g])
        print(f"  {g:12s}: {n:4d} unique buildings")
    print(f"  {'Total':12s}: {len(df_bldg):4d}")

    # ── Cluster within each group (on unique buildings) ────────────
    clustered_parts = []
    for group_name in ["S-vent", "F-vent", "FTX-vent", "Renovated"]:
        df_group = df_bldg[df_bldg["group"] == group_name].copy()
        if len(df_group) == 0:
            continue

        # Drop rows with NaN in clustering features
        df_group = df_group.dropna(subset=CLUSTER_FEATURES).reset_index(
            drop=True)

        print(f"\n{'='*60}")
        print(f"  GROUP: {group_name}")
        print(f"{'='*60}")

        df_clustered, _ = _cluster_unique(
            df_group, group_name, CLUSTER_FEATURES)
        df_clustered["global_cluster"] = (
            group_name + "_C"
            + df_clustered["cluster"].astype(int).astype(str)
        )
        clustered_parts.append(df_clustered)

    df_clustered_bldgs = pd.concat(clustered_parts, ignore_index=True)

    # ── Assign BETSI templates ─────────────────────────────────────
    cluster_profiles = (
        df_clustered_bldgs
        .groupby("global_cluster")
        .agg(
            n_unique=("FormularId", "nunique"),
            avg_ep=("ep", "mean"),
            std_ep=("ep", "std"),
            avg_atemp=("atemp", "mean"),
            avg_floors=("floors", "mean"),
            avg_fp_area=("fp_area", "mean"),
            avg_compactness=("fp_compactness", "mean"),
            avg_slenderness=("fp_slenderness", "mean"),
            avg_byggar=("byggar", "mean"),
        )
        .round(1)
    )

    cluster_profiles["betsi_template"] = cluster_profiles.apply(
        lambda r: assign_betsi_template(
            r["avg_floors"], r["avg_compactness"]),
        axis=1,
    )

    # Map BETSI template back to clustered buildings
    template_map = cluster_profiles["betsi_template"]
    df_clustered_bldgs["betsi_template"] = (
        df_clustered_bldgs["global_cluster"].map(template_map)
    )

    # ── Map assignments back to ALL address-level rows ─────────────
    mapping_cols = ["FormularId", "group", "cluster", "global_cluster",
                    "betsi_template"]
    mapping = df_clustered_bldgs[mapping_cols].copy()
    df_all = df_60s.merge(mapping, on="FormularId", how="inner")

    # ── Fjällvägen 28 ─────────────────────────────────────────────
    fjv = df_clustered_bldgs[
        df_clustered_bldgs["FormularId"] == FJALLVAGEN_FORMULAR_ID]
    if len(fjv):
        f = fjv.iloc[0]
        print(f"\n{'='*60}")
        print(f"  ★ FJÄLLVÄGEN 28 (FormularId={FJALLVAGEN_FORMULAR_ID})")
        print(f"    Group:    {f['group']}")
        print(f"    Cluster:  {f['global_cluster']}")
        print(f"    BETSI:    {f['betsi_template']}")
        print(f"    EP={f['ep']}, Atemp={f['atemp']}, floors={f['floors']}")
        print(f"    fp_area={f['fp_area']:.0f}, "
              f"compactness={f['fp_compactness']:.2f}")
        print(f"{'='*60}")

    # ── Global summary ─────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"  CLUSTER SUMMARY WITH BETSI MAPPING")
    print(f"{'='*80}")
    print(f"  {'Cluster':<16s} {'n':>4s} {'EP':>5s} {'σ_EP':>5s} "
          f"{'Atemp':>6s} {'Fl':>4s} {'Compact':>8s} {'BETSI Template':>20s}")
    print(f"  {'-'*16} {'-'*4} {'-'*5} {'-'*5} "
          f"{'-'*6} {'-'*4} {'-'*8} {'-'*20}")

    for idx, r in cluster_profiles.iterrows():
        std = r["std_ep"] if pd.notna(r["std_ep"]) else 0
        print(f"  {idx:<16s} {r['n_unique']:4.0f} "
              f"{r['avg_ep']:5.0f} {std:5.1f} "
              f"{r['avg_atemp']:6.0f} {r['avg_floors']:4.1f} "
              f"{r['avg_compactness']:8.2f} "
              f"{r['betsi_template']:>20s}")

    print(f"\n  Total clusters: {len(cluster_profiles)}")
    print(f"  Total unique buildings: "
          f"{df_all['FormularId'].nunique()}")

    # ── Identify archetypes (Dahlström method) ─────────────────────
    print(f"\n{'='*80}")
    print(f"  ARCHETYPE IDENTIFICATION (Dahlström et al. 2024)")
    print(f"{'='*80}")

    archetypes = identify_archetypes(df_clustered_bldgs)

    # Add BETSI template to archetypes
    archetypes["betsi_template"] = (
        archetypes["global_cluster"].map(template_map)
    )

        print(f"  {'Cluster':<16s} {'n':>4s} {'Archetype':>20s} "
            f"{'EP':>5s} {'R_i':>5s} {'D_i':>5s} {'Div':>5s} {'Q':>5s} {'BETSI':>20s}")
    print(f"  {'-'*16} {'-'*4} {'-'*20} "
            f"{'-'*5} {'-'*5} {'-'*5} {'-'*5} {'-'*5} {'-'*20}")

    for _, a in archetypes.iterrows():
        print(f"  {a['global_cluster']:<16s} "
              f"{a['cluster_size']:4.0f} "
              f"{a['IdFastBet']:>20s} "
              f"{a['ep']:5.0f} "
              f"{a['representativeness']:5.1f} "
              f"{a['distinctness']:5.1f} "
              f"{a['divergence']:5.1f} "
              f"{a['rep_div_score']:5.1f} "
              f"{a['betsi_template']:>20s}")

    # ── Save outputs ───────────────────────────────────────────────
    out_cols = [
        "FormularId", "IdFastBet", "IdAdr", "group", "cluster",
        "global_cluster", "betsi_template", "ep", "atemp", "floors",
        "apartments", "ventilation", "renovated", "byggar",
        "fp_area", "fp_perimeter", "fp_compactness", "fp_slenderness",
        "n_footprints", "derived_volume", "derived_atemp", "atemp_per_apt",
    ]
    available = [c for c in out_cols if c in df_all.columns]
    df_all[available].to_csv(EDA_DIR / "clusters_betsi.csv", index=False)
    print(f"\n  → Saved clusters_betsi.csv ({len(df_all)} rows, "
          f"{df_all['FormularId'].nunique()} unique buildings)")

    archetypes.to_csv(EDA_DIR / "archetypes_betsi.csv", index=False)
    print(f"  → Saved archetypes_betsi.csv ({len(archetypes)} rows)")

    # ── Cluster profile heatmap ────────────────────────────────────
    heatmap_cols = ["atemp", "floors", "fp_area", "fp_compactness",
                    "atemp_per_apt", "ep"]
    cluster_means = (df_clustered_bldgs
                     .groupby("global_cluster")[heatmap_cols].mean())
    cluster_z = ((cluster_means - cluster_means.mean())
                 / cluster_means.std())

    fig, ax = plt.subplots(
        figsize=(12, max(4, len(cluster_means) * 0.5)))
    sns.heatmap(
        cluster_z.T,
        annot=cluster_means.T.round(1).values, fmt="",
        cmap="RdBu_r", center=0, ax=ax, linewidths=0.5,
    )
    ax.set_xlabel("Cluster")
    ax.set_ylabel("Feature")
    ax.set_title("Cluster Profiles (BETSI mapping) — "
                 "values = means, colour = z-score")
    plt.tight_layout()
    fig.savefig(FIG_DIR / "clustering_heatmap_betsi.png", dpi=150)
    plt.close()

    # ── EP boxplot ─────────────────────────────────────────────────
    order = sorted(df_clustered_bldgs["global_cluster"].unique())
    fig, ax = plt.subplots(figsize=(max(12, len(order) * 0.9), 6))

    # Color by BETSI template
    palette = {
        "BETSI_CONC_SLAB": "#4C72B0",
        "BETSI_CONC_TOWER": "#DD8452",
        "BETSI_CONC_POINT": "#55A868",
    }
    colors = [palette.get(template_map.get(c, ""), "#999999")
              for c in order]

    bp = ax.boxplot(
        [df_clustered_bldgs[df_clustered_bldgs["global_cluster"] == c][
            "ep"].values for c in order],
        tick_labels=order, patch_artist=True,
    )
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)

    ax.set_xticklabels(order, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("EP (kWh/m²)")
    ax.set_title("EP Distribution by Cluster — "
                 "coloured by BETSI template")
    ax.grid(True, axis="y", alpha=0.3)

    # Legend
    from matplotlib.patches import Patch
    legend_items = [
        Patch(facecolor=palette["BETSI_CONC_SLAB"], alpha=0.6,
              label="CONC_SLAB (≤4 fl)"),
        Patch(facecolor=palette["BETSI_CONC_TOWER"], alpha=0.6,
              label="CONC_TOWER (5-6 fl)"),
        Patch(facecolor=palette["BETSI_CONC_POINT"], alpha=0.6,
              label="CONC_POINT (≥7 fl)"),
    ]
    ax.legend(handles=legend_items, loc="upper right")

    plt.tight_layout()
    fig.savefig(FIG_DIR / "clustering_ep_boxplot_betsi.png", dpi=150)
    plt.close()

    print(f"\n  → Saved figures/clustering_*_betsi.png")

    return df_all, archetypes, cluster_profiles


if __name__ == "__main__":
    run()
