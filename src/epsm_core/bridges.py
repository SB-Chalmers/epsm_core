"""Thermal-bridge allowances as equivalent-conductivity uplifts per envelope role.

An envelope carries at most one bridge representation:

- ``thermal_bridge_uplift_fraction`` raises every bridged role by the same fraction;
- ``thermal_bridge_delta_u_w_m2k`` is TABULA's ``delta_U_ThermalBridging``, an additive U on
  the whole envelope area with glazing counted once. Its conductance ``ΔU · A_envelope``
  belongs to the above-grade walls and thermal top, where the linear bridges sit, so it
  becomes one uplift on those two roles. Spreading it over uninsulated basement walls and
  slabs instead can exceed what an equivalent conductivity can represent.

Both engines read the same per-role fractions, so EnergyPlus and RC apply one allowance.
"""

from __future__ import annotations

BRIDGED_ROLES = ("wall", "top", "ground", "basement_wall", "basement_ceiling")
SURCHARGE_ROLES = ("wall", "top")


def thermal_bridge_uplifts(spec, *, resolved=None):
    """Return ``{role: uplift fraction}`` for every bridged envelope role.

    Parameters
    ----------
    spec : BuildingSpec
        Validated building input.
    resolved : ResolvedGeometry, optional
        ``pipeline.resolve_geometry(spec, panelize=bool(spec.surface_constructions))``,
        when the caller already has it. Used only for the absolute surcharge.

    Returns
    -------
    dict of str to float
        One fraction per role in ``BRIDGED_ROLES``. Roles outside the mapping take none.

    Notes
    -----
    For the absolute surcharge, areas follow the nominal quantity takeoff: reciprocal
    faces once, partitions and internal mass excluded, main exterior walls net of their
    panes, and pane area added to the envelope. Each wall and top face contributes the U
    of its own assembly, including surface overrides.
    """
    envelope = spec.envelope
    delta_u = envelope.thermal_bridge_delta_u_w_m2k
    if not delta_u:
        return dict.fromkeys(BRIDGED_ROLES, float(envelope.thermal_bridge_uplift_fraction))
    if resolved is None:
        from .pipeline import resolve_geometry

        resolved = resolve_geometry(spec, panelize=bool(spec.surface_constructions))
    panes = {}
    for opening in resolved.openings:
        panes[opening.parent] = panes.get(opening.parent, 0.0) + opening.area
    envelope_area = conductance = 0.0
    seen = set()
    for face in resolved.graph.surfaces:
        if face.name in seen or face.construction == "partition":
            continue
        seen.add(face.name)
        if face.boundary == "Surface":
            seen.add(face.adjacent)
        role = face.construction.removesuffix("_reverse").removeprefix("unconditioned_")
        if role not in BRIDGED_ROLES:
            continue
        area = face.area
        if face.kind == "Wall" and face.boundary == "Outdoors" and face.cell_kind == "main":
            glazed = panes.get(face.name, 0.0)
            area -= glazed
            envelope_area += glazed
        envelope_area += area
        if role in SURCHARGE_ROLES:
            assembly = spec.surface_constructions.get(face.name) or getattr(envelope, role)
            conductance += area * assembly.u_value_w_m2k
    if conductance <= 0:
        raise ValueError("Thermal-bridge surcharge needs wall or top area to carry it")
    uplift = delta_u * envelope_area / conductance
    return {role: uplift if role in SURCHARGE_ROLES else 0.0 for role in BRIDGED_ROLES}
