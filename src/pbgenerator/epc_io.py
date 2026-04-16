"""Load building footprints and EPC metadata from the Swedish EPC DuckDB."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class FootprintRecord:
    """A building footprint with associated EPC metadata."""
    objektidentitet: str
    formular_id: int | None
    footprint_pts: list[list[float]]  # [[x, y], ...] in EPSG:3006 (SWEREF99 TM)
    centroid_lat: float               # WGS-84 latitude
    centroid_lon: float               # WGS-84 longitude
    andamal: str
    kommun: str
    # EPC fields (None when no EPC match)
    byggnads_kat: str | None
    construction_year: int | None
    atemp: int | None
    num_floors: int | None
    num_apartments: int | None
    energi_prestanda: int | None      # kWh/m²/yr
    fastighet_kwh: int | None         # building services electricity (kWh/yr)

    @property
    def footprint_area(self) -> float:
        """Footprint area in m² (shoelace formula)."""
        pts = self.footprint_pts
        n = len(pts)
        a = 0.0
        for i in range(n):
            j = (i + 1) % n
            a += pts[i][0] * pts[j][1] - pts[j][0] * pts[i][1]
        return abs(a) / 2.0


# ---------------------------------------------------------------------------
# WKT parsing  (avoids shapely / geopandas dependency)
# ---------------------------------------------------------------------------

def _parse_polygon_rings(wkt: str) -> list[list[tuple[float, float]]]:
    """Parse a POLYGON or first polygon of MULTIPOLYGON WKT.

    Returns a list of rings, each ring = [(x, y), ...].
    Only the exterior ring (index 0) is typically needed.
    """
    s = wkt.strip()
    if s.upper().startswith("MULTIPOLYGON"):
        s = s[len("MULTIPOLYGON"):].strip()
        # MULTIPOLYGON (((ring), (ring)), ((ring)))
        # Strip outer parens → ((ring), (ring)), ((ring))
        # Take first polygon → (ring), (ring)
        s = s[1:-1].strip()          # drop outermost ( )
        # Find the end of the first polygon: match the opening '('
        depth = 0
        end = 0
        for i, ch in enumerate(s):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        s = s[: end + 1]  # first polygon with its parens
    elif s.upper().startswith("POLYGON"):
        s = s[len("POLYGON"):].strip()
    else:
        raise ValueError(f"Unsupported geometry type: {wkt[:40]}")

    # s is now like "((x y, x y, ...), (x y, ...))"
    # Strip the polygon-level parens
    s = s.strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()

    # Now split rings on "),(" boundaries
    rings: list[list[tuple[float, float]]] = []
    ring_strs = s.split("),(")
    for rs in ring_strs:
        rs = rs.strip("() ")
        pts: list[tuple[float, float]] = []
        for pair in rs.split(","):
            parts = pair.strip().split()
            if len(parts) >= 2:
                pts.append((float(parts[0]), float(parts[1])))
        if pts:
            rings.append(pts)
    return rings


# ---------------------------------------------------------------------------
# Public query API
# ---------------------------------------------------------------------------

_DEFAULT_DB = Path(__file__).resolve().parents[2] / "epc_sweden.duckdb"

_QUERY = """\
SELECT
    f.objektidentitet,
    f.FormularId,
    f.andamal1,
    ST_AsText(ST_GeomFromWKB(f.geom)) AS wkt,
    e.EgenByggnadsKat,
    e.EgenNybyggAr,
    e.EgenAtemp,
    e.EgenAntalPlan,
    e.EgenAntalBolgh,
    e.IdKommun,
    e.EgiEnergiPrestanda,
    e.EgiFastighet
