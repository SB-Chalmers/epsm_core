"""Freeze the saved MFH diagnostic sample; no database or source modifications."""

import argparse
import hashlib
import json
from pathlib import Path

from shapely import from_wkt
from shapely.affinity import rotate, translate
from shapely.geometry import Polygon, box, shape

from epsm_core.preparation import prepare_geometry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    raw = args.source.read_bytes()
    source = json.loads(raw)
    cases = []

    def add(identifier, group, polygon, provenance):
        result = prepare_geometry(polygon)
        cases.append(dict(
            id=identifier, group=group, provenance=provenance,
            source_sha256=hashlib.sha256(polygon.wkb).hexdigest(),
            preparation=result.artifact(
                source_crs="caller-supplied planar metres",
                target_crs="caller-supplied planar metres", transformation="identity"),
        ))

    for row in source["buildings"]:
        if "MF" not in json.loads(row["selected_groups"]):
            continue
        add(row["building_id"], "mfh", from_wkt(row["geometry_wkt"]), dict(
            source_file=args.source.name, source_file_sha256=hashlib.sha256(raw).hexdigest(),
            selection=source["method"], building_id=row["building_id"],
            selected_groups=json.loads(row["selected_groups"]),
        ))
    synthetics = {
        "rectangle_450": box(0, 0, 30, 15),
        "square_867": box(0, 0, 867 ** 0.5, 867 ** 0.5),
        "compact_400": box(0, 0, 20, 20),
        "slab_1120": box(0, 0, 80, 14),
        "small_64": box(0, 0, 8, 8),
        "narrow_225": box(0, 0, 45, 5),
        "shallow_notch": Polygon([(0, 0), (40, 0), (40, 14), (32, 14),
                                  (32, 12), (25, 12), (25, 14), (0, 14)]),
        "L_shape": Polygon([(0, 0), (30, 0), (30, 10), (10, 10), (10, 30), (0, 30)]),
        "courtyard": box(0, 0, 40, 40).difference(box(10, 10, 30, 30)),
        "rotated_rectangle_23": rotate(box(0, 0, 30, 15), 23, origin=(0, 0)),
        "grid_rotated_rectangle_23": translate(
            rotate(box(0, 0, 30, 15), 23, origin=(0, 0)), 320000, 6470000),
    }
    for name, polygon in synthetics.items():
        add(name, "synthetic", polygon, dict(source="constructed metric geometry"))
    for prefix in ("0181-72ce61a4", "0181-56f82588", "0181-10936640",
                   "0181-502707dc", "0181-6e095fa1"):
        path = next((root / "tests/fixtures/footprints").glob(prefix + "*.json"))
        payload = path.read_bytes()
        row = json.loads(payload)
        add(prefix, "regression", shape(row["source_geometry"]), dict(
            source_file=path.name, source_file_sha256=hashlib.sha256(payload).hexdigest(),
            historical_status=row["status"], residential_classification="unknown"))
    output = root / "tests/fixtures/mfh_layouts/corpus.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(
        version=1, description="Diagnostic MFH sample, synthetic and numerical regressions; not representative.",
        source_sample_sha256=hashlib.sha256(raw).hexdigest(), cases=cases,
    ), indent=2) + "\n")
    print(f"Saved {len(cases)} cases ({sum(c['group'] == 'mfh' for c in cases)} MFH) to {output}")


if __name__ == "__main__":
    main()
