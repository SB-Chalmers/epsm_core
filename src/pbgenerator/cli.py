from __future__ import annotations

import argparse
from pathlib import Path

from .building import Building
from .building_params import load_config
from .location import Location, WeatherSite


def build_from_config(cfg, name: str) -> Building:
    """Construct a :class:`Building` aggregate from a loaded :class:`Config`."""
    weather = WeatherSite(epw_path=str(cfg.weather_file))
    location = Location.hypothetical_site(weather=weather)
    return Building(name=name, params=cfg.building,
                    footprint_pts=cfg.footprint_pts, location=location)


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

    building = build_from_config(cfg, args.name)

    if args.dry_run:
        idf_path = cfg.idf_dir / "in.idf"
        building.write_idf(idf_path)
        print(f"IDF written to {idf_path}")
        return

    results = building.simulate(idf_dir=cfg.idf_dir, output_dir=cfg.output_dir)

    print(f"Heating: {results.heating}")
    print(f"Cooling: {results.cooling}")
    print(f"Site:    {results.site_energy}")
    if results.site_eui is not None:
        print(f"Site EUI:{results.site_eui}")
    print(f"Output:  {cfg.output_dir}")


if __name__ == "__main__":
    main()
