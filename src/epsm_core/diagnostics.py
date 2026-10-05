# File: diagnostics.py
# Purpose: Fail-closed EnergyPlus diagnostics with explicit, versioned warning exceptions.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-09-11
# Changelog:
#   2026-09-11 - Reject geometry repairs and classify shadow limits and missing outputs.
#   2026-09-06 - Document diagnostics interfaces, examples, constraints and processing rationale.

"""Fail-closed EnergyPlus diagnostics with explicit, versioned warning exceptions.

Notes
-----
Diagnostic acceptance fails for missing logs, unapproved warnings and severe/fatal
messages. Recurring warning summaries are deduplicated by exact normalized message
identity. Exception rules require engine version, evidence conditions and occurrence
bounds.

Examples
--------
Example::

    from epsm_core.diagnostics import error_diagnostics

    from tempfile import TemporaryDirectory
    from pathlib import Path

    with TemporaryDirectory() as folder:
        result = error_diagnostics(Path(folder) / "missing.err")
    assert result["accepted"] is False
"""

import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class WarningRule:
    """Versioned, bounded exception for a specific EnergyPlus warning.

    Attributes
    ----------
    identifier : str
        Stable identifier within the owning collection.  Required at construction.
    version : str
        Dataset identity/version or stable item identity, as appropriate to the record.
        Required at construction.
    engine_version : str
        Reported compiler release or EnergyPlus version.  Required at construction.
    pattern : str
        Regular expression for WarningRule, or low/mid/high/auto window family for
        WindowLayoutSpec.  Required at construction.
    rationale : str
        Reviewed reason why a narrowly defined warning may be accepted.  Required at
        construction.
    expected_conditions : tuple[str, ...]
        Evidence labels that must all be verified before a warning rule applies.  Required
        at construction.
    max_occurrences : int
        Positive upper bound on matching warning occurrences.  Required at construction.

    Notes
    -----
    All identity/evidence fields must be nonempty, regex syntax valid and occurrence limit
    positive. Fatal, severe and ALWAYS_FAIL warning categories remain unapprovable
    regardless of supplied rules.

    Examples
    --------
    Example::

        from epsm_core.diagnostics import WarningRule

        rule = WarningRule(
            "example",
            "1",
            "24.2",
            "Known message",
            "Reviewed diagnostic",
            ("verified_condition",),
            1,
        )
    """

    identifier: str
    version: str
    engine_version: str
    pattern: str
    rationale: str
    expected_conditions: tuple[str, ...]
    max_occurrences: int

    def __post_init__(self):
        """Validate the completeness of an explicit warning exception.

        Returns
        -------
        None
            Successful construction retains the supplied rule.

        Raises
        ------
        ValueError
            Rejected conditions: Warning exceptions require version, rationale, conditions and
            occurrence limit.

        Notes
        -----
        Requires nonempty identity, versions, regex, rationale, conditions and a positive
        occurrence limit. Invalid regular expressions propagate re.error.

        Examples
        --------
        Example::

            from epsm_core.diagnostics import WHOLE_BUILDING_AREA_RULE

            rule = WHOLE_BUILDING_AREA_RULE
            rule.__post_init__()
        """

        # 1. Validate the completeness of an explicit warning exception.
        if (
            not all(
                (
                    self.identifier,
                    self.version,
                    self.engine_version,
                    self.pattern,
                    self.rationale,
                    self.expected_conditions,
                )
            )
            or self.max_occurrences < 1
        ):
            raise ValueError(
                "Warning exceptions require version, rationale, conditions and occurrence limit"
            )
        re.compile(self.pattern)


def category(text):
    """Classify an EnergyPlus diagnostic by ordered textual patterns.

    Parameters
    ----------
    text : str
        Original diagnostic text to classify.

    Returns
    -------
    str
        Recognized category or unrecognized_warning.

    Notes
    -----
    Matching is case-insensitive and the first category wins. Classification does not itself
    approve a warning.

    Examples
    --------
    Example::

        from epsm_core.diagnostics import category

        assert category("floor area differs") == "floor_area"
    """

    # 1. Classify an EnergyPlus diagnostic by ordered textual patterns.
    text = text.lower()
    for name, pattern in (
        (
            "missing_output",
            r"requested.*(?:variables|meters).*not generated|(?:output:variable|output:meter).*not found",
        ),
        ("incomplete_view_factors", r"view factors? (?:not complete|.*incomplete)"),
        (
            "shadow_overlap_limit",
            r"too many (?:vertices|figures).*shadow|(?:shadow|overlap).*too many (?:vertices|figures)|too many (?:vertices|figures)",
        ),
        (
            "geometry_repair",
            r"(?:drop|remov|revers)\w*.*vert(?:ex|ices)|vert(?:ex|ices).*?(?:drop|remov|revers)|(?:floor|roof).*?(?:upside.down|revers)",
        ),
        (
            "geometry_mismatch",
            r"(?:subsurface|base surface).*?(?:normal|facing).*?(?:differ|mismatch)|interzone.*?(?:area|azimuth).*?(?:differ|mismatch)",
        ),
        ("convergence_failure", r"converg.*(?:fail|not)|(?:fail|not).*converg"),
        (
            "discarded_surface",
            r"(?:discarded|ignored|removed) surfaces?|surface[^:]* (?:discarded|ignored|removed)",
        ),
        (
            "invalid_geometry",
            r"(?:invalid|degenerate|non.convex|non.planar|zero area|not (?:fully )?enclosed).*|surface.*(?:invalid|not coplanar)",
        ),
        ("floor_area", r"floor area"),
        ("kiva", r"kiva|foundation"),
        ("unused_construction", r"unused construction"),
    ):
        if re.search(pattern, text):
            return name
    return "unrecognized_warning"


