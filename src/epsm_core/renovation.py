# File: renovation.py
# Purpose: Typed immutable physical changes. Catalogues and policy live in epsm_data.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-09-06
# Changelog:
#   2026-09-06 - Document renovation interfaces, examples, constraints and processing rationale.

"""Typed immutable physical changes. Catalogues and policy live in epsm_data.

Notes
-----
Typed measures create validated replacement buildings and append chronological
before/after quantity evidence. Measures affect complete assemblies or systems; target
IDs verify all affected elements rather than selecting a subset. External assessment
references remain administrative metadata.

Examples
--------
Example::

    from epsm_core.renovation import InstallPV
    from epsm_core.specs.physics import PVSpec

    measure = InstallPV(pv=PVSpec(dc_capacity_kw=5))
"""

from typing import Literal

from .specs import (
    AirflowSpec,
    BuildingSpec,
    DeliverySpec,
    FVPSpec,
    GlazingSpec,
    LayerSpec,
    PVSpec,
    QuantityChange,
    RenewablesSpec,
    RenovationRecord,
    Spec,
)


class AddInsulation(Spec):
    """Insert a nominal insulation layer into a complete envelope assembly.

    Attributes
    ----------
    kind : Literal['add_insulation']
        Supported measure discriminator or geometric classification, according to the
        record.  Default: ``'add_insulation'``.
    element : Literal['wall', 'top', 'ground', 'basement_wall', 'basement_ceiling']
        Complete envelope assembly role to receive insulation.  Required at construction.
    layer : LayerSpec
        Physical layer to insert, including material and thickness.  Required at
        construction.
    position : int
        Outside-to-inside layer insertion index, validated when the measure is applied.
        Default: ``0``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    position is checked against the actual assembly when applying the measure. It is an
    insertion index in outside-to-inside order, not an element selection filter.

    Examples
    --------
    Example::

        from epsm_core.renovation import AddInsulation
        from epsm_core.specs.physics import LayerSpec
        from epsm_core.specs.physics import MaterialSpec

        material = MaterialSpec(
            name="concrete",
            conductivity_w_mk=1.7,
            density_kg_m3=2300,
            specific_heat_j_kgk=880,
        )
        measure = AddInsulation(
            element="wall", layer=LayerSpec(material=material, thickness_m=0.1)
        )
    """

    kind: Literal["add_insulation"] = "add_insulation"
    element: Literal["wall", "top", "ground", "basement_wall", "basement_ceiling"]
    layer: LayerSpec
    position: int = 0


class ReplaceGlazing(Spec):
    """Replace the default glazing specification for a building.

    Attributes
    ----------
    kind : Literal['replace_glazing']
        Supported measure discriminator or geometric classification, according to the
        record.  Default: ``'replace_glazing'``.
    glazing : GlazingSpec
        Simple-glazing properties, or an optional override where None means inherit.
        Required at construction.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Explicit facade/storey glazing overrides retain their values. The quantity audit
    identifies every element actually changed by the new default.

    Examples
    --------
    Example::

        from epsm_core.specs.facade import GlazingSpec
        from epsm_core.renovation import ReplaceGlazing

        measure = ReplaceGlazing(
            glazing=GlazingSpec(u_value_w_m2k=1, solar_heat_gain_coefficient=0.5)
        )
    """

    kind: Literal["replace_glazing"] = "replace_glazing"
    glazing: GlazingSpec


class ChangeAirflow(Spec):
    """Replace the building's main airflow specification.

    Attributes
    ----------
    kind : Literal['change_airflow']
        Supported measure discriminator or geometric classification, according to the
        record.  Default: ``'change_airflow'``.
    airflow : AirflowSpec
        Per-zone leakage and ventilation controls; None uses the building defaults.
        Required at construction.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Complete BuildingSpec validation checks compatibility with delivery equipment. Explicit
    common_airflow is a separate setting and is not changed by this measure.

    Examples
    --------
    Example::

        from epsm_core.specs.physics import AirflowSpec
        from epsm_core.renovation import ChangeAirflow

        measure = ChangeAirflow(
            airflow=AirflowSpec(
                topology="F", envelope_infiltration_ach=0.2, mechanical_vent_l_s_m2=0.35
            )
        )
    """

    kind: Literal["change_airflow"] = "change_airflow"
    airflow: AirflowSpec


class InstallFVP(Spec):
    """Set an exhaust-air heat-pump delivery specification.

    Attributes
    ----------
    kind : Literal['install_fvp']
        Supported measure discriminator or geometric classification, according to the
        record.  Default: ``'install_fvp'``.
    fvp : FVPSpec
        Optional exhaust-air heat-pump delivery model; None disables this accounting.
        Required at construction.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    The resulting BuildingSpec must use F ventilation. Existing FVP settings are replaced
    and quantity differences are recorded by apply_renovation.

    Examples
    --------
    Example::

        from epsm_core.specs.physics import FVPSpec
        from epsm_core.renovation import InstallFVP

        measure = InstallFVP(fvp=FVPSpec(cop=3, capacity_kw=5))
    """

    kind: Literal["install_fvp"] = "install_fvp"
    fvp: FVPSpec


