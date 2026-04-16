from __future__ import annotations

import argparse
from pathlib import Path

from .building_params import load_config
from .runner import run


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a building from a footprint and run EnergyPlus",
    )
    parser.add_argument("--config", default="config.json", help="Path to config JSON")
    parser.add_argument("--name", default="building", help="Building / case name")
    parser.add_argument("--dry-run", action="store_true", help="Generate IDF only, skip EnergyPlus")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    cfg.idf_dir.mkdir(parents=True, exist_ok=True)
    cfg.output_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        from .idf_builder import write_idf

        idf_path = cfg.idf_dir / "in.idf"
        write_idf(idf_path, args.name, cfg.footprint_pts, cfg.building)
        print(f"IDF written to {idf_path}")
        return

    results = run(
        name=args.name,
        footprint_pts=cfg.footprint_pts,
        params=cfg.building,
        weather_file=cfg.weather_file,
        idf_dir=cfg.idf_dir,
        output_dir=cfg.output_dir,
    )

    print(f"Heating: {results['heating_kwh']:.1f} kWh")
    print(f"Cooling: {results['cooling_kwh']:.1f} kWh")
    print(f"Site:    {results['site_kwh']:.1f} kWh")
    print(f"Output:  {cfg.output_dir}")


if __name__ == "__main__":
    main()
