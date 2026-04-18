"""
Step 4 — Archetype-to-Cluster Matching & Error Analysis.

For each cluster identified in Step 3, evaluates which buildings have
been simulated with our CMF_1960_1 archetype (from the existing
results_uddevalla_cmf1960_strat.csv) and computes prediction error.

Also checks which cluster Fjällvägen 28 belongs to and whether
the CMF_1960_1 archetype is appropriate for that cluster.

Outputs:
  - Error analysis per cluster (where simulation data exists)
  - Cluster-level archetype fitness assessment
  - Recommended archetype tuning per cluster
  - Figures: error distribution, cluster vs. EPC ratio
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

EDA_DIR = Path(__file__).resolve().parent
PROJECT_DIR = EDA_DIR.parent
FIG_DIR = EDA_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)

FJALLVAGEN_FORMULAR_ID = 1033661


def run():
    # ── Load cluster assignments ────────────────────────────────────────
    # Use k=5 as our primary clustering
    clusters = pd.read_csv(EDA_DIR / "clusters_1960s_k5.csv")
    full_data = pd.read_csv(EDA_DIR / "uddevalla_mfh_features.csv")
    print(f"Cluster assignments: {len(clusters)} buildings")
    print(f"Full dataset: {len(full_data)} buildings")

    # ── Load simulation results ─────────────────────────────────────────
    sim_results = pd.read_csv(PROJECT_DIR / "results_uddevalla_cmf1960_strat.csv")
    print(f"Simulation results: {len(sim_results)} buildings")
    print(f"Simulated FormularIds: {sorted(sim_results['FormularId'].unique())[:10]}...")

    # ── Merge simulation results with cluster assignments ───────────────
    # Each simulated building may have multiple EPC entries (FormularId
    # appears multiple times in full_data). We take the first cluster match.
    cluster_lookup = clusters.drop_duplicates(subset="FormularId")[
        ["FormularId", "cluster_k5"]
    ]

    merged = sim_results.merge(cluster_lookup, on="FormularId", how="left")
    print(f"\nSimulated buildings with cluster assignment: {merged['cluster_k5'].notna().sum()} / {len(merged)}")

    # Some simulated buildings may not be in the 1955-1975 range
    # Check which ones are missing
    missing = merged[merged["cluster_k5"].isna()]
    if len(missing):
        print(f"\nSimulated buildings NOT in 1955-1975 cluster set:")
        for _, row in missing.iterrows():
            print(f"  {row['FormularId']} — {row['Fastighet']} — Byggar={row['Byggar']}")

    # ── Error analysis per cluster ──────────────────────────────────────
    merged_valid = merged.dropna(subset=["cluster_k5"]).copy()
    merged_valid["cluster_k5"] = merged_valid["cluster_k5"].astype(int)

    # Key error metrics
    merged_valid["error_abs"] = merged_valid["EP_sim"] - merged_valid["EP_epc"]
    merged_valid["error_pct"] = (merged_valid["EP_sim"] - merged_valid["EP_epc"]) / merged_valid["EP_epc"] * 100

    print(f"\n{'='*70}")
    print(f"  ERROR ANALYSIS BY CLUSTER (k=5)")
    print(f"{'='*70}")

    for cluster_id in sorted(merged_valid["cluster_k5"].unique()):
        subset = merged_valid[merged_valid["cluster_k5"] == cluster_id]
        print(f"\n  ── Cluster {cluster_id} (n={len(subset)}) ──")
        print(f"    EPC_ratio: mean={subset['EPC_ratio'].mean():.2f}, "
              f"median={subset['EPC_ratio'].median():.2f}, "
              f"std={subset['EPC_ratio'].std():.2f}")
        print(f"    EP_epc:    mean={subset['EP_epc'].mean():.0f} kWh/m²")
        print(f"    EP_sim:    mean={subset['EP_sim'].mean():.0f} kWh/m²")
        print(f"    Error:     mean={subset['error_abs'].mean():.1f} kWh/m², "
              f"MAE={subset['error_abs'].abs().mean():.1f}")
        print(f"    Error %:   mean={subset['error_pct'].mean():.1f}%")
        print(f"    Vent:      {subset['Ventilation'].value_counts().to_dict()}")

        # Show individual buildings
        for _, row in subset.iterrows():
            marker = " ★" if row["FormularId"] == FJALLVAGEN_FORMULAR_ID else ""
            print(f"      {row['FormularId']:8d} {row['Fastighet']:20s} "
                  f"EP_epc={row['EP_epc']:3.0f}  EP_sim={row['EP_sim']:5.1f}  "
                  f"ratio={row['EPC_ratio']:.2f}  vent={row['Ventilation']}{marker}")

    # ── Overall model fitness ───────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  OVERALL MODEL FITNESS")
    print(f"{'='*70}")
    print(f"  n simulated: {len(merged_valid)}")
    print(f"  Mean EPC_ratio: {merged_valid['EPC_ratio'].mean():.2f}")
    print(f"  Median EPC_ratio: {merged_valid['EPC_ratio'].median():.2f}")
    print(f"  Std EPC_ratio: {merged_valid['EPC_ratio'].std():.2f}")
    print(f"  Within 20% (0.8-1.2): {((merged_valid['EPC_ratio'] >= 0.8) & (merged_valid['EPC_ratio'] <= 1.2)).mean()*100:.0f}%")
    print(f"  Within 30% (0.7-1.3): {((merged_valid['EPC_ratio'] >= 0.7) & (merged_valid['EPC_ratio'] <= 1.3)).mean()*100:.0f}%")

    # ── By ventilation system ───────────────────────────────────────────
    print(f"\n  BY VENTILATION SYSTEM:")
    for vent in ["S", "F", "FTX"]:
        subset = merged_valid[merged_valid["Ventilation"] == vent]
        if len(subset):
            print(f"    {vent:3s}: n={len(subset):2d}, mean_ratio={subset['EPC_ratio'].mean():.2f}, "
                  f"EP_epc={subset['EP_epc'].mean():.0f}, EP_sim={subset['EP_sim'].mean():.0f}")

    # ── Plot: EPC ratio by cluster ──────────────────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    # Plot 1: EPC ratio boxplot by cluster
    merged_valid.boxplot(column="EPC_ratio", by="cluster_k5", ax=axes[0], grid=False)
    axes[0].axhline(y=1.0, color="red", linestyle="--", alpha=0.7, label="Perfect match")
    axes[0].axhline(y=0.8, color="orange", linestyle=":", alpha=0.5)
    axes[0].axhline(y=1.2, color="orange", linestyle=":", alpha=0.5)
    axes[0].set_xlabel("Cluster")
    axes[0].set_ylabel("EPC Ratio (simulated / measured)")
    axes[0].set_title("CMF_1960_1 Accuracy by Cluster")
    plt.sca(axes[0])
    plt.suptitle("")

    # Plot 2: EPC ratio by ventilation system
    vent_order = ["S", "F", "FTX"]
    vent_data = merged_valid[merged_valid["Ventilation"].isin(vent_order)]
    vent_data.boxplot(column="EPC_ratio", by="Ventilation", ax=axes[1], grid=False)
    axes[1].axhline(y=1.0, color="red", linestyle="--", alpha=0.7)
    axes[1].axhline(y=0.8, color="orange", linestyle=":", alpha=0.5)
    axes[1].axhline(y=1.2, color="orange", linestyle=":", alpha=0.5)
    axes[1].set_xlabel("Ventilation System")
    axes[1].set_ylabel("EPC Ratio")
    axes[1].set_title("CMF_1960_1 Accuracy by Ventilation")
    plt.sca(axes[1])
    plt.suptitle("")

    # Plot 3: EP_sim vs EP_epc scatter colored by cluster
    for cluster_id in sorted(merged_valid["cluster_k5"].unique()):
        subset = merged_valid[merged_valid["cluster_k5"] == cluster_id]
        axes[2].scatter(subset["EP_epc"], subset["EP_sim"],
                       label=f"Cluster {cluster_id} (n={len(subset)})",
                       alpha=0.7, s=60, edgecolors="k", linewidths=0.3)

    # Mark Fjällvägen 28
    fjv = merged_valid[merged_valid["FormularId"] == FJALLVAGEN_FORMULAR_ID]
    if len(fjv):
        axes[2].scatter(fjv["EP_epc"], fjv["EP_sim"], c="red", s=200,
                       marker="*", zorder=5, label="Fjällvägen 28", edgecolors="k")

    # Perfect match line
    ep_range = [50, 250]
    axes[2].plot(ep_range, ep_range, "r--", alpha=0.5, label="y=x")
    axes[2].plot(ep_range, [x*1.2 for x in ep_range], "orange", linestyle=":", alpha=0.3)
    axes[2].plot(ep_range, [x*0.8 for x in ep_range], "orange", linestyle=":", alpha=0.3)
    axes[2].set_xlabel("EP (EPC measured, kWh/m²)")
    axes[2].set_ylabel("EP (CMF_1960_1 simulated, kWh/m²)")
    axes[2].set_title("Simulated vs. Measured EP")
    axes[2].legend(fontsize=8)
    axes[2].set_xlim(ep_range)
    axes[2].set_ylim(ep_range)
    axes[2].set_aspect("equal")

    plt.tight_layout()
    fig.savefig(FIG_DIR / "archetype_error_by_cluster.png", dpi=150)
    plt.close()
    print(f"\n  → Saved archetype_error_by_cluster.png")

    # ── Cluster-level recommendation ────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  ARCHETYPE FITNESS RECOMMENDATIONS")
    print(f"{'='*70}")

    # Analyze each cluster's fitness
    for cluster_id in sorted(merged_valid["cluster_k5"].unique()):
        subset = merged_valid[merged_valid["cluster_k5"] == cluster_id]
        mean_ratio = subset["EPC_ratio"].mean()
        n = len(subset)

        # Get cluster profile from full cluster data
        cluster_profile = clusters[clusters["cluster_k5"] == cluster_id]
        dominant_vent = cluster_profile["ventilation"].mode().iloc[0] if len(cluster_profile) else "?"
        avg_ep = cluster_profile["ep"].mean() if len(cluster_profile) else 0
        reno_pct = cluster_profile["renovated"].mean() * 100 if len(cluster_profile) else 0

        print(f"\n  Cluster {cluster_id}: n_simulated={n}, "
              f"n_total={len(cluster_profile)}, "
              f"avg_EP={avg_ep:.0f}, dominant_vent={dominant_vent}, "
              f"reno={reno_pct:.0f}%")
        print(f"    Mean ratio: {mean_ratio:.2f}")

        if 0.8 <= mean_ratio <= 1.2:
            print(f"    ✓ CMF_1960_1 is APPROPRIATE for this cluster")
        elif mean_ratio < 0.8:
            overshoot = (1 - mean_ratio) * 100
            print(f"    ✗ CMF_1960_1 UNDERESTIMATES EP by ~{overshoot:.0f}%")
            print(f"      → Model predicts lower EP than measured")
            print(f"      → Likely cause: missing heat losses not captured by archetype")
        else:
            overshoot = (mean_ratio - 1) * 100
            print(f"    ✗ CMF_1960_1 OVERESTIMATES EP by ~{overshoot:.0f}%")
            print(f"      → Model predicts higher EP than measured")
            print(f"      → Likely cause: archetype envelope too leaky for this subgroup")

    # ── Detailed look at Fjällvägen 28's cluster ────────────────────────
    print(f"\n{'='*70}")
    print(f"  FJÄLLVÄGEN 28 — DETAILED CLUSTER ANALYSIS")
    print(f"{'='*70}")

    fjv_full = full_data[full_data["FormularId"] == FJALLVAGEN_FORMULAR_ID].iloc[0]
    fjv_cluster = clusters[clusters["FormularId"] == FJALLVAGEN_FORMULAR_ID]
    if len(fjv_cluster):
        cid = fjv_cluster.iloc[0]["cluster_k5"]
        cluster_buildings = clusters[clusters["cluster_k5"] == cid]

        print(f"\n  Fjällvägen 28 is in Cluster {int(cid)}")
        print(f"  Cluster {int(cid)} profile:")
        print(f"    Buildings in cluster: {len(cluster_buildings)}")
        print(f"    EP range: {cluster_buildings['ep'].min():.0f} – {cluster_buildings['ep'].max():.0f} kWh/m²")
        print(f"    EP mean: {cluster_buildings['ep'].mean():.1f} ± {cluster_buildings['ep'].std():.1f}")
        print(f"    Fjällvägen 28 EP: {fjv_full['ep']}")

        # Ventilation breakdown
        print(f"\n    Ventilation breakdown:")
        vc = cluster_buildings["ventilation"].value_counts()
        for vent, cnt in vc.items():
            print(f"      {vent}: {cnt} ({cnt/len(cluster_buildings)*100:.0f}%)")

        # How many have been simulated?
        simulated_in_cluster = merged_valid[merged_valid["cluster_k5"] == cid]
        print(f"\n    Simulated buildings in this cluster: {len(simulated_in_cluster)}")
        if len(simulated_in_cluster):
            print(f"    Simulation accuracy in cluster:")
            print(f"      Mean ratio: {simulated_in_cluster['EPC_ratio'].mean():.2f}")
            print(f"      Std ratio:  {simulated_in_cluster['EPC_ratio'].std():.2f}")

        # Buildings similar to Fjällvägen 28 within cluster
        similar = cluster_buildings[
            (cluster_buildings["ventilation"] == "S") &
            (cluster_buildings["ep"].between(90, 130))
        ]
        print(f"\n    S-vent buildings with EP 90-130 in cluster: {len(similar)}")
        if len(similar):
            print(f"    Their EP: {similar['ep'].describe()[['mean','std','min','max']].to_string()}")

    # ── Save merged results ─────────────────────────────────────────────
    merged_valid.to_csv(EDA_DIR / "simulation_vs_clusters.csv", index=False)
    print(f"\n  → Saved simulation_vs_clusters.csv")


if __name__ == "__main__":
    run()