class InstallPV(Spec):
    """Append one PV system to existing renewable generation inputs.

    Attributes
    ----------
    kind : Literal['install_pv']
        Supported measure discriminator or geometric classification, according to the
        record.  Default: ``'install_pv'``.
    pv : PVSpec
        PVWatts system design with DC capacity, orientation and losses.  Required at
        construction.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    The measure changes physical configuration only. PySAM is required later when evaluating
    production, not when constructing this input record.

    Examples
    --------
    Example::

        from epsm_core.renovation import InstallPV
        from epsm_core.specs.physics import PVSpec

        measure = InstallPV(pv=PVSpec(dc_capacity_kw=5))
    """

    kind: Literal["install_pv"] = "install_pv"
    pv: PVSpec


def apply_renovation(
    building: BuildingSpec,
    measure,
    *,
    effective_date,
    targeted_element_ids=None,
    dataset_references=(),
    assessment_references=(),
):
    """Apply one immutable measure and append a dated physical quantity audit.

    Parameters
    ----------
    building : BuildingSpec
        Validated building input; geometry-only helpers also accept an object exposing the
        fields they consume.
    measure : Spec
        One supported typed renovation measure.
    effective_date : date or str
        Measure date, accepting ISO YYYY-MM-DD; events must be appended chronologically.
    targeted_element_ids : sequence of str or None
        Optional exact set of all affected physical elements; does not restrict measure
        scope. Default: ``None``.
    dataset_references : tuple of DatasetReference
        Explicit external catalogue references carried into audit records. Default: ``()``.
    assessment_references : tuple of AssessmentReference
        Administrative lifecycle or pricing references; no factor lookup is performed.
        Default: ``()``.

    Returns
    -------
    BuildingSpec
        Updated building with a RenovationRecord.

    Raises
    ------
    ValueError
        Rejected conditions: Renovation events must be appended in effective-date order;
        Insulation layer position outside assembly; This measure changes a complete
        assembly/system; targets must match all affected physical elements.
    TypeError
        If the input or generated result violates the constraints described in Notes.

    Notes
    -----
    Measures affect the complete selected assembly or system. Explicit target IDs must equal
    all affected elements; they do not filter the operation. Default glazing replacement
    leaves explicit facade overrides in place. Events must be chronological.

    Examples
    --------
    Supply a validated BuildingSpec as ``building``.

    Example::

        from epsm_core.renovation import InstallPV
        from epsm_core.specs.physics import PVSpec
        from epsm_core.renovation import apply_renovation

        changed = apply_renovation(
            building,
            InstallPV(pv=PVSpec(dc_capacity_kw=5)),
            effective_date="2026-09-06",
        )
    """

    # 1. Apply one immutable measure and append a dated physical quantity audit.
    from datetime import date

    from .quantities import quantity_takeoff

    effective_date = (
        date.fromisoformat(effective_date) if isinstance(effective_date, str) else effective_date
    )
    if building.renovations and effective_date < building.renovations[-1].effective_date:
        raise ValueError("Renovation events must be appended in effective-date order")
    # 2. Capture physical quantities before applying the complete typed measure.
    before_items = quantity_takeoff(building)
    if isinstance(measure, AddInsulation):
        assembly = getattr(building.envelope, measure.element)
        if assembly is None:
            raise ValueError(f"No {measure.element} assembly exists to insulate")
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
    # 3. Compare stable item identities to derive added, removed and replaced quantities.
    after_items = quantity_takeoff(changed)
    before = {q.item_id: q for q in before_items}
    after = {q.item_id: q for q in after_items}
    changes = []
    for key in sorted(before.keys() | after.keys()):
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        action = "replaced" if old and new else "removed" if old else "added"
        changes.append(QuantityChange(action=action, before=old, after=new))
    # 4. Verify target completeness; target IDs are an audit assertion, not a selection filter.
    affected = tuple(sorted({q.element_id for c in changes for q in (c.before, c.after) if q}))
    if targeted_element_ids is not None and set(targeted_element_ids) != set(affected):
        raise ValueError(
            "This measure changes a complete assembly/system; targets must match all affected physical elements"
        )
    # 5. Append dated evidence linking measure parameters, quantity changes and physical hashes.
    record = RenovationRecord(
        measure=measure.kind,
        effective_date=effective_date,
        targeted_element_ids=affected,
        changes=tuple(changes),
        dataset_references=dataset_references,
        assessment_references=assessment_references,
        before_sha256=building.physical_hash(),
        after_sha256=changed.physical_hash(),
        parameters_json=measure.model_dump_json(),
    )
    return changed.updated(renovations=(*building.renovations, record))
