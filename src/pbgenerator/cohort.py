"""Cohort builder — extract building feature tables for a Swedish kommun.

A :class:`Cohort` wraps the EPC + footprint + (optional) socio-economic
feature engineering used in the EDA pipeline (``EDA/build_city_features.py``)
behind a single class so downstream studies can opt into the same schema
without copying SQL.

Typical use::

    from pbgenerator.cohort import Cohort

    gbg = Cohort(
        kommun_name="Göteborg",
        kommunkod="1480",
        category="Flerbostadshus",
        year_range=(1955, 1975),
    )
    df = gbg.to_features(socioeconomic=False)
    df.to_csv("gothenburg_mfh_1960s.csv", index=False)

The schema matches ``EDA/uddevalla_mfh_features.csv``: per-building EPC
columns (energy components, ventilation, renovations, heating system),
derived ratios (atemp_per_apt, garage_pct, heating_intensity), the era
flags, footprint geometry (fp_area, fp_perimeter, fp_compactness,
fp_slenderness, derived_volume, derived_atemp, centroid_e/n) and — when
``socioeconomic=True`` — population density, RegSO area, and median income.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import duckdb
import numpy as np
import pandas as pd

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "epc_sweden.duckdb"
STOREY_HEIGHT = 3.0  # metres — typical 1960s lamellhus floor-to-floor


# ---------------------------------------------------------------------------
# Cohort
# ---------------------------------------------------------------------------

@dataclass
class Cohort:
    """A municipality + category + era cohort spec.

    Parameters
    ----------
    kommun_name:
        SCB municipality name as it appears in ``epc.IdKommun`` (e.g.
        ``"Göteborg"``, ``"Uddevalla"``).
    kommunkod:
        Four-digit SCB code (e.g. ``"1480"``).  Required only for
        ``socioeconomic=True``.
    category:
        EPC building category (``EgenByggnadsKat``).  Default
        ``"Flerbostadshus"`` (multi-family housing).
    year_range:
        Inclusive ``(min_year, max_year)`` filter on ``EgenNybyggAr``.
        Default ``(1955, 1975)`` — the 1960s miljonprogram cohort.
    db_path:
        Override the DuckDB path; defaults to repo-root ``epc_sweden.duckdb``.
    """
    kommun_name: str
    kommunkod: str | None = None
    category: str = "Flerbostadshus"
    year_range: tuple[int, int] = (1955, 1975)
    db_path: Path = field(default_factory=lambda: DEFAULT_DB_PATH)

    # -- public ------------------------------------------------------------

    def to_features(
        self,
        *,
        socioeconomic: bool = False,
        dedup: str | None = "FormularId",
    ) -> pd.DataFrame:
        """Materialise the per-building feature DataFrame.

        Parameters
        ----------
        socioeconomic:
            If True, attach SCB population density / RegSO / income.
            Requires ``kommunkod`` and a local SCB gpkg.
        dedup:
            Column name to deduplicate on (default ``"FormularId"``).
            Keeps the latest row per id, matching the EPC convention of
            ``IdHuvudadress DESC``.  Set to ``None`` to keep every row.
        """
        df = self._extract_epc()
        if dedup:
            n_before = len(df)
            df = df.sort_values("IdHuvudadress", ascending=False).drop_duplicates(
                subset=[dedup], keep="first"
            ).reset_index(drop=True)
            self._dedup_dropped = n_before - len(df)
        else:
            self._dedup_dropped = 0
        df = self._attach_footprints(df)
        if socioeconomic:
            df = self._attach_socioeconomic(df)
        return df

    def count(self) -> int:
        """Return the number of buildings matching the cohort filters."""
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            return con.execute(
                f"""
                SELECT COUNT(*) FROM epc
                WHERE EgenByggnadsKat = ?
                  AND IdKommun = ?
                  AND EgenAtemp > 0
                  AND EgiEnergiPrestanda > 0
                  AND EgenNybyggAr BETWEEN ? AND ?
                """,
                [self.category, self.kommun_name, *self.year_range],
            ).fetchone()[0]

    # -- internals ---------------------------------------------------------

    def _extract_epc(self) -> pd.DataFrame:
        ymin, ymax = self.year_range
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            df = con.execute(
                """
                SELECT
                    FormularId, IdFastBet, IdHusnr, IdAdr, IdHuvudadress,
                    EgenNybyggAr        AS byggar,
                    EgenAtemp           AS atemp,
                    EgenAntalPlan       AS floors,
                    EgenAntalKallarplan AS basement_floors,
                    EgenAntalBolgh      AS apartments,
                    EgenAvarmgarage     AS garage_area,
                    EgenAtempBostad     AS atemp_bostad_pct,
                    EgiEnergiPrestanda  AS ep,
                    EgiSumma1           AS energy_summa1,
                    EgiVVBered          AS dhw_total,
                    EgiFastighet        AS fastighetsel,
                    EgiHushall          AS hushallsel,
                    EgiKomfort          AS comfort_cooling,
                    EgiSumma2           AS energy_summa2,
                    EgiFjarrvarme       AS fjv_kwh,
                    EgiOlja             AS olja_kwh,
                    EgiGas              AS gas_kwh,
                    EgiElVatten         AS el_vatten_kwh,
                    EgiElDirekt         AS el_direkt_kwh,
                    EgiPumpMark         AS pump_mark_kwh,
                    EgiPumpFranluft     AS pump_franluft_kwh,
                    EgiPumpLuftLuft     AS pump_luft_luft_kwh,
                    EgiPumpLuftVatten   AS pump_luft_vatten_kwh,
                    EgiFjarrvarmeVV         AS fjv_vv_kwh,
                    EgiFjarrvarmeUPPV       AS fjv_uppv_kwh,
                    EgiVersion              AS epc_version,
                    EgiNormKorrGD           AS normkorr_gd,
                    EgiElVattenUPPV         AS el_vatten_uppv_kwh,
                    EgiElDirektUPPV         AS el_direkt_uppv_kwh,
                    EgiElVV                 AS el_vv_kwh,
                    EgiPumpMarkUPPV         AS pump_mark_uppv_kwh,
                    EgiPumpFranluftUPPV     AS pump_franluft_uppv_kwh,
                    EgiPumpLuftLuftUPPV     AS pump_luft_luft_uppv_kwh,
                    EgiPumpLuftVattenUPPV   AS pump_luft_vatten_uppv_kwh,
                    VentTypFTX              AS vent_ftx,
                    VentTypFT           AS vent_ft,
                    VentTypF            AS vent_f,
                    VentTypSjalvdrag    AS vent_s,
                    AtgUtfordaIsolTak       AS reno_roof,
                    AtgUtfordaIsolVagg      AS reno_wall,
                    AtgUtfordaIsolMark      AS reno_ground,
                    AtgUtfordaByteFonster   AS reno_window_replace,
                    AtgUtfordaKompFonster   AS reno_window_add,
                    AtgUtfordaTatFonster    AS reno_window_seal,
                    AtgUtfordaByteVent      AS reno_vent_replace,
                    AtgUtfordaAterVent      AS reno_heat_recovery,
                    AtgUtfordaJustVarme     AS reno_heating_adjust,
                    AtgUtfordaByteVarmepump AS reno_heat_pump,
                    EgiEnergiklass      AS energy_class
                FROM epc
                WHERE EgenByggnadsKat = ?
                  AND IdKommun = ?
                  AND EgenAtemp > 0
                  AND EgiEnergiPrestanda > 0
                  AND EgenNybyggAr BETWEEN ? AND ?
                """,
                [self.category, self.kommun_name, ymin, ymax],
            ).fetchdf()

        # Ventilation: collapse the four boolean columns to a single label.
        def _vent(row):
            if row["vent_ftx"] == "Ja": return "FTX"
            if row["vent_ft"] == "Ja":  return "FT"
            if row["vent_f"] == "Ja":   return "F"
            if row["vent_s"] == "Ja":   return "S"
            return "Unknown"
        df["ventilation"] = df.apply(_vent, axis=1)

        reno_cols = [c for c in df.columns if c.startswith("reno_")]
        for c in reno_cols:
            df[c] = (df[c] == "Ja").astype(int)
        df["reno_envelope"] = (
            df["reno_roof"] | df["reno_wall"] | df["reno_ground"]
            | df["reno_window_replace"] | df["reno_window_add"]
        ).astype(int)
        df["reno_ventilation"] = (df["reno_vent_replace"] | df["reno_heat_recovery"]).astype(int)
        df["renovated"] = (df[reno_cols].sum(axis=1) > 0).astype(int)

        df["atemp_per_apt"] = np.where(
            df["apartments"] > 0, df["atemp"] / df["apartments"], np.nan
        )
        df["garage_area"] = df["garage_area"].fillna(0)
        df["garage_pct"] = np.where(
            df["atemp"] > 0, df["garage_area"] / df["atemp"] * 100, 0
        )
        df["residential_pct"] = df["atemp_bostad_pct"].fillna(100).clip(0, 100)
        df["heating_intensity"] = np.where(
            df["atemp"] > 0, df["energy_summa1"] / df["atemp"], np.nan
        )
        df["dhw_share"] = np.where(
            df["energy_summa2"] > 0, df["dhw_total"] / df["energy_summa2"], np.nan
        )
        df["fastighetsel_share"] = np.where(
            df["energy_summa2"] > 0, df["fastighetsel"] / df["energy_summa2"], np.nan
        )

        # Post-2019 EPCs (BFS 2018:11) populate only the *_UPPV / *_VV split,
        # leaving the legacy combined Egi{Carrier} columns at 0/NULL.  Look at
        # *_uppv_kwh first (heating-only carrier energy) and fall back to the
        # legacy column for pre-2019 records.
        def _heat(row):
            def hot(*cols):
                return any(
                    pd.notna(row.get(c)) and row.get(c) > 0 for c in cols
                )
            if hot("fjv_uppv_kwh", "fjv_kwh"):                               return "Fjv"
            if hot("pump_mark_uppv_kwh", "pump_mark_kwh"):                   return "GHP"
            if hot("pump_franluft_uppv_kwh", "pump_franluft_kwh"):           return "FVP"
            if hot("pump_luft_vatten_uppv_kwh", "pump_luft_vatten_kwh"):     return "ALWHP"
            if hot("pump_luft_luft_uppv_kwh", "pump_luft_luft_kwh"):         return "AAHP"
            if hot("el_vatten_uppv_kwh", "el_vatten_kwh"):                   return "ElVatten"
            if hot("el_direkt_uppv_kwh", "el_direkt_kwh"):                   return "ElDirekt"
            if hot("olja_kwh"):                                              return "Olja"
            return "Other"
        df["heating_system"] = df.apply(_heat, axis=1)

        # ---------------------------------------------------------------
        # Delivered EP correction — BFS 2018:11 (effective 2019) changed
        # EgiEnergiPrestanda from delivered kWh/m² to a primary-energy
        # index.  Rebuild delivered EP from the carrier _UPPV (heating)
        # and _VV (DHW) columns so calibration targets match what
        # EnergyPlus actually models.
        # ---------------------------------------------------------------
        def _c(*cols: str) -> pd.Series:
            return sum(df[c].fillna(0.0) for c in cols)  # type: ignore[return-value]

        heating_uppv = _c(
            "fjv_uppv_kwh", "el_vatten_uppv_kwh", "el_direkt_uppv_kwh",
            "pump_mark_uppv_kwh", "pump_franluft_uppv_kwh",
            "pump_luft_luft_uppv_kwh", "pump_luft_vatten_uppv_kwh",
        )
        dhw_vv = _c("fjv_vv_kwh", "el_vv_kwh")
        normkorr = df["normkorr_gd"].fillna(1.0)
        atemp = df["atemp"].clip(lower=1.0)
        ep_post = (
            heating_uppv * normkorr + dhw_vv + df["fastighetsel"].fillna(0.0)
        ) / atemp
        in_range = (ep_post >= 5.0) & (ep_post <= 600.0)
        ep_post = np.where(in_range, ep_post, df["ep"])
        is_post2019 = df["epc_version"].fillna(0) >= 2019
        df["ep_delivered"] = np.where(is_post2019, ep_post, df["ep"])
        # Override ep so downstream calibration targets use delivered energy
        df["ep"] = df["ep_delivered"]

        def _era(yr):
            if yr < 1940:  return "<1940"
            if yr < 1960:  return "1940-1959"
            if yr < 1970:  return "1960-1969"
            if yr < 1980:  return "1970-1979"
            if yr < 1990:  return "1980-1989"
            if yr < 2000:  return "1990-1999"
            return "2000+"
        df["era"] = df["byggar"].apply(_era)
        df["is_1960s"] = ((df["byggar"] >= 1960) & (df["byggar"] <= 1969)).astype(int)
        df.drop(columns=["vent_ftx", "vent_ft", "vent_f", "vent_s"], inplace=True)
        return df

    def _attach_footprints(self, df: pd.DataFrame) -> pd.DataFrame:
        """Project WGS-84 footprints to SWEREF99 TM and aggregate per FormularId."""
        from pyproj import Transformer
        import shapely.wkt as _swkt
        from shapely.geometry import Polygon as _ShPoly, MultiPolygon as _ShMulti

        ymin, ymax = self.year_range
        tx = Transformer.from_crs("EPSG:4326", "EPSG:3006", always_xy=True)

        with duckdb.connect(str(self.db_path), read_only=True) as con:
            con.execute("LOAD spatial;")
            rows = con.execute(
                """
                SELECT f.FormularId, ST_AsText(ST_GeomFromWKB(f.geom)) AS wkt
                FROM footprints f
                LEFT JOIN (
                    SELECT * FROM epc
                    QUALIFY ROW_NUMBER() OVER (
                        PARTITION BY FormularId ORDER BY IdHuvudadress DESC
                    ) = 1
                ) e ON f.FormularId = e.FormularId
                WHERE e.EgenByggnadsKat = ?
                  AND e.IdKommun = ?
                  AND e.EgenAtemp > 0
                  AND e.EgiEnergiPrestanda > 0
                  AND e.EgenNybyggAr BETWEEN ? AND ?
                """,
                [self.category, self.kommun_name, ymin, ymax],
            ).fetchdf()

        records = []
        for _, row in rows.iterrows():
            wkt = row["wkt"]
            if wkt is None:
                continue
            try:
                geom = _swkt.loads(wkt)
            except Exception:
                continue
            polys = list(geom.geoms) if isinstance(geom, _ShMulti) else [geom]
            for poly in polys:
                if not isinstance(poly, _ShPoly) or poly.is_empty:
                    continue
                ext_lonlat = list(poly.exterior.coords)
                if len(ext_lonlat) < 4:
                    continue
                pts_m = [tx.transform(lon, lat) for lon, lat in ext_lonlat[:-1]]
                proj_poly = _ShPoly(pts_m)
                if not proj_poly.is_valid or proj_poly.area <= 0:
                    continue
                records.append({
                    "FormularId": row["FormularId"],
                    "area": proj_poly.area,
                    "perim": proj_poly.length,
                    "centroid_e": proj_poly.centroid.x,
                    "centroid_n": proj_poly.centroid.y,
                })

        if not records:
            df["fp_area"] = np.nan
            df["fp_perimeter"] = np.nan
            df["n_footprints"] = 0
            df["fp_compactness"] = np.nan
            df["fp_slenderness"] = np.nan
            df["centroid_e"] = np.nan
            df["centroid_n"] = np.nan
            df["derived_volume"] = np.nan
            df["derived_atemp"] = np.nan
            return df

        df_fp = pd.DataFrame(records)
        agg = (
            df_fp.groupby("FormularId")
            .apply(
                lambda g: pd.Series({
                    "fp_area": g["area"].sum(),
                    "fp_perimeter": g["perim"].sum(),
                    "n_footprints": len(g),
                    "centroid_e": (g["centroid_e"] * g["area"]).sum() / g["area"].sum(),
                    "centroid_n": (g["centroid_n"] * g["area"]).sum() / g["area"].sum(),
                }),
                include_groups=False,
            )
            .reset_index()
        )
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

        df = df.merge(agg, on="FormularId", how="left")
        df["derived_volume"] = df["fp_area"] * df["floors"] * STOREY_HEIGHT
        df["derived_atemp"] = df["fp_area"] * df["floors"] * 0.85
        return df

    def _attach_socioeconomic(self, df: pd.DataFrame) -> pd.DataFrame:
        """Optional SCB joins (population density, RegSO, median income).

        Delegates to ``EDA/step_2_scb_socioeconomic.py`` so changes to the
        SCB API/WFS only need to be made in one place.  Requires
        ``kommunkod`` and a local ``EDA/befolkning_1km_2025.gpkg``.
        """
        if self.kommunkod is None:
            raise ValueError("Cohort.kommunkod required for socioeconomic=True")

        # Lazy import — pulls in geopandas + requests.
        import sys
        eda_dir = Path(__file__).resolve().parents[2] / "EDA"
        if str(eda_dir) not in sys.path:
            sys.path.insert(0, str(eda_dir))
        from step_2_scb_socioeconomic import (  # type: ignore[import-not-found]
            fetch_population_for_buildings,
            fetch_regso_codes,
            fetch_income_per_regso,
            INCOME_YEAR,
        )

        df = fetch_population_for_buildings(df)
        try:
            df = fetch_regso_codes(df, kommunkod=self.kommunkod)
            unique_regso = df["regso_code"].dropna().unique().tolist()
            if unique_regso:
                income_map = fetch_income_per_regso(unique_regso)
                df["income_median"] = df["regso_code"].map(income_map)
            else:
                df["income_median"] = np.nan
        except Exception as exc:  # noqa: BLE001 — surface to caller, keep df usable
            print(f"WARNING: socio-economic fetch failed ({exc!r})")
            df["regso_code"] = None
            df["regso_name"] = None
            df["income_median"] = np.nan
        return df


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------

def gothenburg_1960s(**overrides) -> Cohort:
    """Pre-canned cohort: Göteborg MFH 1955–1975."""
    return Cohort(kommun_name="Göteborg", kommunkod="1480", **overrides)


def uddevalla_1960s(**overrides) -> Cohort:
    """Pre-canned cohort: Uddevalla MFH 1955–1975 (paper baseline)."""
    return Cohort(kommun_name="Uddevalla", kommunkod="1485", **overrides)


def kommun_kommuner_1960s(kommuner: Iterable[tuple[str, str]]) -> dict[str, Cohort]:
    """Build a dict of name → Cohort for several kommuner at once."""
    return {name: Cohort(kommun_name=name, kommunkod=code) for name, code in kommuner}