ALWAYS_FAIL = {
    "missing_output",
    "shadow_overlap_limit",
    "geometry_repair",
    "geometry_mismatch",
    "incomplete_view_factors",
    "convergence_failure",
    "discarded_surface",
    "invalid_geometry",
}


def error_diagnostics(path, *, engine_version="24.2", rules=(), conditions=()):
    """Parse an EnergyPlus error log and evaluate strict warning acceptance.

    Parameters
    ----------
    path : str or Path
        Local input file path; the operation never downloads missing input.
    engine_version : str
        Engine version against which warning rules are matched. Default: ``'24.2'``.
    rules : sequence of WarningRule
        Explicit versioned warning exceptions; severe/fatal and always-fail categories
        cannot be waived. Default: ``()``.
    conditions : sequence of str
        Verified condition labels required by warning-exception rules. Default: ``()``.

    Returns
    -------
    dict
        Messages, occurrence totals, acceptance status and source path.

    Notes
    -----
    Missing or empty logs fail. Recurring summaries merge only identical normalized messages
    and avoid double-counting examples. Severe/fatal and ALWAYS_FAIL categories cannot be
    waived; exceptions need matching engine, conditions, full regex and count limit.

    Examples
    --------
    Example::

        from epsm_core.diagnostics import error_diagnostics

        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as folder:
            result = error_diagnostics(Path(folder) / "missing.err")
        assert result["accepted"] is False
    """

    # 1. Parse an EnergyPlus error log and evaluate strict warning acceptance.
    path = Path(path)
    text = path.read_text(errors="replace") if path.exists() else ""
    messages = []
    current = None
    phase = "initialization"
    for line in text.splitlines():
        if "Beginning Simulation" in line or "Simulation Error Summary" in line:
            phase = "simulation"
        if "Warmup" in line and "Summary" in line:
            phase = "warmup"
        match = re.search(r"\*\*\s*(Warning|Severe|Fatal)\s*\*\*\s*(.*)", line, re.I)
        if match:
            current = dict(
                severity=match[1].lower(),
                original_text=line,
                summary=match[2],
                phase=phase,
                occurrence_count=1,
                recurring_summary=False,
            )
            messages.append(current)
        elif current and re.search(r"\*\*\s*~~~\s*\*\*", line):
            current["original_text"] += "\n" + line
            count = re.search(
                r"(?:occurred|occurrences\s*=)\s*(\d+)\s*(?:total\s*)?(?:times)?", line, re.I
            )
            if count:
                current["occurrence_count"] = int(count[1])
                current["recurring_summary"] = True
    # A recurring summary reports the total, including earlier emitted examples.
    # Merge only exact normalized message keys; never aggregate a category broadly.
    # 2. Merge exact recurring messages without counting earlier examples twice.
    merged = {}
    for m in messages:
        summary_key = re.sub(r"\s+", " ", m["summary"]).strip().rstrip(".")
        # EnergyPlus spells the initial example and recurring total differently.
        # They describe the same local solve; retain both texts but count once.
        if re.fullmatch(
            r"WetBulb not converged after (?:101|max) iterations\(PsyTwbFnTdbWPb\)", summary_key
        ):
            summary_key = "WetBulb not converged (PsyTwbFnTdbWPb)"
        key = (m["severity"], summary_key)
        if key in merged:
            old = merged[key]
            old["occurrence_count"] = (
                max(old["occurrence_count"], m["occurrence_count"])
                if m["recurring_summary"] or old["recurring_summary"]
                else old["occurrence_count"] + m["occurrence_count"]
            )
            old["original_text"] += "\n" + m["original_text"]
            old["recurring_summary"] |= m["recurring_summary"]
        else:
            merged[key] = m
    messages = list(merged.values())
    # 3. Classify messages and apply only versioned, evidence-backed bounded exceptions.
    for m in messages:
        m["category"] = category(m["original_text"])
        m["affected_objects"] = sorted(
            set(
                re.findall(
                    r'(?i)(?:zone|surface|construction|object)\s*(?:name)?\s*[=:]\s*["\']?([^"\'\n,]+)',
                    m["original_text"],
                )
            )
        )
        m["approved"] = False
        m["exception_rule"] = None
        if m["severity"] == "warning" and m["category"] not in ALWAYS_FAIL:
            for rule in rules:
                if (
                    rule.engine_version == engine_version
                    and set(rule.expected_conditions) <= set(conditions)
                    and m["occurrence_count"] <= rule.max_occurrences
                    and re.fullmatch(rule.pattern, m["summary"])
                ):
                    m["approved"] = True
                    m["exception_rule"] = asdict(rule)
                    break
    # 4. A missing/empty log or any unapproved message prevents diagnostic acceptance.
    return dict(
        policy_version="strict-1",
        engine_version=engine_version,
        messages=messages,
        accepted=path.exists() and bool(text.strip()) and all(m["approved"] for m in messages),
        warning_count=sum(m["occurrence_count"] for m in messages if m["severity"] == "warning"),
        severe_count=sum(m["occurrence_count"] for m in messages if m["severity"] == "severe"),
        fatal_count=sum(m["occurrence_count"] for m in messages if m["severity"] == "fatal"),
        invalid_view_factor_count=sum(
            m["occurrence_count"] for m in messages if m["category"] == "incomplete_view_factors"
        ),
        err_path=str(path),
    )


