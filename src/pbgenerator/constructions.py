from __future__ import annotations

import logging
from dataclasses import dataclass

from honeybee.boundarycondition import Ground, Outdoors, Surface as SurfaceBC
from honeybee.room import Room
from honeybee_energy.construction.opaque import OpaqueConstruction
from honeybee_energy.construction.window import WindowConstruction
from honeybee_energy.material.opaque import EnergyMaterial, EnergyMaterialNoMass
from honeybee_energy.material.glazing import EnergyWindowMaterialSimpleGlazSys

from .building_params import BuildingParams

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Construction-set data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConstructionSetDef:
    """Defines constructions for all surface types.

    Only ``wall``, ``roof``, ``floor``, and ``window`` are required.
    Specific constructions override the general ones when present;
    ``apply_constructions`` falls back to a sensible default when a
    specific field is *None*.

    Upstream mapping::

        ROOF                    → roof
        TOP_FLOOR               → top_floor
        INTERMEDIATE_FLOOR      → intermediate_floor
        GROUND_FLOOR            → ground_floor  (falls back to floor)
        BASEMENT_FLOOR          → basement_floor
        EXT_WALL                → wall
        EXT_WALL_LOW            → ext_wall_low
        EXT_WALL_MEDIUM         → ext_wall_medium
        EXT_WALL_HIGH           → ext_wall_high
        BASEMENT_WALL           → basement_wall
        INT_WALL_LOADBEARING    → int_wall_loadbearing
        INT_WALL_NONLOADBEARING → int_wall_nonloadbearing
    """
    # Required (general fallbacks)
    wall: OpaqueConstruction
    roof: OpaqueConstruction
    floor: OpaqueConstruction
    window: WindowConstruction
    # Optional (specific overrides)
    top_floor: OpaqueConstruction | None = None
    intermediate_floor: OpaqueConstruction | None = None
    ground_floor: OpaqueConstruction | None = None
    basement_floor: OpaqueConstruction | None = None
    basement_wall: OpaqueConstruction | None = None
    ext_wall_low: OpaqueConstruction | None = None
    ext_wall_medium: OpaqueConstruction | None = None
    ext_wall_high: OpaqueConstruction | None = None
    int_wall_loadbearing: OpaqueConstruction | None = None
    int_wall_nonloadbearing: OpaqueConstruction | None = None

    @classmethod
    def from_epsm_archetype(cls, archetype) -> ConstructionSetDef:
        """Build a ConstructionSetDef from an epsm_data BuildingArchetype.

        Maps each epsm_data Element (keyed by BuildingElement role) to a
        honeybee OpaqueConstruction.  Composite layers use area-weighted
        effective properties (parallel-path method).
        """
        from epsm_data.domain.enums import BuildingElement as BE

        _ROLE_MAP = {
            BE.EXT_WALL:                "wall",
            BE.EXT_WALL_LOW:            "ext_wall_low",
            BE.EXT_WALL_MEDIUM:         "ext_wall_medium",
            BE.EXT_WALL_HIGH:           "ext_wall_high",
            BE.ROOF:                    "roof",
            BE.TOP_FLOOR:               "top_floor",
            BE.INTERMEDIATE_FLOOR:      "intermediate_floor",
            BE.GROUND_FLOOR:            "ground_floor",
            BE.BASEMENT_FLOOR:          "basement_floor",
            BE.BASEMENT_WALL:           "basement_wall",
            BE.INT_WALL_LOADBEARING:    "int_wall_loadbearing",
            BE.INT_WALL_NONLOADBEARING: "int_wall_nonloadbearing",
        }

        constructions: dict[str, OpaqueConstruction] = {}
        aid = archetype.archetype_id

        for role, elem in archetype.construction_set.elements.items():
            field = _ROLE_MAP.get(role)
            if field is None:
                continue

            # Skip WindowElement — handled separately below
            if not hasattr(elem, 'components'):
                continue

            cons_id = f"{aid}_{role.value}"
            hb_layers: list[EnergyMaterial] = []
            layer_idx = 0
            for comp in elem.components:
                for slot in comp.layers:
                    layer = slot.layer
                    if layer.is_composite:
                        k = sum(m.material.conductivity * m.area_fraction
                                for m in layer.materials)
                        rho = sum(m.material.density * m.area_fraction
                                  for m in layer.materials)
                        cp = sum(m.material.specific_heat * m.area_fraction
                                 for m in layer.materials)
                        rough = layer.materials[0].material.roughness.value
                        name = f"{layer.layer_code}_eff"
                    else:
                        mat = layer.materials[0].material
                        k, rho, cp = mat.conductivity, mat.density, mat.specific_heat
                        rough = mat.roughness.value
                        name = mat.name

                    hb_layers.append(EnergyMaterial(
                        f"{cons_id}_{layer_idx}_{name}", layer.thickness, k, rho, cp,
                        roughness=rough,
                    ))
                    layer_idx += 1

            constructions[field] = OpaqueConstruction(cons_id, hb_layers)

        # Require wall, roof, floor — use fallbacks
        wall = (constructions.get("wall")
                or constructions.get("ext_wall_low")
                or constructions.get("ext_wall_medium")
                or constructions.get("ext_wall_high"))
        roof = constructions.get("roof") or constructions.get("top_floor")
        floor = (constructions.get("ground_floor")
                 or constructions.get("basement_floor")
                 or constructions.get("floor"))

        if not all([wall, roof, floor]):
            missing = [n for n, v in [("wall", wall), ("roof", roof), ("floor", floor)] if not v]
            raise ValueError(
                f"Archetype '{aid}' is missing required elements: {missing}"
            )

        # Window — use archetype WindowElement if available, else BETSI 2-pane fallback
        win_elem = archetype.window
        u = win_elem.u_value if win_elem else 2.5
        shgc = win_elem.shgc if win_elem else 0.70
        vt = win_elem.vt if win_elem else 0.65
        window = _win(aid, u=u, shgc=shgc, vt=vt)

        return cls(
            wall=wall,
            roof=roof,
            floor=floor,
            window=window,
            **{k: v for k, v in constructions.items()
               if k not in ("wall", "roof", "floor")},
        )


