# File: constructions.py
# Purpose: Pure physical construction helpers; no material registry or network access.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-10-22
# Changelog:
#   2026-10-22 - Solve selected physical layer depths while retaining actual materials.
#   2026-09-06 - Document constructions interfaces, examples, constraints and processing rationale.

"""Pure physical construction helpers; no material registry or network access.

Notes
-----
These helpers transform validated nominal layer stacks without external registries.
Internal-mass halves conserve slab capacity; insulation solving uses steady-state
resistance; thermal bridges use equivalent conductivity while retaining nominal mass.

Examples
--------
Example::

    from epsm_core.specs.physics import ConstructionSpec
    from epsm_core.specs.physics import LayerSpec
    from epsm_core.specs.physics import MaterialSpec
    from epsm_core.constructions import internal_mass_halves

    material = MaterialSpec(
        name="concrete",
        conductivity_w_mk=1.7,
        density_kg_m3=2300,
        specific_heat_j_kgk=880,
    )
    assembly = ConstructionSpec(
        layers=(LayerSpec(material=material, thickness_m=0.2),)
    )
    first, second = internal_mass_halves(assembly)
    assert (
        abs(
            sum(x.thickness_m for h in (first, second) for x in h.layers)
            - sum(x.thickness_m for x in assembly.layers)
        )
        < 1e-9
    )
"""

from math import isfinite

from epsm_data.domain import Element
from epsm_data.domain.enums import BuildingElement as ElementRole

from .specs import ConstructionSpec


def internal_mass_halves(assembly: ConstructionSpec):
    """Split a physical slab at its thickness midpoint into two exposed halves.

    Parameters
    ----------
    assembly : ConstructionSpec
        Nominal assembly ordered from outside to inside.

    Returns
    -------
    tuple of ConstructionSpec
        Half-slabs ordered from midplane to exposed face.

    Notes
    -----
    EnergyPlus InternalMass exchanges on one side. Assign the physical footprint area to
    each half to preserve exposed area and total heat capacity.

    Examples
    --------
    Example::

        from epsm_core.specs.physics import ConstructionSpec
        from epsm_core.specs.physics import LayerSpec
        from epsm_core.specs.physics import MaterialSpec
        from epsm_core.constructions import internal_mass_halves

        material = MaterialSpec(
            name="concrete",
            conductivity_w_mk=1.7,
            density_kg_m3=2300,
            specific_heat_j_kgk=880,
        )
        assembly = ConstructionSpec(
            layers=(LayerSpec(material=material, thickness_m=0.2),)
        )
        first, second = internal_mass_halves(assembly)
        assert (
            abs(
                sum(x.thickness_m for h in (first, second) for x in h.layers)
                - sum(x.thickness_m for x in assembly.layers)
            )
            < 1e-9
        )
    """
    # 1. Split a physical slab at its thickness midpoint into two exposed halves.
    midpoint = sum(layer.thickness_m for layer in assembly.layers) / 2
    first, second, position = [], [], 0.0
    for layer in assembly.layers:
        left = max(0.0, min(layer.thickness_m, midpoint - position))
        right = layer.thickness_m - left
        if left > 1e-12:
            first.append(layer.updated(thickness_m=left))
        if right > 1e-12:
            second.append(layer.updated(thickness_m=right))
        position += layer.thickness_m
    return (
        assembly.updated(layers=tuple(reversed(first))),
        assembly.updated(layers=tuple(second)),
    )