WHOLE_BUILDING_AREA_RULE = WarningRule(
    identifier="explicit_whole_building_space_area",
    version="1",
    engine_version="24.2",
    pattern=re.escape(
        "GetSurfaceData: Entered Space Floor Area(s) differ more than 5% from calculated Space Floor Area(s)."
    ),
    rationale="The explicit Space area includes intermediate physical slabs represented by InternalMass. "
    "The compiler reconciles this area to the geometric base floors plus each physical slab once.",
    expected_conditions=("whole_building_zoning", "space_area_equals_base_plus_physical_slabs"),
    max_occurrences=1,
)

# DisplayExtraWarnings spells the same compiler-proven area convention per space.
WHOLE_BUILDING_AREA_DETAIL_RULE = WarningRule(
    identifier="explicit_whole_building_space_area_detail",
    version="1",
    engine_version="24.2",
    pattern=r'GetSurfaceData: Entered Floor Area for Space="[^"]+" is [0-9.]+% different from the calculated Floor Area\.',
    rationale=WHOLE_BUILDING_AREA_RULE.rationale,
    expected_conditions=WHOLE_BUILDING_AREA_RULE.expected_conditions,
    max_occurrences=1,
)


def compiler_warning_conditions(spec, model, report):
    """Derive permitted warning conditions from emitted geometry evidence.

    Parameters
    ----------
    spec : BuildingSpec
        Validated building input; geometry-only helpers also accept an object exposing the
        fields they consume.
    model : dict
        EnergyPlus epJSON object mapping keyed by object type and name.
    report : CompilationReport or dict
        Compilation metadata; SQL/compiler consumers use CompilationReport, viewer_data uses
        its decoded data mapping.

    Returns
    -------
    tuple of str
        Proven conditions for the whole-building area exception.

    Notes
    -----
    An assertion by the caller is insufficient. Base floor areas plus each physical slab
    must reconcile to every reported zone floor area.

    Examples
    --------
    Supply a validated BuildingSpec as ``building``; the matching CompilationReport as
    ``report``; the matching compiled epJSON dictionary as ``model``.

    Example::

        from epsm_core.diagnostics import compiler_warning_conditions

        conditions = compiler_warning_conditions(building, model, report)
    """
    # 1. Derive permitted warning conditions from emitted geometry evidence.
    if spec.geometry.zoning.mode != "whole_building":
        return ()
    from .surface_checks import close, properties, vertices

    expected = {z: 0.0 for z in report.data["zones"]}
    for face in model["BuildingSurface:Detailed"].values():
        if face["surface_type"] == "Floor":
            expected[face["zone_name"]] += properties(vertices(face))[0]
    for mass in report.data["internal_mass"]:
        expected[mass["zone"]] += mass["area_m2"]
    if not report.data["internal_mass"]:
        return ()
    if all(
        close(area, report.data["zones"][zone]["floor_area_m2"]) for zone, area in expected.items()
    ):
        return ("whole_building_zoning", "space_area_equals_base_plus_physical_slabs")
    return ()
