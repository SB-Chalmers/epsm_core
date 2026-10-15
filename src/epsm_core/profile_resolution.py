"""Resolve portable Data definitions using Core's existing physical converters.

Selection and source records belong to Data. This module performs no I/O and
does not infer calendars, installed HVAC, reference areas or geometry.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass

from epsm_data import OperatingProfile
from pydantic import TypeAdapter, ValidationError

from ._representation import bounded_summary
from .building import OperationProfile
from .dhw import DHWProfileSpec
from .generic_programme import GenericOtherProgramme
from .nonresidential import SvebyNonResidentialSpec
from .specs import AirflowSpec, FacadeSpec, SourceRecord, UseSpec
from .specs.base import Fraction, Nonnegative
from .specs.facade import _validate_facade_properties
from .specs.physics import _validate_airflow_properties, _validate_use_properties
from .standards import SvebyResidentialSpec, _freeze

logger = logging.getLogger(__name__)


@dataclass(frozen=True, repr=False)
class ResolvedOperatingProfile:
    """Loaded assumptions, a validated use when complete and explicit requirements.

    ``assumptions`` is a recursively read-only mapping using BuildingBuilder's
    use/common_use/airflow/facade section names. ``operation`` is None when use
    inputs remain incomplete. Source records describe assumptions, never source
    measurements. ``to_dict()`` returns writable detached JSON-compatible data.
    No simulation readiness, file access or calculation is performed by repr.
    """

    profile_id: str
    _assumptions_json: str
    operation: OperationProfile | None
    requirements: tuple[str, ...]
    source_references: tuple[str, ...]
    source_records: tuple[SourceRecord, ...]
    notes: tuple[str, ...] = ()

    @property
    def assumptions(self):
        """Return immutable loaded assumptions without another definition lookup."""
        return _freeze(json.loads(self._assumptions_json))

    def to_dict(self):
        """Return detached values and source records, without writing artifacts."""
        return {"profile_id": self.profile_id, "assumptions": json.loads(self._assumptions_json),
                "requirements": list(self.requirements),
                "source_references": list(self.source_references),
                "notes": list(self.notes),
                "source_records": [record.model_dump(mode="json") for record in self.source_records]}

    def __repr__(self):
        return bounded_summary(type(self).__name__, profile=self.profile_id,
                               operation=self.operation is not None, requirements=len(self.requirements))

    __str__ = __repr__


def _calendar_values(calendar, *, project):
    if not isinstance(calendar, Mapping):
        raise ValueError("calendar must be a mapping of explicit Gregorian project inputs")
    allowed = {"calendar_year", "active_dates", "calendar_source", "normal_use"} if project else {"calendar_year"}
    if set(calendar) - allowed or "calendar_year" not in calendar:
        raise ValueError("calendar must supply calendar_year and only supported calendar fields")
    year = calendar["calendar_year"]
    if type(year) is not int or not 1 <= year <= 9999:
        raise ValueError("calendar_year must be a Gregorian year")
    if project and not {"active_dates", "calendar_source"} <= set(calendar):
        raise ValueError("An explicit project active_dates and calendar_source are required")
    if "normal_use" in calendar and type(calendar["normal_use"]) is not bool:
        raise ValueError("normal_use must be an explicit boolean")
    return dict(calendar)


def _validate_partial(kind, values, section):
    try:
        return kind.model_validate(values), ()
    except ValidationError as error:
        if any(item["type"] != "missing" or not isinstance(item["loc"][-1], str)
               for item in error.errors()):
            raise
        validator = (_validate_use_properties if issubclass(kind, UseSpec) else
                     _validate_airflow_properties if kind is AirflowSpec else _validate_facade_properties)
        validator(values)
        return None, tuple(section + "." + ".".join(map(str, item["loc"]))
                           for item in error.errors())


def _validated_options(options, *, residential, data):
    allowed = {"fixed_solar_shading_calculated", "cooling_enabled"}
    allowed |= {"occupant_density_per_m2"} if residential else {"zone_role", "standby_fraction"}
    if set(options) - allowed:
        raise ValueError("Unsupported profile conversion option")
    for key in ("fixed_solar_shading_calculated", "cooling_enabled"):
        if key in options and options[key] is not None and type(options[key]) is not bool:
            raise ValueError(f"{key} must be an explicit boolean")
    for key, kind in (("standby_fraction", Fraction), ("occupant_density_per_m2", Nonnegative)):
        if key in options and options[key] is not None:
            TypeAdapter(kind).validate_python(options[key])
    if "zone_role" in options and (data["building_use"] != "school"
                                    or options["zone_role"] not in data["operation_inputs"]["zone_roles"]):
        raise ValueError("zone_role must identify a supported school role")
    return options


def resolve_operating_profile(profile, *, calendar=None, previous=None, **options):
    """Convert a loaded standard or custom Data profile without resource reads.

    Parameters
    ----------
    profile : epsm_data.OperatingProfile
        A selected Sveby, explicit generic, type-specific BEN DHW or custom
        definition. Custom ``values['building_assumptions']`` supplies plain
        use/common_use/airflow/facade inputs; incomplete sections remain visible.
    calendar : mapping, optional
        Residential profiles accept ``calendar_year`` for exact monthly timing.
        Office/school require Gregorian ``calendar_year``, distinct ``active_dates``
        and nonempty ``calendar_source``; ``normal_use`` defaults to True.
        None leaves office/school operation unresolved. Supplied invalid calendars
        raise ValueError. No holiday list is generated.
    previous : UseSpec, optional
        Explicit basis for a partial BEN/custom use overlay. Omitted previous use
        is never invented. Full standard definitions resolve independently.
    **options
        Existing source-factory overrides, such as residential occupant density,
        school zone_role or explicitly calculated fixed shading.

    Returns
    -------
    ResolvedOperatingProfile
        Complete operation where possible, partial assumptions, sources and
        requirements. Loading source definitions does not establish HVAC topology,
        reference area or simulation readiness. Source rates retain their Atemp basis.
    """
    if not isinstance(profile, OperatingProfile):
        raise TypeError("profile must be an EPSM Data OperatingProfile")
    data = profile.to_dict()["values"]
    if previous is not None:
        previous = UseSpec.model_validate(previous.model_dump() if isinstance(previous, UseSpec) else previous)
    requirements = list(data.get("requirements", ()))
    source_records = ()
    custom_paths = None
    if "building_assumptions" in data:
        if calendar is not None or options:
            raise ValueError("Custom assumptions supply their own resolved schedules and inputs")
        assumptions = data["building_assumptions"]
        if not isinstance(assumptions, dict):
            raise ValueError("building_assumptions must be a mapping")
        custom_paths = tuple(section + "." + field for section, values in assumptions.items()
                             if isinstance(values, dict) for field in values)
        if previous is not None and "use" in assumptions:
            if not isinstance(assumptions["use"], dict):
                raise ValueError("use must be a mapping for an explicit partial overlay")
            assumptions["use"] = {**previous.model_dump(mode="json"), **assumptions["use"]}
    elif data.get("purpose") == "epc_normal_use":
        if calendar is not None or options:
            raise ValueError("BEN DHW changes annual intensity only; retain explicit existing timing")
        if "dhw_kwh_m2_year" not in data:
            raise ValueError("Select a type-specific DHW definition through Data")
        dhw = DHWProfileSpec.model_validate({key: data[key] for key in DHWProfileSpec.model_fields})
        assumptions = {"use": {"dhw_kwh_m2_year": dhw.dhw_kwh_m2_year}}
        if previous is not None:
            assumptions["use"] = dhw.apply_to(previous).model_dump(mode="json")
        requirements.append("load_reference_area_m2")
        source_records = (dhw.source_record(),)
    elif data.get("standard_name") == "Sveby Brukarindata bostader":
        _validated_options(options, residential=True, data=data)
        values = {} if calendar is None else _calendar_values(calendar, project=False)
        assumptions = SvebyResidentialSpec(data).building_assumptions(**values, **options)
    elif data.get("building_use") in {"office", "school"}:
        _validated_options(options, residential=False, data=data)
        if calendar is None:
            assumptions = {}
            requirements.append("calendar")
        else:
            values = _calendar_values(calendar, project=True)
            assumptions = SvebyNonResidentialSpec(data).building_assumptions(**values, **options)
            requirements = [item for item in requirements if item != "calendar"]
    elif data.get("profile_id") == "epsm.generic_other.v1":
        if calendar is not None or options:
            raise ValueError("Generic weekday screening assumptions do not select a project calendar")
        programme = GenericOtherProgramme(profile.profile_id, data["mechanical_vent_l_s_m2"], data)
        assumptions = {"use": programme.use_spec().model_dump(mode="json"), "airflow": {
            "mechanical_vent_l_s_m2": programme.mechanical_vent_l_s_m2,
            "mechanical_vent_fraction": programme.ventilation_fraction().model_dump(mode="json")}}
    else:
        raise ValueError("Unsupported profile definition; custom profiles need building_assumptions")
    kinds = {"use": OperationProfile, "common_use": OperationProfile,
             "airflow": AirflowSpec, "facade": FacadeSpec}
    if set(assumptions) - set(kinds):
        raise ValueError("Unknown building_assumptions section")
    operation = None
    for section, values in assumptions.items():
        validated, missing = _validate_partial(kinds[section], values, section)
        requirements.extend(missing)
        if section == "use":
            operation = validated
    if "use" not in assumptions:
        requirements.append("operation")
    if not source_records:
        paths = custom_paths if custom_paths is not None else assumptions
        source_records = tuple(SourceRecord(field_path=path, status="assumed",
            source="; ".join(profile.source_references) or profile.profile_id,
            assumption_profile=profile.profile_id) for path in paths)
    result = ResolvedOperatingProfile(profile.profile_id,
        json.dumps(assumptions, sort_keys=True, separators=(",", ":"), allow_nan=False),
        operation, tuple(dict.fromkeys(requirements)), profile.source_references, source_records, profile.notes)
    logger.debug("Resolved operating profile %s; %d requirements", profile.profile_id, len(result.requirements))
    return result