# ---------------------------------------------------------------------------
# Material helpers
# ---------------------------------------------------------------------------

def _win(name: str, u: float, shgc: float, vt: float = 0.4) -> WindowConstruction:
    return WindowConstruction(f"{name}_WIN", [
        EnergyWindowMaterialSimpleGlazSys(f"{name}_GLAZ", u_factor=u, shgc=shgc, vt=vt),
    ])


# ---------------------------------------------------------------------------
# Construction-set registry  (populated by epsm_data auto-discovery)
# ---------------------------------------------------------------------------

CONSTRUCTION_SETS: dict[str, callable] = {}


def _load_epsm_archetypes() -> None:
    """Auto-discover epsm_data archetypes and register them."""
    try:
        from epsm_data import run_build_baseline
        from pathlib import Path

        epsm_root = Path(__file__).resolve().parents[3] / "EPSM_data"
        if not epsm_root.exists():
            epsm_root = Path.home() / "GitHub" / "EPSM_data"

        excel = epsm_root / "Data" / "Material_Database.xlsx"
        json_path = epsm_root / "Data" / "opaque_material.json"

        if not excel.exists() or not json_path.exists():
            logger.debug("epsm_data installed but data files not found — skipping auto-load")
            return

        result = run_build_baseline(excel, json_path)
        for arch in result.archetypes:
            aid = arch.archetype_id
            if aid not in CONSTRUCTION_SETS:
                # Bind arch in closure to avoid late-binding issues
                CONSTRUCTION_SETS[aid] = (lambda a: lambda: ConstructionSetDef.from_epsm_archetype(a))(arch)
                logger.info("Registered epsm_data archetype: %s", aid)

    except ImportError:
        logger.debug("epsm_data not installed — using built-in construction sets only")
    except Exception:
        logger.warning("Failed to load epsm_data archetypes", exc_info=True)


# Run auto-discovery at import time
_load_epsm_archetypes()


def get_construction_set(name: str) -> ConstructionSetDef:
    """Look up a construction set by name. Raises ValueError if not found."""
    factory = CONSTRUCTION_SETS.get(name)
    if factory is None:
        available = ", ".join(sorted(CONSTRUCTION_SETS))
        raise ValueError(
            f"Unknown construction set '{name}'. Available: {available}"
        )
    return factory()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_INTERIOR_FLOOR = OpaqueConstruction("INTERIOR_FLOOR_CONS", [
    EnergyMaterialNoMass("INTERIOR_R", 0.3, roughness="Rough"),
])

_INTERIOR_WALL = OpaqueConstruction("INTERIOR_WALL_CONS", [
    EnergyMaterialNoMass("INTERIOR_WALL_R", 0.3, roughness="Rough"),
])