def solve_insulation(
    assembly: ConstructionSpec,
    layer_index: int,
    target_u_w_m2k: float,
    *,
    min_thickness_m: float = 0.001,
    max_thickness_m: float = 2,
):
    """Solve one layer thickness for a specified steady-state U-value.

    Parameters
    ----------
    assembly : ConstructionSpec
        Nominal assembly ordered from outside to inside.
    layer_index : int
        Index of the single layer whose thickness may change.
    target_u_w_m2k : float
        Desired positive steady-state U-value in W/(m2 K), including reporting film
        resistance.
    min_thickness_m : float
        Feasibility bound for the solved layer thickness, in metres. Default: ``0.001``.
    max_thickness_m : float
        Feasibility bound for the solved layer thickness, in metres. Default: ``2``.

    Returns
    -------
    ConstructionSpec
        Validated assembly containing the replaced layer.

    Raises
    ------
    ValueError
        Rejected conditions: Target U must be positive.

    Notes
    -----
    Other layers and surface-film resistance stay fixed. The selected index uses Python
    indexing; unattainable thickness bounds raise ValueError.

    Examples
    --------
    Example::

        from epsm_core.specs.physics import ConstructionSpec
        from epsm_core.specs.physics import LayerSpec
        from epsm_core.specs.physics import MaterialSpec
        from epsm_core.constructions import solve_insulation

        material = MaterialSpec(
            name="concrete",
            conductivity_w_mk=1.7,
            density_kg_m3=2300,
            specific_heat_j_kgk=880,
        )
        assembly = ConstructionSpec(
            layers=(LayerSpec(material=material, thickness_m=0.2),)
        )
        improved = solve_insulation(assembly, 0, 1.0)
        assert abs(improved.u_value_w_m2k - 1.0) < 1e-9
    """

    # 1. Solve one layer thickness for a specified steady-state U-value.
    if target_u_w_m2k <= 0:
        raise ValueError("Target U must be positive")
    fixed_r = assembly.surface_resistance_m2k_w + sum(
        x.thickness_m / x.material.conductivity_w_mk
        for i, x in enumerate(assembly.layers)
        if i != layer_index
    )
    layer = assembly.layers[layer_index]
    thickness = (1 / target_u_w_m2k - fixed_r) * layer.material.conductivity_w_mk
    if not min_thickness_m <= thickness <= max_thickness_m:
        raise ValueError(f"Infeasible insulation thickness: {thickness:g} m")
    layers = list(assembly.layers)
    layers[layer_index] = layer.updated(thickness_m=thickness)
    return assembly.updated(layers=tuple(layers))


def solve_element_insulation(
    element: Element,
    component_name: str,
    layer_index: int,
    target_u_w_m2k: float,
    *,
    min_thickness_m: float = 0.001,
    max_thickness_m: float = 2.0,
) -> Element:
    """Return a physical construction with one layer solved for a nominal U target.

    Parameters
    ----------
    element : epsm_data.Element
        Complete opaque physical construction. All parallel material constituents
        must span their layer's full depth, as required by ``thermal_construction``.
    component_name : str
        Exact component name within the construction; no material is inferred.
    layer_index : int
        Zero-based index in the selected component's ordered ``layers`` tuple.
        This is not the possibly nonconsecutive ``LayerSlot.position`` value.
    target_u_w_m2k : float
        Positive, finite Core nominal reporting U-value in W/(m2 K). This uses
        the surface-film resistance ``thermal_construction`` reports for the
        element's role (boundary films by role, including for internal constructions). It is not a ground heat-transfer
        result or a thermal-bridge-adjusted U-value. Data's role-specific
        ``Element.u_value`` uses the same films and reports the same value.
    min_thickness_m, max_thickness_m : float
        Positive, finite bounds on the solved full layer depth, in metres.

    Returns
    -------
    epsm_data.Element
        Validated independent graph replacements along the changed path. Names,
        material identities/properties, area fractions, slot positions and all
        other layers are retained. Every constituent of the selected layer gets
        the solved depth, so physical quantities reflect its actual composition.

    Raises
    ------
    ValueError
        Invalid selection, unsupported thermal arrangement, nonfinite input or
        an unattainable target within the explicit thickness bounds.

    Notes
    -----
    This pure, offline authoring operation never edits the supplied construction,
    selects a catalogue definition or invents renovation material flows. Use a
    declared renovation measure for an intervention on an existing building.
    The existing nominal ``solve_insulation`` owns the resistance calculation;
    Data's validated ``with_changes`` operations own physical graph replacement.
    """
    from .building_adapter import thermal_construction

    if not isinstance(element, Element) or element.application == ElementRole.WINDOW:
        raise ValueError("Opaque insulation solving requires a non-window layered Element")
    for name, value in (("target_u_w_m2k", target_u_w_m2k),
                        ("min_thickness_m", min_thickness_m),
                        ("max_thickness_m", max_thickness_m)):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not isfinite(value) or value <= 0):
            raise ValueError(f"{name} must be finite and positive")
    if min_thickness_m > max_thickness_m:
        raise ValueError("Insulation thickness bounds require min_thickness_m <= max_thickness_m")
    if not isinstance(component_name, str) or not component_name:
        raise ValueError("component_name must identify an existing component")
    component_index = next((i for i, c in enumerate(element.components)
                            if c.name == component_name), None)
    if component_index is None:
        raise ValueError(f"No component named {component_name!r} in construction {element.name!r}")
    component = element.components[component_index]
    if (isinstance(layer_index, bool) or not isinstance(layer_index, int)
            or not 0 <= layer_index < len(component.layers)):
        raise ValueError("layer_index must be a zero-based index within the selected component")

    assembly = thermal_construction(element)
    nominal_index = sum(len(c.layers) for c in element.components[:component_index]) + layer_index
    solved = solve_insulation(assembly, nominal_index, target_u_w_m2k,
                             min_thickness_m=min_thickness_m, max_thickness_m=max_thickness_m)
    thickness = solved.layers[nominal_index].thickness_m
    slot = component.layers[layer_index]
    layer = slot.layer.with_changes(thickness=thickness, materials=tuple(
        share.with_changes(thickness=thickness) for share in slot.layer.materials))
    layers = list(component.layers)
    layers[layer_index] = slot.with_changes(layer=layer)
    components = list(element.components)
    components[component_index] = component.with_changes(layers=tuple(layers))
    return element.with_changes(components=tuple(components))


