"""Physical material inventory, independent of solver zones and equivalent materials."""

from __future__ import annotations

import json
from dataclasses import dataclass

from ._representation import bounded_summary


@dataclass(frozen=True)
class MaterialQuantity:
    """One installed material occurrence; unknown mass is never represented by zero."""

    occurrence_id: str
    material_id: str
    element_id: str
    component_id: str
    layer_id: str
    area_m2: float | None
    volume_m3: float | None
    mass_kg: float | None
    material: object | None = None
    material_name: str = ""
    role: str = ""
    count: float | None = None
    kind: str = "material"
    factor_refs: tuple[tuple[str, str], ...] = ()
    length_m: float | None = None

    def __repr__(self):
        return bounded_summary(type(self).__name__, material=self.material_id,
                               kind=self.kind, area_m2=self.area_m2, mass_kg=self.mass_kg)

    __str__ = __repr__

    def to_dict(self):
        return {
            "occurrence_id": self.occurrence_id,
            "material_id": self.material_id,
            "material_name": self.material_name,
            "element_id": self.element_id,
            "component_id": self.component_id,
            "layer_id": self.layer_id,
            "role": self.role,
            "area_m2": self.area_m2,
            "volume_m3": self.volume_m3,
            "mass_kg": self.mass_kg,
            "count": self.count, "length_m": self.length_m, "kind": self.kind,
            "factor_refs": dict(self.factor_refs),
            "material": self.material.to_dict() if self.material is not None else None,
        }


class MaterialInventory(tuple):
    """Iterable material occurrences with explicit per-material aggregation."""

    def __repr__(self):
        return bounded_summary(type(self).__name__, occurrences=len(self))

    __str__ = __repr__

    def by_material(self):
        result = {}
        for row in self:
            group = result.setdefault(row.material_id, {
                "material_id": row.material_id, "material_name": row.material_name,
                "area_m2": 0.0, "volume_m3": 0.0, "mass_kg": 0.0, "count": 0.0,
                "occurrence_ids": [], "complete": True,
            })
            group["occurrence_ids"].append(row.occurrence_id)
            for field in ("area_m2", "volume_m3", "mass_kg", "count"):
                value = getattr(row, field)
                if value is None:
                    group[field] = None
                    if field != "count":
                        group["complete"] = False
                elif group[field] is not None:
                    group[field] += value
        return result

    def to_dict(self):
        return [row.to_dict() for row in self]


@dataclass(frozen=True)
class MaterialFlows:
    """One ordered physical intervention. Time belongs to assessment settings."""

    stage_id: str
    order: int
    installed: MaterialInventory
    removed: MaterialInventory
    retained: MaterialInventory

    def __repr__(self):
        return bounded_summary(type(self).__name__, order=self.order,
                               installed=len(self.installed), removed=len(self.removed),
                               retained=len(self.retained))

    __str__ = __repr__

    @property
    def transition_id(self):
        return self.stage_id

    @property
    def added(self):
        return self.installed

    def to_dict(self):
        return {"stage_id": self.stage_id, "order": self.order,
                "installed": self.installed.to_dict(), "removed": self.removed.to_dict(),
                "retained": self.retained.to_dict()}


def material_inventory(elements, equipment=(), installations=()):
    """Traverse physical assignments, counting only constituent material leaves.

    Installations are products outside the layered envelope, such as ductwork;
    their quantity is reported in its own unit and mass is never inferred.
    """
    from epsm_data.domain.element import WindowElement

    rows = []
    for element in elements:
        construction = element.construction
        if construction is None:
            raise ValueError(f"Element {element.identifier!r} has no construction")
        if isinstance(construction, WindowElement):
            refs = {}
            if construction.boverket_id is not None:
                refs["boverket_id"] = str(construction.boverket_id)
            reference = construction.carbon_reference
            if reference is not None:
                refs["carbon_reference_id"] = reference.identifier
                refs["carbon_reference"] = json.dumps(
                    reference.to_dict(), sort_keys=True, separators=(",", ":")
                )
            rows.append(MaterialQuantity(
                element.component_ids[0], construction.name, element.identifier,
                element.component_ids[0], "window", element.area_m2, None, None,
                material_name=construction.name, role=element.role.value, kind="window",
                factor_refs=tuple(refs.items()),
            ))
            continue
        for component, component_id in zip(construction.components, element.component_ids):
            for slot in component.layers:
                layer = slot.layer
                layer_id = f"{component_id}/layer:{slot.position}"
                for index, share in enumerate(layer.materials):
                    material = share.material
                    area = element.area_m2 * share.area_fraction
                    volume = area * share.thickness
                    rows.append(MaterialQuantity(
                        f"{layer_id}/material:{index}", material.json_id or str(material.uuid),
                        element.identifier, component_id, layer_id, area, volume,
                        volume * material.density if material.density is not None else None,
                        material, material.name, element.role.value,
                    ))
    for item in equipment:
        rows.append(MaterialQuantity(
            item.occurrence_id, item.product_id, "equipment." + item.identifier,
            item.occurrence_id, "equipment", None, None, None,
            material_name=item.description or item.product_id, role="equipment",
            count=item.count, kind="equipment", factor_refs=item.factor_refs,
        ))
    for item in installations:
        rows.append(MaterialQuantity(
            item.occurrence_id, item.product_id, "installation." + item.identifier,
            item.occurrence_id, "installation",
            item.quantity if item.unit == "m2" else None, None, item.mass_kg,
            material_name=item.description, role="installation",
            count=item.quantity if item.unit == "item" else None, kind="installation",
            factor_refs=item.factor_refs,
            length_m=item.quantity if item.unit == "m" else None,
        ))
    return MaterialInventory(rows)