def _degrade_for_thermal_bridges(
    construction: OpaqueConstruction, fraction: float,
) -> OpaqueConstruction:
    """Return a copy with U-value increased by *fraction* (e.g. 0.20 = +20%).

    Finds the insulation layer (highest R-value) and reduces its thickness
    so that U_new = (1 + fraction) × U_old.
    """
    if fraction <= 0:
        return construction

    layers = construction.materials
    total_r = sum(lyr.r_value for lyr in layers)
    if total_r <= 0:
        return construction

    # R reduction needed: R_old - R_old/(1+f) = R_old * f/(1+f)
    r_reduction = total_r * fraction / (1 + fraction)

    # Find the insulation layer (EnergyMaterial with highest R)
    ins_idx = None
    max_r = 0
    for i, lyr in enumerate(layers):
        if isinstance(lyr, EnergyMaterial) and lyr.r_value > max_r:
            max_r = lyr.r_value
            ins_idx = i

    if ins_idx is None or max_r <= r_reduction:
        return construction

    ins = layers[ins_idx]
    new_thickness = (ins.r_value - r_reduction) * ins.conductivity

    new_layers = []
    for i, lyr in enumerate(layers):
        if i == ins_idx:
            new_layers.append(EnergyMaterial(
                lyr.identifier + "_TB",
                new_thickness, lyr.conductivity, lyr.density, lyr.specific_heat,
                roughness=lyr.roughness,
            ))
        else:
            new_layers.append(lyr)

    return OpaqueConstruction(construction.identifier + "_TB", new_layers)


