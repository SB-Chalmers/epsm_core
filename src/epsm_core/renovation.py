"""Typed immutable physical changes. Catalogues and policy live in epsm_data."""

from typing import Literal

from .specs import (
    AirflowSpec,
    BuildingSpec,
    DeliverySpec,
    FVPSpec,
    GlazingSpec,
    LayerSpec,
    PVSpec,
    RenewablesSpec,
    RenovationRecord,
    Spec,
)


class AddInsulation(Spec):
    kind: Literal["add_insulation"] = "add_insulation"
    element: Literal["wall", "top", "ground", "basement_wall"]
    layer: LayerSpec
    position: int = 0


class ReplaceGlazing(Spec):
    kind: Literal["replace_glazing"] = "replace_glazing"
    glazing: GlazingSpec


class ChangeAirflow(Spec):
    kind: Literal["change_airflow"] = "change_airflow"
    airflow: AirflowSpec


class InstallFVP(Spec):
    kind: Literal["install_fvp"] = "install_fvp"
    fvp: FVPSpec


class InstallPV(Spec):
    kind: Literal["install_pv"] = "install_pv"
    pv: PVSpec


def apply_renovation(building: BuildingSpec, measure):
    if isinstance(measure, AddInsulation):
        assembly = getattr(building.envelope, measure.element)
        if not 0 <= measure.position <= len(assembly.layers):
            raise ValueError("Insulation layer position outside assembly")
        layers = list(assembly.layers)
        layers.insert(measure.position, measure.layer)
        changed = building.updated(
            envelope=building.envelope.updated(
                **{measure.element: assembly.updated(layers=tuple(layers))}
            )
        )
    elif isinstance(measure, ReplaceGlazing):
        changed = building.updated(facade=building.facade.updated(glazing=measure.glazing))
    elif isinstance(measure, ChangeAirflow):
        changed = building.updated(airflow=measure.airflow)
    elif isinstance(measure, InstallFVP):
        changed = building.updated(delivery=DeliverySpec(fvp=measure.fvp))
    elif isinstance(measure, InstallPV):
        changed = building.updated(
            renewables=RenewablesSpec(pv_systems=(*building.renewables.pv_systems, measure.pv))
        )
    else:
        raise TypeError(f"Unsupported renovation {type(measure).__name__}")
    record = RenovationRecord(
        measure=measure.kind,
        before_sha256=building.physical_hash(),
        after_sha256=changed.physical_hash(),
        parameters_json=measure.model_dump_json(),
    )
    return changed.updated(renovations=(*building.renovations, record))