def bridge_equivalent(assembly: ConstructionSpec, uplift: float):
    """Represent a thermal-bridge uplift by scaling layer conductivities.

    Parameters
    ----------
    assembly : ConstructionSpec
        Nominal assembly ordered from outside to inside.
    uplift : float
        Fractional increase in nominal U-value; 0.1 denotes a ten-percent uplift.

    Returns
    -------
    ConstructionSpec
        Equivalent assembly with the requested U-value uplift.

    Raises
    ------
    ValueError
        Rejected conditions: Thermal bridge uplift exceeds feasible construction
        conductance.

    Notes
    -----
    Thickness, density and specific heat remain physical; modified conductivity is an
    equivalent conductance model, not a new material measurement.

    Examples
    --------
    Example::

        from epsm_core.specs.physics import ConstructionSpec
        from epsm_core.specs.physics import LayerSpec
        from epsm_core.specs.physics import MaterialSpec
        from epsm_core.constructions import bridge_equivalent

        material = MaterialSpec(
            name="concrete",
            conductivity_w_mk=1.7,
            density_kg_m3=2300,
            specific_heat_j_kgk=880,
        )
        assembly = ConstructionSpec(
            layers=(LayerSpec(material=material, thickness_m=0.2),)
        )
        equivalent = bridge_equivalent(assembly, 0.1)
        assert abs(equivalent.u_value_w_m2k / assembly.u_value_w_m2k - 1.1) < 1e-9
    """
    # 1. Represent a thermal-bridge uplift by scaling layer conductivities.
    target_r = 1 / (assembly.u_value_w_m2k * (1 + uplift)) - assembly.surface_resistance_m2k_w
    layer_r = sum(x.thickness_m / x.material.conductivity_w_mk for x in assembly.layers)
    if target_r <= 0:
        raise ValueError("Thermal bridge uplift exceeds feasible construction conductance")
    factor = layer_r / target_r
    return assembly.updated(
        layers=tuple(
            x.updated(
                material=x.material.updated(conductivity_w_mk=x.material.conductivity_w_mk * factor)
            )
            for x in assembly.layers
        )
    )


def surface_construction_reversed(face, physical_overrides):
    """Orient one reciprocal physical partition from its common nominal owner.

    Computational AirBoundary partitions have no layer direction. When a
    physical shared wall replaces that partition, one reciprocal side must use
    the reversed nominal layers. Existing explicitly oriented roles retain their
    original direction, and ordinary AirBoundary faces remain unchanged.
    """
    return (face.construction.endswith("_reverse") or
            (face.construction == "partition" and face.name in physical_overrides
             and face.boundary == "Surface" and face.name > face.adjacent))
