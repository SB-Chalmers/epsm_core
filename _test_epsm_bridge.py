"""Check: do EnergyPlus constructions match epsm_data U-values?"""
from pathlib import Path
from collections import defaultdict

from pbgenerator.constructions import CONSTRUCTION_SETS, get_construction_set
from pbgenerator.epc_io import load_footprints, load_epc_metadata, detect_ventilation_system
from pbgenerator.archetypes import cmf_1960
from pbgenerator.idf_builder import build_model

# ---- 1. Print epsm_data U-values ----
print("=" * 60)
print("EPSM_DATA U-VALUES (before model build)")
print("=" * 60)
cs = get_construction_set("CMF_1960_1")
print(f"  wall:       U={cs.wall.u_factor:.3f}")
print(f"  roof:       U={cs.roof.u_factor:.3f}")
print(f"  floor:      U={cs.floor.u_factor:.3f}")
for attr in ["top_floor", "intermediate_floor", "ground_floor",
             "basement_floor", "basement_wall"]:
    obj = getattr(cs, attr, None)
    if obj:
        print(f"  {attr}: U={obj.u_factor:.3f}")
print(f"  window:     U={cs.window.u_factor:.3f}")
print()

# ---- 2. Build Honeybee model (no simulation) ----
EPC_FORMULAR_ID = 1033661
fp = load_footprints(fastighetsbeteckning="ÄGIR 17", husnummer=1)[0]
epc = load_epc_metadata(EPC_FORMULAR_ID)
vent_sys = detect_ventilation_system(EPC_FORMULAR_ID)

params = cmf_1960(
    num_floors=epc["num_floors"],
    ventilation_system=vent_sys,
    num_basement_floors=epc["num_basement_floors"],
    cold_attic=True,
)

model = build_model("fjallvagen28", fp.footprint_pts, params)

# ---- 3. Inspect constructions on each face ----
print("=" * 60)
print("HONEYBEE MODEL — CONSTRUCTIONS ON FACES")
print("=" * 60)

face_data = defaultdict(list)
for room in model.rooms:
    for face in room.faces:
        ftype = type(face.type).__name__
        bc = type(face.boundary_condition).__name__
        cons = face.properties.energy.construction
        if cons is not None:
            u = cons.u_factor
            cid = cons.identifier
        else:
            u = None
            cid = "None"
        key = (ftype, bc, cid)
        face_data[key].append((room.identifier, face.identifier, u))

for (ftype, bc, cid), faces in sorted(face_data.items()):
    u = faces[0][2]
    u_str = f"U={u:.3f}" if u is not None else "U=N/A"
    print(f"\n{ftype} | {bc} | {cid} | {u_str} | {len(faces)} faces")
    for room_id, face_id, _ in faces[:3]:
        print(f"    {room_id} → {face_id}")
    if len(faces) > 3:
        print(f"    ... +{len(faces)-3} more")

# ---- 4. Also dump the IDF construction blocks to verify ----
print()
print("=" * 60)
print("IDF CONSTRUCTION BLOCKS (from Honeybee to_idf)")
print("=" * 60)

seen = set()
for room in model.rooms:
    for face in room.faces:
        cons = face.properties.energy.construction
        if cons is not None and cons.identifier not in seen:
            seen.add(cons.identifier)
            try:
                u = cons.u_factor
                print(f"\n--- {cons.identifier} (U={u:.3f}) ---")
                if hasattr(cons, 'layers'):
                    for i, layer in enumerate(cons.layers):
                        if hasattr(layer, 'thickness'):
                            print(f"  [{i}] {layer.identifier}: "
                                  f"t={layer.thickness:.4f}m, "
                                  f"k={layer.conductivity:.4f}, "
                                  f"rho={layer.density:.1f}, "
                                  f"cp={layer.specific_heat:.1f}")
                        else:
                            print(f"  [{i}] {layer.identifier}: "
                                  f"U={layer.u_factor:.3f}, SHGC={layer.solar_heat_gain_coefficient:.3f}")
            except Exception as e:
                print(f"\n--- {cons.identifier} (error: {e}) ---")
