# File: specs/building.py
# Purpose: Building input specifications.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-10-03
# Changelog:
#   2026-10-03 - Add documented calendar, operational and archetype-application support.
#   2026-09-06 - Document building interfaces, examples, constraints and processing rationale.

"""Building input specifications.

Notes
-----
BuildingSpec is the complete cross-system validation boundary. It verifies geometry
references, HVAC compatibility and context relationships while keeping source evidence
separate from physical identity. Physical hashing retains weather content identity but
excludes its local path.

Examples
--------
Replace example paths with existing local inputs; output paths must be writable.

Example::

    from epsm_core.specs.building import BuildingSpec
    from pathlib import Path

    building = BuildingSpec.model_validate_json(Path("building.json").read_text())
"""

from __future__ import annotations

import hashlib
import json

from pydantic import model_validator

from .base import Positive, Spec
from .context import ContextSpec
from .facade import FacadeSpec
from .geometry import GeometrySpec
from .operations import UnconditionedExchangeSpec, ZoneUseSpec
from .physics import (
    AirflowSpec,
    ClimateSpec,
    ConstructionSpec,
    DeliverySpec,
    EnvelopeSpec,
    RenewablesSpec,
    UseSpec,
    _validate_operation_hvac,
)
from .provenance import AssessmentReference, ProvenanceSpec, RenovationRecord


