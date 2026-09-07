"""Inspect simple, courtyard or unequal-wing geometry without an engine."""

import argparse

from epsm_core import BuildingPart, Footprint, GeometrySpec, ZoningSpec


def example_geometry(shape="courtyard", zoning="perimeter_core"):
    footprint = Footprint.rectangle(30, 20)
    if shape == "courtyard":
        footprint = Footprint(
            exterior=((0, 0), (40, 0), (40, 30), (0, 30)),
            holes=(((12, 10), (28, 10), (28, 20), (12, 20)),),
        )
    geometry = GeometrySpec.from_footprint(
        footprint, storeys=3, storey_height_m=3, zoning=ZoningSpec(mode=zoning)
    )
    if shape == "wings":
        geometry = geometry.updated(
            parts=(
                *geometry.parts,
                BuildingPart(
                    identifier="wing",
                    footprint=Footprint(exterior=((30, 0), (42, 0), (42, 20), (30, 20))),
                    storey_elevations_m=(0, 3, 6),
                ),
            )
        )
    return geometry


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--shape", choices=("rectangle", "courtyard", "wings"), default="courtyard")
    p.add_argument(
        "--zoning",
        choices=("whole_building", "per_storey", "perimeter_core"),
        default="perimeter_core",
    )
    p.add_argument("--output", default="output/geometry")
    p.add_argument("--headless", action="store_true")
    args = p.parse_args()
    with example_geometry(args.shape, args.zoning).view(
        args.output, launch_browser=not args.headless
    ) as view:
        print(view.url)
        if not args.headless:
            input("Press Enter to stop the preview. ")