def apply_constructions(rooms: list[Room], params: BuildingParams) -> None:
    """Assign constructions to every face, using the most specific match.

    Face classification:

    *  **Wall + Ground BC** → ``basement_wall`` → ``wall``
    *  **Wall + Outdoors BC** → ``wall``
    *  **Wall + Surface BC** → ``int_wall_loadbearing`` → ``int_wall_nonloadbearing`` → lightweight fallback
    *  **RoofCeiling + Outdoors BC** → ``roof``
    *  **RoofCeiling + Surface BC (top room)** → ``top_floor`` → ``intermediate_floor`` → lightweight fallback
    *  **RoofCeiling + Surface BC** → ``intermediate_floor`` → lightweight fallback
    *  **Floor + Ground BC (basement)** → ``basement_floor`` → ``ground_floor`` → ``floor``
    *  **Floor + Ground BC (grade)** → ``ground_floor`` → ``floor``
    *  **Floor + Surface BC** → ``intermediate_floor`` → lightweight fallback
    *  **Floor + Outdoors BC** → ``floor``
    """
    cs = get_construction_set(params.construction_set)

    # Apply Sveby solar shading factor to window SHGC
    ssf = params.solar_shading_factor
    if 0 < ssf < 1.0:
        glaz = cs.window.materials[0]
        shaded_glaz = EnergyWindowMaterialSimpleGlazSys(
            f"{glaz.identifier}_shaded",
            u_factor=glaz.u_factor,
            shgc=glaz.shgc * ssf,
            vt=glaz.vt * ssf,
        )
        cs = ConstructionSetDef(
            **{k: (WindowConstruction(f"{cs.window.identifier}_shaded", [shaded_glaz])
                   if k == "window" else v)
               for k, v in cs.__dict__.items()}
        )

    # Apply thermal bridge surcharge to exterior constructions
    tb = params.thermal_bridge_fraction
    if tb > 0:
        cs = ConstructionSetDef(
            wall=_degrade_for_thermal_bridges(cs.wall, tb),
            roof=_degrade_for_thermal_bridges(cs.roof, tb),
            floor=_degrade_for_thermal_bridges(cs.floor, tb),
            window=cs.window,
            top_floor=_degrade_for_thermal_bridges(cs.top_floor, tb) if cs.top_floor else None,
            ground_floor=_degrade_for_thermal_bridges(cs.ground_floor, tb) if cs.ground_floor else None,
            basement_floor=_degrade_for_thermal_bridges(cs.basement_floor, tb) if cs.basement_floor else None,
            basement_wall=_degrade_for_thermal_bridges(cs.basement_wall, tb) if cs.basement_wall else None,
            intermediate_floor=cs.intermediate_floor,
            ext_wall_low=_degrade_for_thermal_bridges(cs.ext_wall_low, tb) if cs.ext_wall_low else None,
            ext_wall_medium=_degrade_for_thermal_bridges(cs.ext_wall_medium, tb) if cs.ext_wall_medium else None,
            ext_wall_high=_degrade_for_thermal_bridges(cs.ext_wall_high, tb) if cs.ext_wall_high else None,
            int_wall_loadbearing=cs.int_wall_loadbearing,
            int_wall_nonloadbearing=cs.int_wall_nonloadbearing,
        )

    # Determine top z of *conditioned* rooms (those whose RoofCeiling faces
    # are interzone, not Outdoors).  When cold_attic=True the attic rooms
    # have their ceiling exposed to Outdoors, pushing max_z above the
    # conditioned envelope.  Using only rooms with interzone ceilings ensures
    # the top conditioned floor gets ``top_floor`` instead of
    # ``intermediate_floor``.
    conditioned_max_zs = []
    for room in rooms:
        has_interzone_ceiling = any(
            type(f.type).__name__ == "RoofCeiling"
            and isinstance(f.boundary_condition, SurfaceBC)
            for f in room.faces
        )
        if has_interzone_ceiling or not any(
            type(f.type).__name__ == "RoofCeiling" for f in room.faces
        ):
            conditioned_max_zs.append(
                max(max(v.z for v in f.vertices) for f in room.faces)
            )

    # Fallback: if every room has Outdoors ceilings (no attic), use global max
    if conditioned_max_zs:
        top_z = max(conditioned_max_zs)
    else:
        top_z = max(
            max(v.z for v in face.vertices)
            for room in rooms for face in room.faces
        )

    # Pre-compute which z-level is the top conditioned ceiling, so that
    # both the ceiling (RoofCeiling+Surface) and the matching attic floor
    # (Floor+Surface) at that z get the same top_floor construction.
    top_ceiling_z = None
    if cs.top_floor:
        for room in rooms:
            rmax = max(max(v.z for v in f.vertices) for f in room.faces)
            if abs(rmax - top_z) < 0.1:
                for face in room.faces:
                    if (type(face.type).__name__ == "RoofCeiling"
                            and isinstance(face.boundary_condition, SurfaceBC)):
                        top_ceiling_z = min(v.z for v in face.vertices)
                        break
                if top_ceiling_z is not None:
                    break

    for room in rooms:
        room_min_z = min(min(v.z for v in f.vertices) for f in room.faces)
        room_max_z = max(max(v.z for v in f.vertices) for f in room.faces)
        is_basement = room_min_z < -0.1
        is_top = abs(room_max_z - top_z) < 0.1

        for face in room.faces:
            ftype = type(face.type).__name__
            bc = face.boundary_condition

            if ftype == "Wall":
                if isinstance(bc, Ground):
                    face.properties.energy.construction = (
                        cs.basement_wall or cs.wall
                    )
                elif isinstance(bc, SurfaceBC):
                    face.properties.energy.construction = (
                        cs.int_wall_loadbearing
                        or cs.int_wall_nonloadbearing
                        or _INTERIOR_WALL
                    )
                else:  # Outdoors
                    face.properties.energy.construction = cs.wall

            elif ftype == "RoofCeiling":
                if isinstance(bc, Outdoors):
                    face.properties.energy.construction = cs.roof
                else:  # Surface (interzone)
                    if is_top:
                        face.properties.energy.construction = (
                            cs.top_floor
                            or cs.intermediate_floor
                            or _INTERIOR_FLOOR
                        )
                    else:
                        face.properties.energy.construction = (
                            cs.intermediate_floor or _INTERIOR_FLOOR
                        )

            elif ftype == "Floor":
                if isinstance(bc, Ground):
                    if is_basement:
                        face.properties.energy.construction = (
                            cs.basement_floor
                            or cs.ground_floor
                            or cs.floor
                        )
                    else:
                        face.properties.energy.construction = (
                            cs.ground_floor or cs.floor
                        )
                elif isinstance(bc, SurfaceBC):
                    # Attic floor sitting on top conditioned ceiling must
                    # use the same construction for EnergyPlus interzone
                    # symmetry.
                    if (top_ceiling_z is not None
                            and any(abs(v.z - top_ceiling_z) < 0.1
                                    for v in face.vertices)):
                        face.properties.energy.construction = (
                            cs.top_floor
                            or cs.intermediate_floor
                            or _INTERIOR_FLOOR
                        )
                    else:
                        face.properties.energy.construction = (
                            cs.intermediate_floor or _INTERIOR_FLOOR
                        )
                else:  # Outdoors (cantilever / overhang)
                    face.properties.energy.construction = cs.floor

            for aperture in face.apertures:
                aperture.properties.energy.construction = cs.window
