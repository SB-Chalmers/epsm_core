"""
Step 1b — Add building footprint geometry features to the MFH dataset.

Queries the DuckDB footprints table, transforms WGS-84 polygons to
EPSG:3006 (SWEREF99 TM, metres), and computes per-building geometry
metrics:

  - fp_area        : total footprint area (m²), summed over all polygons
  - fp_perimeter   : total footprint perimeter (m)
  - n_footprints   : number of footprint polygons per FormularId
  - fp_compactness : 4π·area / perimeter²  (circle = 1, elongated → 0)
  - derived_volume : fp_area × floors × storey_height (3.0 m default)
  - derived_atemp  : fp_area × floors × 0.85 (rough BRA → Atemp factor)
  - fp_slenderness : perimeter / (2·√(π·area))  — 1 for circle, higher for elongated

These are merged into the existing uddevalla_mfh_features.csv on FormularId.
"""
import duckdb
import numpy as np
import pandas as pd
from pathlib import Path
from pyproj import Transformer

EDA_DIR = Path(__file__).resolve().parent
DB_PATH = EDA_DIR.parent / "epc_sweden.duckdb"
DATA_PATH = EDA_DIR / "uddevalla_mfh_features.csv"

STOREY_HEIGHT = 3.0  # metres


def _parse_polygon_rings(wkt: str):
    """Extract exterior ring coords from POLYGON or first polygon of MULTIPOLYGON."""
    wkt = wkt.strip()
    if wkt.startswith("MULTIPOLYGON"):
        wkt = wkt[len("MULTIPOLYGON"):].strip()
        wkt = wkt[1:]  # strip outer (
        depth = 0
        end = 0
        for i, ch in enumerate(wkt):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        wkt = "POLYGON " + wkt[:end+1]
    if wkt.startswith("POLYGON"):
        wkt = wkt[len("POLYGON"):].strip()

    # Remove outer parens
    wkt = wkt.strip("() ")
    ring_strs = wkt.split("),(")
    rings = []
    for rs in ring_strs:
        rs = rs.strip("() ")
        pts = []
        for pair in rs.split(","):
            parts = pair.strip().split()
            if len(parts) >= 2:
                pts.append((float(parts[0]), float(parts[1])))
        if pts:
            rings.append(pts)
    return rings


def _shoelace_area(pts):
    """Signed area via shoelace formula (should be in projected coords)."""
    n = len(pts)
    a = 0.0
    for i in range(n):
        j = (i + 1) % n
        a += pts[i][0] * pts[j][1] - pts[j][0] * pts[i][1]
    return abs(a) / 2.0


def _perimeter(pts):
    """Perimeter of a closed polygon (projected coords)."""
    n = len(pts)
    p = 0.0
    for i in range(n):
        j = (i + 1) % n
        dx = pts[j][0] - pts[i][0]
        dy = pts[j][1] - pts[i][1]
        p += (dx**2 + dy**2) ** 0.5
    return p


def run():
    tx = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)

    con = duckdb.connect(str(DB_PATH), read_only=True)
    con.execute("LOAD spatial;")

    # Get all footprints for Uddevalla MFH
    rows = con.execute("""
        SELECT f.FormularId,
               ST_AsText(ST_GeomFromWKB(f.geom)) AS wkt
        FROM footprints f
        LEFT JOIN (
            SELECT * FROM epc
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY FormularId ORDER BY IdHuvudadress DESC
            ) = 1
        ) e ON f.FormularId = e.FormularId
        WHERE e.EgenByggnadsKat = 'Flerbostadshus'
          AND e.IdKommun = 'Uddevalla'
          AND e.EgenAtemp > 0
          AND e.EgiEnergiPrestanda > 0
    """).fetchdf()
    con.close()
    print(f"Loaded {len(rows)} footprint records")

    # Compute geometry per footprint, then aggregate per FormularId
    records = []
    for _, row in rows.iterrows():
        fid = row["FormularId"]
        wkt = row["wkt"]
        if wkt is None:
            continue

        rings = _parse_polygon_rings(wkt)
        if not rings:
            continue

        exterior = rings[0]
        if len(exterior) > 1 and exterior[0] == exterior[-1]:
            exterior = exterior[:-1]
        if len(exterior) < 3:
            continue

        # Transform WGS-84 → EPSG:3006
        pts_m = [tx.transform(lon, lat) for lon, lat in exterior]

        area = _shoelace_area(pts_m)
        perim = _perimeter(pts_m)
        records.append({"FormularId": fid, "area": area, "perim": perim})

    df_fp = pd.DataFrame(records)
    print(f"Computed geometry for {len(df_fp)} footprints")

    # Aggregate per FormularId (buildings can have multiple footprint polygons)
    agg = df_fp.groupby("FormularId").agg(
        fp_area=("area", "sum"),
        fp_perimeter=("perim", "sum"),
        n_footprints=("area", "count"),
    ).reset_index()

    # Derived metrics
    agg["fp_compactness"] = np.where(
        agg["fp_perimeter"] > 0,
        4 * np.pi * agg["fp_area"] / agg["fp_perimeter"] ** 2,
        np.nan,
    )
    agg["fp_slenderness"] = np.where(
        agg["fp_area"] > 0,
        agg["fp_perimeter"] / (2 * np.sqrt(np.pi * agg["fp_area"])),
        np.nan,
    )

    print(f"Unique buildings with geometry: {len(agg)}")
    print(f"fp_area: {agg['fp_area'].describe()}")

    # Merge into existing features CSV
    df = pd.read_csv(DATA_PATH)

    # Drop old geometry columns if re-running
    for col in ["fp_area", "fp_perimeter", "n_footprints",
                 "fp_compactness", "fp_slenderness",
                 "derived_volume", "derived_atemp"]:
        if col in df.columns:
            df.drop(columns=[col], inplace=True)

    df = df.merge(agg, on="FormularId", how="left")

    # Derived volume and Atemp (need floors from the EPC)
    df["derived_volume"] = df["fp_area"] * df["floors"] * STOREY_HEIGHT
    df["derived_atemp"] = df["fp_area"] * df["floors"] * 0.85

    matched = df["fp_area"].notna().sum()
    print(f"Merged: {matched}/{len(df)} buildings have footprint geometry")

    df.to_csv(DATA_PATH, index=False)
    print(f"Saved updated features to {DATA_PATH}")

    return df


if __name__ == "__main__":
    run()
