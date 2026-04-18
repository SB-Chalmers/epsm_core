"""
Step 1 — Extract all Uddevalla multifamily housing (flerbostadshus) from DuckDB.

Pulls every EPC record for MFH in Uddevalla, engineers features relevant to
energy performance, encodes categorical variables, and exports a clean
analysis-ready DataFrame to CSV.

Features extracted:
  - Building geometry:  Atemp, floors, basement floors, apartments, garage area
  - Energy performance: EP (energiprestanda), heating, DHW, building services,
                        household electricity, comfort cooling, total energy
  - Heating system flags: district heat, oil, gas, electric, heat pumps
  - Ventilation system:  FTX, FT, F, Självdrag (natural draft)
  - Renovation measures: roof/wall insulation, window replacement, vent upgrade
  - Derived features:    heating_intensity, dhw_share, fastighetsel_share,
                         atemp_per_apt, era category, residential %
"""
import duckdb
import pandas as pd
import numpy as np
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "epc_sweden.duckdb"
OUT_PATH = Path(__file__).resolve().parent / "uddevalla_mfh_features.csv"


def extract():
    con = duckdb.connect(str(DB_PATH), read_only=True)

    df = con.execute("""
        SELECT
            -- identifiers
            FormularId,
            IdFastBet,
            IdHusnr,
            IdAdr,
            IdHuvudadress,

            -- building geometry
            EgenNybyggAr        AS byggar,
            EgenAtemp           AS atemp,
            EgenAntalPlan       AS floors,
            EgenAntalKallarplan AS basement_floors,
            EgenAntalBolgh      AS apartments,
            EgenAvarmgarage     AS garage_area,
            EgenAtempBostad     AS atemp_bostad_pct,

            -- energy performance
            EgiEnergiPrestanda  AS ep,
            EgiSumma1           AS energy_summa1,
            EgiVVBered          AS dhw_total,
            EgiFastighet        AS fastighetsel,
            EgiHushall          AS hushallsel,
            EgiKomfort          AS comfort_cooling,
            EgiSumma2           AS energy_summa2,

            -- heating sources (kWh)
            EgiFjarrvarme       AS fjv_kwh,
            EgiOlja             AS olja_kwh,
            EgiGas              AS gas_kwh,
            EgiElVatten         AS el_vatten_kwh,
            EgiElDirekt         AS el_direkt_kwh,
            EgiPumpMark         AS pump_mark_kwh,
            EgiPumpFranluft     AS pump_franluft_kwh,
            EgiPumpLuftLuft     AS pump_luft_luft_kwh,
            EgiPumpLuftVatten   AS pump_luft_vatten_kwh,

            -- DHW breakdown
            EgiFjarrvarmeVV     AS fjv_vv_kwh,
            EgiFjarrvarmeUPPV   AS fjv_uppv_kwh,

            -- ventilation system flags
            VentTypFTX          AS vent_ftx,
            VentTypFT           AS vent_ft,
            VentTypF            AS vent_f,
            VentTypSjalvdrag    AS vent_s,

            -- renovation measures performed
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

            -- energy class
            EgiEnergiklass      AS energy_class

        FROM epc
        WHERE EgenByggnadsKat = 'Flerbostadshus'
          AND IdKommun = 'Uddevalla'
          AND EgenAtemp > 0
          AND EgiEnergiPrestanda > 0
    """).fetchdf()

    con.close()

    print(f"Raw records: {len(df)}")

    # --- Encode ventilation system as single categorical ---
    def classify_vent(row):
        if row["vent_ftx"] == "Ja":
            return "FTX"
        elif row["vent_ft"] == "Ja":
            return "FT"
        elif row["vent_f"] == "Ja":
            return "F"
        elif row["vent_s"] == "Ja":
            return "S"
        return "Unknown"

    df["ventilation"] = df.apply(classify_vent, axis=1)

    # --- Encode renovation flags as binary 0/1 ---
    reno_cols = [c for c in df.columns if c.startswith("reno_")]
    for c in reno_cols:
        df[c] = (df[c] == "Ja").astype(int)

    # Composite: any envelope renovation
    df["reno_envelope"] = (
        (df["reno_roof"] | df["reno_wall"] | df["reno_ground"] |
         df["reno_window_replace"] | df["reno_window_add"])
    ).astype(int)

    # Composite: any ventilation renovation
    df["reno_ventilation"] = (
        (df["reno_vent_replace"] | df["reno_heat_recovery"])
    ).astype(int)

    # Any renovation at all
    df["renovated"] = (df[reno_cols].sum(axis=1) > 0).astype(int)

    # --- Derived features ---
    df["atemp_per_apt"] = np.where(
        df["apartments"] > 0,
        df["atemp"] / df["apartments"],
        np.nan
    )
    # Fill NaN garage_area with 0 (NULL means no heated garage)
    df["garage_area"] = df["garage_area"].fillna(0)
    df["garage_pct"] = np.where(
        df["atemp"] > 0,
        df["garage_area"] / df["atemp"] * 100,
        0
    )
    df["residential_pct"] = df["atemp_bostad_pct"].fillna(100).clip(0, 100)

    # Heating intensity (heating kWh / m²) — use Summa1 which is total heating
    df["heating_intensity"] = np.where(
        df["atemp"] > 0,
        df["energy_summa1"] / df["atemp"],
        np.nan
    )
    # DHW share of total
    df["dhw_share"] = np.where(
        df["energy_summa2"] > 0,
        df["dhw_total"] / df["energy_summa2"],
        np.nan
    )
    # Fastighetsel share
    df["fastighetsel_share"] = np.where(
        df["energy_summa2"] > 0,
        df["fastighetsel"] / df["energy_summa2"],
        np.nan
    )

    # Heating system classification
    def classify_heating(row):
        if pd.notna(row["fjv_kwh"]) and row["fjv_kwh"] > 0:
            return "Fjv"
        elif pd.notna(row["pump_mark_kwh"]) and row["pump_mark_kwh"] > 0:
            return "GHP"
        elif pd.notna(row["pump_franluft_kwh"]) and row["pump_franluft_kwh"] > 0:
            return "FVP"
        elif pd.notna(row["el_vatten_kwh"]) and row["el_vatten_kwh"] > 0:
            return "ElVatten"
        elif pd.notna(row["el_direkt_kwh"]) and row["el_direkt_kwh"] > 0:
            return "ElDirekt"
        elif pd.notna(row["olja_kwh"]) and row["olja_kwh"] > 0:
            return "Olja"
        return "Other"

    df["heating_system"] = df.apply(classify_heating, axis=1)

    # Era classification
    def classify_era(yr):
        if yr < 1940:
            return "<1940"
        elif yr < 1960:
            return "1940-1959"
        elif yr < 1970:
            return "1960-1969"
        elif yr < 1980:
            return "1970-1979"
        elif yr < 1990:
            return "1980-1989"
        elif yr < 2000:
            return "1990-1999"
        return "2000+"

    df["era"] = df["byggar"].apply(classify_era)

    # Is 1960s flag
    df["is_1960s"] = ((df["byggar"] >= 1960) & (df["byggar"] <= 1969)).astype(int)

    # Drop raw ventilation flag columns (now encoded)
    df.drop(columns=["vent_ftx", "vent_ft", "vent_f", "vent_s"], inplace=True)

    # --- Summary stats ---
    print(f"\nClean records: {len(df)}")
    print(f"\nEra distribution:")
    print(df["era"].value_counts().sort_index().to_string())
    print(f"\nVentilation distribution:")
    print(df["ventilation"].value_counts().to_string())
    print(f"\nHeating system distribution:")
    print(df["heating_system"].value_counts().to_string())
    print(f"\nRenovated: {df['renovated'].sum()} / {len(df)} ({df['renovated'].mean()*100:.0f}%)")
    print(f"\n1960s buildings: {df['is_1960s'].sum()}")
    print(f"\nEP statistics (all eras):")
    print(df["ep"].describe().to_string())
    print(f"\nEP statistics (1960s only):")
    print(df.loc[df["is_1960s"] == 1, "ep"].describe().to_string())

    # --- Save ---
    df.to_csv(OUT_PATH, index=False)
    print(f"\nSaved to {OUT_PATH}")
    print(f"Shape: {df.shape}")
    print(f"Columns: {list(df.columns)}")

    return df


if __name__ == "__main__":
    extract()