FROM footprints f
LEFT JOIN (
    SELECT * FROM epc
    QUALIFY ROW_NUMBER() OVER (PARTITION BY FormularId ORDER BY IdHuvudadress DESC) = 1
) e ON f.FormularId = e.FormularId
WHERE 1=1
"""


def load_footprints(
    *,
    db_path: str | Path = _DEFAULT_DB,
    formular_id: int | None = None,
    objektidentitet: str | None = None,
    fastighetsbeteckning: str | None = None,
    husnummer: int | None = None,
    address: str | None = None,
    kommun: str | None = None,
    byggnads_kat: str | None = None,
    andamal: str | None = None,
    limit: int = 100,
) -> list[FootprintRecord]:
    """Query the EPC/footprint database and return footprint records.

    Parameters
    ----------
    db_path : path to the DuckDB file.
    formular_id : filter by a specific EPC FormularId.
    objektidentitet : filter by footprint UUID.
    fastighetsbeteckning : property designation (e.g. 'ÄGIR 17'), case-insensitive.
    husnummer : building number within the property.
    address : street address substring (e.g. 'Fjällvägen 28'), matched against EPC IdAdr.
    kommun : municipality name (e.g. 'Göteborg').
    byggnads_kat : building category (e.g. 'Flerbostadshus').
    andamal : footprint purpose filter (substring match, e.g. 'Flerfamiljshus').
    limit : maximum number of records to return.
    """
    import duckdb
    from pyproj import Transformer

    _tx_4326_to_3006 = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)

    con = duckdb.connect(str(db_path), read_only=True)
    con.execute("LOAD spatial;")

    # If searching by address, resolve to fastighetsbeteckning first
    if address is not None and fastighetsbeteckning is None:
        epc_row = con.execute(
            "SELECT IdFastBet FROM epc WHERE IdAdr LIKE ? LIMIT 1",
            [f"%{address}%"],
        ).fetchone()
        if epc_row and epc_row[0]:
            fastighetsbeteckning = epc_row[0]
        else:
            con.close()
            return []

    sql = _QUERY
    params: list = []

    if formular_id is not None:
        sql += " AND f.FormularId = ?"
        params.append(formular_id)
    if objektidentitet is not None:
        sql += " AND f.objektidentitet = ?"
        params.append(objektidentitet)
    if fastighetsbeteckning is not None:
        sql += " AND UPPER(f.fastighetsbeteckning) = UPPER(?)"
        params.append(fastighetsbeteckning)
    if husnummer is not None:
        sql += " AND f.husnummer = ?"
        params.append(husnummer)
    if kommun is not None:
        sql += " AND e.IdKommun = ?"
        params.append(kommun)
    if byggnads_kat is not None:
        sql += " AND e.EgenByggnadsKat = ?"
        params.append(byggnads_kat)
    if andamal is not None:
        sql += " AND f.andamal1 LIKE ?"
        params.append(f"%{andamal}%")

    sql += f" LIMIT {int(limit)}"

    rows = con.execute(sql, params).fetchall()
    con.close()
    log.info("Loaded %d footprint(s) from EPC database", len(rows))

    records: list[FootprintRecord] = []
    for row in rows:
        (objid, fid, andamal1, wkt,
         kat, year, atemp, floors, apts, kommun_name,
         energi_prest, fastighet) = row

        if wkt is None:
            continue

        rings = _parse_polygon_rings(wkt)
        if not rings:
            continue

        # Exterior ring, drop closing duplicate vertex
        exterior = rings[0]
        if len(exterior) > 1 and exterior[0] == exterior[-1]:
            exterior = exterior[:-1]
        if len(exterior) < 3:
            continue

        # WGS-84 centroid (before transform to EPSG:3006)
        c_lon = sum(p[0] for p in exterior) / len(exterior)
        c_lat = sum(p[1] for p in exterior) / len(exterior)

        # Transform from WGS-84 (lon, lat) to EPSG:3006 (SWEREF99 TM metres)
        pts_m = []
        for lon, lat in exterior:
            x, y = _tx_4326_to_3006.transform(lon, lat)
            pts_m.append([x, y])

        records.append(FootprintRecord(
            objektidentitet=objid,
            formular_id=int(fid) if fid is not None else None,
            footprint_pts=pts_m,
            centroid_lat=c_lat,
            centroid_lon=c_lon,
            andamal=andamal1 or "",
            kommun=kommun_name or "",
            byggnads_kat=kat,
            construction_year=int(year) if year is not None else None,
            atemp=int(atemp) if atemp is not None else None,
            num_floors=int(floors) if floors is not None else None,
            num_apartments=int(apts) if apts is not None else None,
            energi_prestanda=int(energi_prest) if energi_prest is not None else None,
            fastighet_kwh=int(fastighet) if fastighet is not None else None,
        ))

    return records


@dataclass
class ContextFootprint:
    """A nearby building footprint used for shading context."""
    objektidentitet: str
    footprint_pts: list[list[float]]  # [[x, y], ...] in EPSG:3006
    height: float                     # metres


_CONTEXT_QUERY = """\
WITH target AS (
    SELECT ST_Centroid(ST_GeomFromWKB(geom)) AS pt,
           objektidentitet AS target_id
    FROM footprints
    WHERE objektidentitet = ?
    LIMIT 1
),
nearby AS (
    SELECT f.objektidentitet,
           f.FormularId,
           ST_AsText(ST_GeomFromWKB(f.geom)) AS wkt
    FROM footprints f, target t
    WHERE ST_Distance(ST_Centroid(ST_GeomFromWKB(f.geom)), t.pt) < ?
      AND f.objektidentitet != t.target_id
)
SELECT n.objektidentitet, n.wkt, e.EgenAntalPlan
FROM nearby n
LEFT JOIN (
    SELECT FormularId, EgenAntalPlan
    FROM epc
    QUALIFY ROW_NUMBER() OVER (PARTITION BY FormularId ORDER BY IdHuvudadress DESC) = 1
) e ON n.FormularId = e.FormularId
"""


def load_context_footprints(
    target: FootprintRecord,
    *,
    radius_m: float = 500.0,
    default_height: float = 15.0,
    floor_height: float = 3.0,
    db_path: str | Path = _DEFAULT_DB,
) -> list[ContextFootprint]:
    """Load nearby building footprints for context shading.

    Parameters
    ----------
    target : the target building whose neighbourhood to query.
    radius_m : search radius in metres (converted to approximate degrees).
    default_height : height to assign buildings without EPC data.
    floor_height : assumed storey height for EPC-derived heights.
    db_path : path to the DuckDB file.
    """
    import duckdb
    from pyproj import Transformer

    _tx_4326_to_3006 = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)

    # Convert radius to approximate degrees (1 deg lat ≈ 111 km)
    deg_radius = radius_m / 111_000.0

    con = duckdb.connect(str(db_path), read_only=True)
    con.execute("LOAD spatial;")

    rows = con.execute(_CONTEXT_QUERY, [target.objektidentitet, deg_radius]).fetchall()
    con.close()

    results: list[ContextFootprint] = []
    seen: set[str] = set()

    for objid, wkt, epc_floors in rows:
        if objid in seen or wkt is None:
            continue
        seen.add(objid)

        try:
            rings = _parse_polygon_rings(wkt)
        except (ValueError, IndexError):
            continue
        if not rings:
            continue

        exterior = rings[0]
        if len(exterior) > 1 and exterior[0] == exterior[-1]:
            exterior = exterior[:-1]
        if len(exterior) < 3:
            continue

        pts_m = []
        for lon, lat in exterior:
            x, y = _tx_4326_to_3006.transform(lon, lat)
            pts_m.append([x, y])

        if epc_floors is not None and int(epc_floors) > 0:
            height = int(epc_floors) * floor_height
        else:
            height = default_height

        results.append(ContextFootprint(
            objektidentitet=objid,
            footprint_pts=pts_m,
            height=height,
        ))

    log.info("Loaded %d context footprints within %.0fm", len(results), radius_m)
    return results


def load_footprint_by_id(
    formular_id: int,
    *,
    db_path: str | Path = _DEFAULT_DB,
) -> FootprintRecord:
    """Load a single footprint by EPC FormularId."""
    results = load_footprints(db_path=db_path, formular_id=formular_id, limit=1)
    if not results:
        raise LookupError(f"No footprint found for FormularId={formular_id}")
    return results[0]


def load_epc_metadata(
    formular_id: int,
    *,
    db_path: str | Path = _DEFAULT_DB,
) -> dict[str, int | str | None]:
    """Load basic EPC building metadata by FormularId.

    Useful when the footprint's FormularId doesn't match the target EPC.
    """
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    row = con.execute("""
        SELECT EgenByggnadsKat, EgenNybyggAr, EgenAtemp, EgenAntalPlan,
               EgenAntalBolgh, EgiEnergiPrestanda, EgiFastighet,
               EgenAtempBostad, EgenAvarmgarage, EgenAntalKallarplan
        FROM epc WHERE FormularId = ? LIMIT 1
    """, [formular_id]).fetchone()
    con.close()

    if row is None:
        raise LookupError(f"No EPC found for FormularId={formular_id}")

    res_pct = int(row[7]) if row[7] is not None else 100
    garage_m2 = int(row[8]) if row[8] is not None else 0
    basement_floors = int(row[9]) if row[9] is not None else 0

    log.info("EPC %d: year=%s  Atemp=%s  floors=%s  apts=%s  EP=%s kWh/m²/yr  "
             "residential=%d%%  garage=%dm²  basement_floors=%d",
             formular_id, row[1], row[2], row[3], row[4], row[5],
             res_pct, garage_m2, basement_floors)

    return {
        "byggnads_kat": row[0],
        "construction_year": int(row[1]) if row[1] is not None else None,
        "atemp": int(row[2]) if row[2] is not None else None,
        "num_floors": int(row[3]) if row[3] is not None else None,
        "num_apartments": int(row[4]) if row[4] is not None else None,
        "energi_prestanda": int(row[5]) if row[5] is not None else None,
        "fastighet_kwh": int(row[6]) if row[6] is not None else None,
        "residential_pct": res_pct,
        "garage_m2": garage_m2,
        "num_basement_floors": basement_floors,
    }


_EPC_ENERGY_LABELS = [
    ("Fjv",          "EgiFjarrvarme"),
    ("FjvUPPV",      "EgiFjarrvarmeUPPV"),
    ("FjvVV",        "EgiFjarrvarmeVV"),
    ("Olja",         "EgiOlja"),
    ("Gas",          "EgiGas"),
    ("ElVatten",     "EgiElVatten"),
    ("ElDirekt",     "EgiElDirekt"),
    ("PumpMark",     "EgiPumpMark"),
    ("PumpMarkUPPV", "EgiPumpMarkUPPV"),
    ("PumpFranluft",     "EgiPumpFranluft"),
    ("PumpFranluftUPPV", "EgiPumpFranluftUPPV"),
    ("PumpLuftLuft",     "EgiPumpLuftLuft"),
    ("PumpLuftLuftUPPV", "EgiPumpLuftLuftUPPV"),
    ("PumpLuftVatten",     "EgiPumpLuftVatten"),
    ("PumpLuftVattenUPPV", "EgiPumpLuftVattenUPPV"),
    ("Summa1",       "EgiSumma1"),
    ("VVBered",      "EgiVVBered"),
    ("Fastighet",    "EgiFastighet"),
    ("Hushall",      "EgiHushall"),
    ("Verksamhet",   "EgiVerksamhet"),
    ("Komfort",      "EgiKomfort"),
    ("Summa2",       "EgiSumma2"),
]


def load_epc_energy(
    formular_id: int,
    *,
    db_path: str | Path = _DEFAULT_DB,
) -> dict[str, int | None]:
    """Load the EPC energy breakdown for a given FormularId.

    Returns a dict mapping short label → kWh value (or None).
    """
    import duckdb

    cols = ", ".join(col for _, col in _EPC_ENERGY_LABELS)
    extra = ", EgiNormKorrGD, EgiForstaArManad, EgiSistaArManad"
    con = duckdb.connect(str(db_path), read_only=True)
    row = con.execute(
        f"SELECT {cols}{extra} FROM epc WHERE FormularId = ? LIMIT 1",
        [formular_id],
    ).fetchone()
    con.close()

    if row is None:
        raise LookupError(f"No EPC found for FormularId={formular_id}")

    n_energy = len(_EPC_ENERGY_LABELS)
    result: dict[str, int | float | None] = {
        label: (int(v) if v is not None else None)
        for (label, _), v in zip(_EPC_ENERGY_LABELS, row[:n_energy])
    }
    # Normal-year correction columns
    result["NormKorrGD"] = float(row[n_energy]) if row[n_energy] is not None else None
    result["PeriodStart"] = int(row[n_energy + 1]) if row[n_energy + 1] is not None else None
    result["PeriodEnd"] = int(row[n_energy + 2]) if row[n_energy + 2] is not None else None

    non_null = {k: v for k, v in result.items() if v is not None}
    log.info("EPC %d energy: %s", formular_id, non_null)
    return result


def detect_ventilation_system(
    formular_id: int,
    *,
    db_path: str | Path = _DEFAULT_DB,
) -> str:
    """Infer ventilation system type from EPC ventilation-type fields.

    Returns one of: "S", "F", "FT", "FTX".
    Priority: FTX > FT > F > S (självdrag).

    Note: FVP (frånluftvärmepump) is a *heating system*, not a ventilation
    type.  A building can have självdrag ventilation with a small FVP for
    supplementary heating.  Use ``load_epc_energy()["PumpFranluftUPPV"]``
    to check for FVP presence separately.
    """
    import duckdb

    # Check the ventilation type fields directly
    con = duckdb.connect(str(db_path), read_only=True)
    row = con.execute(
        "SELECT VentTypFTX, VentTypFT, VentTypF, VentTypSjalvdrag "
        "FROM epc WHERE FormularId = ? LIMIT 1",
        [formular_id],
    ).fetchone()
    con.close()

    if row:
        ftx, ft, f_only, sjd = row
        if ftx and ftx.strip().lower() == "ja":
            log.info("EPC %d: detected ventilation system FTX (VentTypFTX=Ja)", formular_id)
            return "FTX"
        if ft and ft.strip().lower() == "ja":
            log.info("EPC %d: detected ventilation system FT (VentTypFT=Ja)", formular_id)
            return "FT"
        if f_only and f_only.strip().lower() == "ja":
            log.info("EPC %d: detected ventilation system F (VentTypF=Ja)", formular_id)
            return "F"
        if sjd and sjd.strip().lower() == "ja":
            log.info("EPC %d: detected ventilation system S (VentTypSjalvdrag=Ja)", formular_id)
            return "S"

    log.info("EPC %d: detected ventilation system F (frånluft, default)", formular_id)
    return "F"
