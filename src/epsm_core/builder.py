# File: builder.py
# Purpose: Convenience assembly with explicit, externally supplied assumption profiles.
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
#   2026-10-03 - Select explicit use profiles and preserve supplied evidence status.
#   2026-09-15 - Select bundled Sveby residential operations in the no-argument form.
#   2026-09-06 - Document builder interfaces, examples, constraints and processing rationale.

"""Convenience assembly with explicit, externally supplied assumption profiles.

Notes
-----
Default profiles are supplied by the caller and deep-copied. With no arguments, no profile is selected. An explicit building_use selects
the versioned Sveby profile. Recursive dictionary
merging records measured or assumed provenance for every leaf before validating the
complete BuildingSpec. No archetype or material catalogue is loaded here.

Examples
--------
Example::

    from epsm_core import BuildingBuilder

    builder = BuildingBuilder(building_use="residential")  # bundled Sveby residential operations
"""

from copy import deepcopy
from typing import Literal

from .specs import BuildingSpec, ProvenanceSpec, SourceRecord


class BuildingBuilder:
    """Assemble validated buildings from default or caller-owned assumptions.

    Attributes
    ----------
    profile : str or None
        Versioned profile name recorded as the source of assumed leaves.
    assumptions : dict
        Deep-copied nested default profile used by build.

    Notes
    -----
    With no arguments, selects no profile. Selecting building_use loads a named Sveby
    profile; supplying both custom-profile arguments retains caller-owned behavior. Assumptions are
    copied at construction and the source of every merged leaf is recorded. This builder
    does not load material, weather or physical-archetype catalogues.

    Examples
    --------
    Example::

        from epsm_core import BuildingBuilder

        builder = BuildingBuilder(building_use="residential")
        assert builder.profile.startswith("sveby.residential.v2.0")
    """

    def __init__(
        self,
        *,
        assumption_profile: str | None = None,
        assumptions: dict | None = None,
        building_use: Literal["residential", "office", "school"] | None = None,
        calendar_year: int | None = None,
        active_dates=None,
        calendar_source: str | None = None,
    ):
        """Capture a named assumption profile without retaining caller-owned mappings.

        Parameters
        ----------
        assumption_profile : str or None
            Named and externally managed default profile recorded in provenance. Supply with
            assumptions for a custom profile. Default: ``None``.
        assumptions : dict or None
            Nested default values explicitly supplied by the caller. Supply with
            assumption_profile for a custom profile. Default:
            ``None``.

        building_use : residential, office, school or None
            Select the versioned Sveby operational profile. Office and school require
            calendar_year, active_dates and a nonempty calendar_source.
        calendar_year, active_dates, calendar_source
            Explicit local-standard-time calendar; no holiday list is inferred.
            References: nonresidential.py source locators and standards.py monthly tables.

        Returns
        -------
        None
            Initializes profile and a deep copy of assumptions.

        Raises
        ------
        ValueError
            If exactly one of assumption_profile and assumptions is supplied. A custom
            profile requires both so its provenance identity cannot be detached from its
            values.

        Notes
        -----
        The no-argument form selects no assumptions and performs no lookup. Custom profiles do
        not read files or registries. Construction of a validated BuildingSpec is deferred to
        build. Sveby supplies operations, not weather or physical fabric, so those inputs
        remain required when ``build`` is called.

        Examples
        --------
        Example::

            from epsm_core import BuildingBuilder

            standard = BuildingBuilder(building_use="residential")
            custom = BuildingBuilder(
                assumption_profile="study-v1",
                assumptions={},
            )
        """

        if building_use not in {None, "residential", "office", "school"}:
            raise ValueError("Unknown building_use; choose residential, office or school")
        if assumption_profile is not None and (not isinstance(assumption_profile, str) or not assumption_profile.strip()):
            raise ValueError("assumption_profile must be a nonempty name")
        if assumption_profile is None and assumptions is None:
            if building_use is None:
                self.profile = None
                self.assumptions = {}
                return
            if building_use == "residential":
                from .standards import load_sveby_spec
                standard = load_sveby_spec()
                assumptions = standard.building_assumptions(calendar_year=calendar_year)
            else:
                from .nonresidential import load_sveby_office_v1, load_sveby_school_v1
                standard = (load_sveby_office_v1() if building_use == "office" else load_sveby_school_v1())
                if calendar_year is None or active_dates is None or calendar_source is None:
                    raise ValueError("Office/school profiles require year, active_dates and calendar_source")
                assumptions = standard.building_assumptions(calendar_year=calendar_year,
                    active_dates=active_dates, calendar_source=calendar_source)
            assumption_profile = standard.profile_id
        elif assumption_profile is None or assumptions is None:
            raise ValueError(
                "assumption_profile and assumptions must be supplied together, or both omitted"
            )
        if (building_use is not None and building_use != "residential" and assumption_profile.startswith("sveby.")
                and not assumption_profile.startswith(f"sveby.{building_use}.")):
            raise ValueError("Choose a matching operational profile for the requested building use")
        self.profile = assumption_profile
        self.assumptions = deepcopy(assumptions)

    def build(self, *, source: str = "user", input_status: Literal["measured", "inferred", "assumed"] = "measured", **known) -> BuildingSpec:
        """Merge measured inputs over profile defaults and record leaf-level provenance.

        Parameters
        ----------
        input_status : measured, inferred or assumed
            Provenance for supplied leaves; choose assumed for synthetic scenarios.
        source : str
            Evidence source assigned to supplied leaves. Default: ``'user'``.
        **known : dict
            Explicit values taking precedence over the assumption defaults.

        Returns
        -------
        BuildingSpec
            Validated complete building with generated source records.

        Notes
        -----
        Nested dictionaries merge recursively. Supplied leaves use input_status (measured
        by default), including a value equal to its default; missing leaves are assumed. Caller-supplied provenance is
        replaced. Typed Pydantic specifications are serialized with ``exclude_unset=True`` so
        their schema defaults do not accidentally override missing leaves supplied by the named
        profile.

        Examples
        --------
        Supply a BuildingBuilder as ``builder`` with an explicit assumption profile; complete
        building input fields as the ``known`` mapping.

        Example::

            building = builder.build(source="survey", **known)
        """

        if input_status not in ("measured", "inferred", "assumed"):
            raise ValueError("Unknown supplied-input evidence status")
        supplied_use = known.get("use")
        category = (supplied_use.get("occupancy_category") if isinstance(supplied_use, dict)
                    else getattr(supplied_use, "occupancy_category", None))
        if self.profile is not None and self.profile.startswith("sveby.residential.") and category == "non_residential":
            raise ValueError("Select an office/school or explicit custom assumption profile")
        if self.profile is not None and self.profile.startswith(("sveby.office.", "sveby.school.")) and category == "residential":
            raise ValueError("Select an operational profile compatible with residential occupancy")
        # 1. Merge measured inputs over profile defaults and record leaf-level provenance.
        records = []

        def supplied_mapping(value):
            """Preserve which fields a supplied Pydantic specification set explicitly."""
            if hasattr(value, "model_dump"):
                return value.model_dump(mode="json", exclude_unset=True)
            return value

        def merge(defaults, overrides, prefix=""):
            """Recursively combine default and override dictionaries in stable key order.

            Parameters
            ----------
            defaults : dict
                Nested default values explicitly supplied by the caller.
            overrides : dict
                Explicit values taking precedence over the assumption defaults.
            prefix : str
                Dotted path prefix accumulated during recursive provenance merging. Default: ``''``.

            Returns
            -------
            dict
                Merged subtree.

            Notes
            -----
            Appends one SourceRecord per non-dictionary leaf to the enclosing records list. Dotted
            paths reflect nesting; overriding a scalar with a mapping requires compatible defaults.

            Examples
            --------
            Within the enclosing operation, after its captured state has been initialized::

                merge({"height": 3}, {"height": 4}, "geometry")
            """

            # 1. Recursively combine default and override dictionaries in stable key order.
            result = {}
            for key in sorted(defaults.keys() | overrides.keys()):
                path = f"{prefix}.{key}".strip(".")
                assumed = key not in overrides
                default_value = supplied_mapping(defaults.get(key, {}))
                override_value = supplied_mapping(overrides.get(key, {}))
                value = default_value if assumed else override_value
                # NOTE: Recursive merging assumes the corresponding defaults are also a mapping.
                if isinstance(value, dict):
                    nested_defaults = default_value if isinstance(default_value, dict) else {}
                    nested_overrides = override_value if isinstance(override_value, dict) else {}
                    result[key] = merge(nested_defaults, nested_overrides, path)
                else:
                    result[key] = value
                    records.append(
                        SourceRecord(
                            field_path=path,
                            status="assumed" if assumed else input_status,
                            source=self.profile if assumed else source,
                            assumption_profile=self.profile if assumed else None,
                        )
                    )
            return result

        data = merge(self.assumptions, known)
        data["provenance"] = ProvenanceSpec(records=tuple(records))
        return BuildingSpec.model_validate(data)
