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
# Date modified: 2026-09-06
# Changelog:
#   2026-09-06 - Document builder interfaces, examples, constraints and processing rationale.

"""Convenience assembly with explicit, externally supplied assumption profiles.

Notes
-----
Default profiles are supplied by the caller and deep-copied. Recursive dictionary
merging records measured or assumed provenance for every leaf before validating the
complete BuildingSpec. No archetype or material catalogue is loaded here.

Examples
--------
Example::

    from epsm_core.builder import BuildingBuilder

    builder = BuildingBuilder(assumption_profile="study-v1", assumptions={})
"""

from copy import deepcopy

from .specs import BuildingSpec, ProvenanceSpec, SourceRecord


class BuildingBuilder:
    """Assemble validated buildings from an explicit named assumption profile.

    Attributes
    ----------
    profile : str
        Name recorded as the source of assumed leaves.
    assumptions : dict
        Deep-copied nested default profile used by build.

    Notes
    -----
    Copies the supplied assumption dictionary at construction and records the source of
    every merged leaf. This builder does not load material or archetype catalogues.

    Examples
    --------
    Example::

        from epsm_core.builder import BuildingBuilder

        builder = BuildingBuilder(assumption_profile="study-v1", assumptions={})
    """

    def __init__(self, *, assumption_profile: str, assumptions: dict):
        """Capture a named assumption profile without retaining caller-owned mappings.

        Parameters
        ----------
        assumption_profile : str
            Named and externally managed default profile recorded in provenance.
        assumptions : dict
            Nested default values explicitly supplied by the caller.

        Returns
        -------
        None
            Initializes profile and a deep copy of assumptions.

        Notes
        -----
        No files or registries are read. Construction of a validated BuildingSpec is deferred to
        build.

        Examples
        --------
        Example::

            from epsm_core.builder import BuildingBuilder

            builder = BuildingBuilder(assumption_profile="study-v1", assumptions={})
        """

        self.profile = assumption_profile
        self.assumptions = deepcopy(assumptions)

    def build(self, *, source: str = "user", **known) -> BuildingSpec:
        """Merge measured inputs over profile defaults and record leaf-level provenance.

        Parameters
        ----------
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
        Nested dictionaries merge recursively. Any supplied leaf is marked measured, including a
        value equal to its default; missing leaves are assumed. Caller-supplied provenance is
        replaced.

        Examples
        --------
        Supply a BuildingBuilder as ``builder`` with an explicit assumption profile; complete
        building input fields as the ``known`` mapping.

        Example::

            building = builder.build(source="survey", **known)
        """

        # 1. Merge measured inputs over profile defaults and record leaf-level provenance.
        records = []

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
                value = defaults[key] if assumed else overrides[key]
                # NOTE: Recursive merging assumes the corresponding defaults are also a mapping.
                if isinstance(value, dict):
                    result[key] = merge(defaults.get(key, {}), overrides.get(key, {}), path)
                else:
                    result[key] = value
                    records.append(
                        SourceRecord(
                            field_path=path,
                            status="assumed" if assumed else "measured",
                            source=self.profile if assumed else source,
                            assumption_profile=self.profile if assumed else None,
                        )
                    )
            return result

        data = merge(self.assumptions, known)
        data["provenance"] = ProvenanceSpec(records=tuple(records))
        return BuildingSpec.model_validate(data)