class BuildingSpec(Spec):
    """Complete physical building input with explicit weather and assumption provenance.

    Attributes
    ----------
    identifier : str
        Stable identifier within the owning collection.  Required at construction.
    geometry : GeometrySpec
        Physical parts, metric coordinate frame, orientation and zoning controls.  Required
        at construction.
    facade : FacadeSpec
        Window and shading controls; None uses the preview's zero-glazing default.  Required
        at construction.
    climate : ClimateSpec
        Weather-file checksum, site metadata and simulation calendar.  Required at
        construction.
    envelope : EnvelopeSpec
        Explicit nominal constructions and ground boundary temperatures.  Required at
        construction.
    airflow : AirflowSpec
        Per-zone leakage and ventilation controls; None uses the building defaults.
        Required at construction.
    use : UseSpec
        Residential or general occupancy, gains and thermostat schedules.  Required at
        construction.
    common_use : UseSpec | None
        Optional common/stairwell controls; absent values use the compiler's documented
        defaults.  Default: ``None``.
    common_airflow : AirflowSpec | None
        Optional common/stairwell controls; absent values use the compiler's documented
        defaults.  Default: ``None``.
    context : ContextSpec
        Explicit shading neighbours; existing context is retained by synthetic generation.
        Default: ``ContextSpec()``.
    delivery : DeliverySpec
        Delivery.  Default: ``DeliverySpec()``.
    renewables : RenewablesSpec
        Explicit renewable generation systems evaluated after thermal demand.  Default:
        ``RenewablesSpec()``.
    provenance : ProvenanceSpec
        Field-level measured, inferred and assumed source evidence.  Default:
        ``ProvenanceSpec()``.
    renovations : tuple[RenovationRecord, ...]
        Chronological physical measure history excluded from the current physical hash.
        Default: ``()``.
    assessment_references : tuple[AssessmentReference, ...]
        Administrative lifecycle or pricing references; no factor lookup is performed.
        Default: ``()``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Cross-validation enforces compatible HVAC, setpoints, topology, facade references and
    context. Administrative IDs and provenance are excluded from physical_hash; weather
    content remains included by checksum.

    Examples
    --------
    Replace example paths with existing local inputs; output paths must be writable.

    Example::

        from epsm_core.specs.building import BuildingSpec
        from pathlib import Path

        building = BuildingSpec.model_validate_json(Path("building.json").read_text())
    """

    # Sveby uses Atemp for loads/flow; the physical geometry/heat-transfer area stays intact.
    # Exact zone overrides may specify their own documented area allocation.
    load_reference_area_m2: Positive | None = None
    zone_uses: tuple[ZoneUseSpec, ...] = ()
    unconditioned_exchange: tuple[UnconditionedExchangeSpec, ...] = ()
    identifier: str
    geometry: GeometrySpec
    facade: FacadeSpec
    climate: ClimateSpec
    envelope: EnvelopeSpec
    airflow: AirflowSpec
    use: UseSpec
    common_use: UseSpec | None = None
    common_airflow: AirflowSpec | None = None
    context: ContextSpec = ContextSpec()
    delivery: DeliverySpec = DeliverySpec()
    renewables: RenewablesSpec = RenewablesSpec()
    provenance: ProvenanceSpec = ProvenanceSpec()
    renovations: tuple[RenovationRecord, ...] = ()
    assessment_references: tuple[AssessmentReference, ...] = ()
    # Migration adapter output: resolved thermal-face assignments from physical elements.
    # Public authoring stores physical elements, not these solver-dependent identifiers.
    surface_constructions: dict[str, ConstructionSpec] = {}
    internal_mass_constructions: dict[str, ConstructionSpec] = {}

    @model_validator(mode="after")
    def compatible(self):
        """Validate cross-system and geometry references on a complete building.

        Returns
        -------
        Self
            Validated building specification.

        Raises
        ------
        ValueError
            Rejected conditions: Common heating supply limit must exceed its heating setpoint;
            Apartment generation requires explicitly residential occupancy; Apartment generation
            requires dwelling_partition and common_partition constructions; Unconditioned
            basement requires an explicit thermal-boundary basement_ceiling construction; FVP
            delivery requires F ventilation; Heating supply limit must exceed the heating
            setpoint.

        Notes
        -----
        Checks setpoint/supply limits, apartment occupancy and partitions, basement boundary
        construction, FVP exhaust topology, facade overrides and context overlap. Individual
        fields are validated before these relationships.

        Examples
        --------
        Supply a validated BuildingSpec as ``building``.

        Example::

            assert building.compatible() is building
        """

        # Resolve calendars here; a standalone UseSpec has no simulation year.
        from .schedules import ScheduleSpec
        pairs = [(self.use, self.airflow)]
        if self.common_use is not None:
            pairs.append((self.common_use, self.common_airflow or self.airflow))
        elif self.common_airflow is not None:
            pairs.append((self.use, self.common_airflow))
        pairs.extend((x.use or self.use, x.airflow or self.airflow) for x in self.zone_uses)
        for use, airflow in pairs:
            _validate_operation_hvac(use, airflow, self.delivery)
            for obj in (use, airflow):
                for name in type(obj).model_fields:
                    schedule = getattr(obj, name)
                    if isinstance(schedule, ScheduleSpec):
                        schedule.hourly(self.climate.calendar_year)
            if use.dhw_kwh_m2_year and not sum(use.dhw_fraction.hourly(self.climate.calendar_year)):
                raise ValueError("Nonzero DHW requires activity in the simulation year")
        if self.delivery.heating is not None:
            heating = self.delivery.heating
            weights = heating.loss_fraction.hourly(self.climate.calendar_year)
            if heating.net_distribution_loss_kwh_m2_year and not sum(weights):
                raise ValueError("Net distribution losses require activity in the simulation year")
            if heating.heat_pump_cop is not None:
                heating.heat_pump_cop.hourly(self.climate.calendar_year)
        selectors = [(x.zone_name, x.zone_kind) for x in self.zone_uses]
        if len(selectors) != len(set(selectors)):
            raise ValueError("Duplicate zone-use selectors")
        kinds = [x.zone_kind for x in self.unconditioned_exchange]
        if len(kinds) != len(set(kinds)):
            raise ValueError("Duplicate unconditioned exchange selectors")
        for exchange in self.unconditioned_exchange:
            exchange.fraction.hourly(self.climate.calendar_year)
        if self.delivery.fvp and self.zone_uses:
            raise ValueError("FVP delivery currently requires uniform continuous exhaust flow")
        # 1. Validate cross-system and geometry references on a complete building.
        if self.geometry.zoning.mode == "apartments":
            if self.use.occupancy_category != "residential":
                raise ValueError("Apartment generation requires explicitly residential occupancy")
            if self.envelope.dwelling_partition is None or self.envelope.common_partition is None:
                raise ValueError(
                    "Apartment generation requires dwelling_partition and common_partition constructions"
                )
        if (
            self.geometry.basement_depth_m
            and not self.geometry.basement_conditioned
            and self.envelope.basement_ceiling is None
        ):
            raise ValueError(
                "Unconditioned basement requires an explicit thermal-boundary basement_ceiling construction"
            )
        catalog = {f.facade_id: f for f in self.geometry.facades()}
        for override in self.facade.overrides:
            if override.facade_id not in catalog:
                raise ValueError(f"Override references unknown facade: {override.facade_id}")
            if (
                override.storey is not None
                and override.storey not in catalog[override.facade_id].storeys
            ):
                raise ValueError(f"Override references nonexistent storey: {override.facade_id}")
        from ..context import validate_context

        validate_context(self.geometry, self.context)
        return self

    def widget(self, *, height=600):
        """Inspect this building inline in JupyterLab or VS Code without simulation."""
        return self.geometry.widget(facade=self.facade, context=self.context, height=height)

    def view(self, directory=None, *, launch_browser=True):
        """Open a geometry preview using this building's facade and context settings.

        Parameters
        ----------
        directory : str or Path or None
            Local artifact directory; consult Notes for creation, overwrite and default-path
            behavior. Default: ``None``.
        launch_browser : bool
            Open the default browser when true; the returned server still needs cleanup.
            Default: ``True``.

        Returns
        -------
        ViewerHandle
            Live preview server requiring cleanup.

        Notes
        -----
        Delegates to GeometrySpec.view and does not simulate. Writes artifacts and optionally
        opens the browser.

        Examples
        --------
        Supply a validated BuildingSpec as ``building``.

        Example::

            with building.view("output/review", launch_browser=False) as handle:
                print(handle.url)
        """

        return self.geometry.view(
            directory, facade=self.facade, context=self.context, launch_browser=launch_browser
        )

    def physical_dict(self):
        """Serialize simulation-relevant inputs without administrative provenance.

        Returns
        -------
        dict
            JSON-compatible physical input mapping.

        Notes
        -----
        Excludes identifier, provenance, renovation history, assessment references and the local
        EPW path. Weather content remains identified by checksum. Returns a fresh mapping.

        Examples
        --------
        Supply a validated BuildingSpec as ``building``.

        Example::

            assert "identifier" not in building.physical_dict()
        """

        # 1. Serialize simulation-relevant inputs without administrative provenance.
        data = self.model_dump(
            mode="json",
            exclude={"identifier", "provenance", "renovations", "assessment_references"},
        )
        data["climate"].pop("epw_path")
        for name in ("surface_constructions", "internal_mass_constructions"):
            if not data[name]:
                data.pop(name)
        return data

    def physical_hash(self):
        """Hash canonical JSON for the building's physical input identity.

        Returns
        -------
        str
            SHA-256 hexadecimal digest.

        Notes
        -----
        Sorted keys and compact separators remove dictionary insertion-order differences. This
        identifies inputs, not compiler binaries or execution settings; those belong to run_id.

        Examples
        --------
        Supply a validated BuildingSpec as ``building``.

        Example::

            assert (
                building.updated(identifier="renamed").physical_hash()
                == building.physical_hash()
            )
        """

        return hashlib.sha256(
            json.dumps(self.physical_dict(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
