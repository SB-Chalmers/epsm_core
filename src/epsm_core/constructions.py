"""Pure physical construction helpers; no material registry or network access."""

from .specs import ConstructionSpec


def internal_mass_halves(assembly: ConstructionSpec):
    """Two adiabatic half-slabs, ordered from midplane to each exposed face.

    InternalMass exchanges heat on one face only. Each half uses the actual
    footprint area, preserving both the exposed area and the physical heat capacity.
    """
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


def bridge_equivalent(assembly: ConstructionSpec, uplift: float):
    """Scale conductivities, retaining thickness and thermal mass, to match target U."""
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
