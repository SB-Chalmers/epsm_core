"""Write inspectable custom or synthetic neighbouring buildings."""

import argparse
from pathlib import Path

from epsm_core import ContextBuilding, ContextSpec, Footprint, GeometrySpec, synthetic_context


def example_context(geometry, preset):
    if preset == "custom":
        return ContextSpec(
            buildings=(
                ContextBuilding(
                    identifier="neighbour",
                    height_m=18,
                    footprints=(Footprint(exterior=((0, -30), (30, -30), (30, -15), (0, -15))),),
                ),
            )
        )
    return synthetic_context(geometry, preset=preset)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--preset",
        choices=("custom", "rural", "urban_lowrise_dense", "urban_highrise_dense"),
        default="urban_lowrise_dense",
    )
    p.add_argument("--output", type=Path, default=Path("output/context"))
    args = p.parse_args()
    geometry = GeometrySpec.from_footprint(
        Footprint.rectangle(30, 20), storeys=3, storey_height_m=3
    )
    context = example_context(geometry, args.preset)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "context.json").write_text(context.model_dump_json(indent=2))
    with geometry.view(args.output, context=context, launch_browser=False) as view:
        print(f"Saved {len(context.buildings)} neighbours and viewer to {view.directory}")
