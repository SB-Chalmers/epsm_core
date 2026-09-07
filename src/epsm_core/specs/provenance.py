# File: specs/provenance.py
# Purpose: Provenance input specifications.
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
#   2026-09-06 - Document provenance interfaces, examples, constraints and processing rationale.

"""Provenance input specifications.

Notes
-----
Records retain input evidence, external reference identities, nominal quantities and
renovation history. They do not fetch datasets or calculate costs or impacts.
Administrative provenance is excluded from the current physical building hash.

Examples
--------
Example::

    from epsm_core.specs.provenance import SourceRecord

    record = SourceRecord(
        field_path="geometry.parts",
        status="assumed",
        source="study-v1",
        assumption_profile="study-v1",
    )
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from .base import Fraction, Nonnegative, Spec


class SourceRecord(Spec):
    """Trace one input leaf to measured, inferred or assumed evidence.

    Attributes
    ----------
    field_path : str
        Dotted path of the input leaf described by this source record.  Required at
        construction.
    status : Literal['measured', 'inferred', 'assumed']
        Evidence or processing outcome classification for the record.  Required at
        construction.
    source : str
        Evidence source assigned to supplied leaves.  Required at construction.
    confidence : Fraction | None
        Optional confidence fraction between zero and one. In [0, 1] when supplied. Default:
        ``None``.
    assumption_profile : str | None
        Named and externally managed default profile recorded in provenance.  Default:
        ``None``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    field_path is a dotted model path. confidence is an optional fraction;
    assumption_profile identifies the named source of a default. Evidence is supplied
    explicitly, not looked up.

    Examples
    --------
    Example::

        from epsm_core.specs.provenance import SourceRecord

        record = SourceRecord(
            field_path="geometry.parts",
            status="assumed",
            source="study-v1",
            assumption_profile="study-v1",
        )
    """

    field_path: str
    status: Literal["measured", "inferred", "assumed"]
    source: str
    confidence: Fraction | None = None
    assumption_profile: str | None = None


class ProvenanceSpec(Spec):
    """Container for explicit field-level source records.

    Attributes
    ----------
    records : tuple[SourceRecord, ...]
        Ordered field-level source records.  Default: ``()``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Records describe provenance without changing BuildingSpec physical identity. No external
    database or catalogue is contacted.

    Examples
    --------
    Example::

        from epsm_core.specs.provenance import ProvenanceSpec

        provenance = ProvenanceSpec()
    """

    records: tuple[SourceRecord, ...] = ()


class DatasetReference(Spec):
    """Versioned reference to an external catalogue item.

    Attributes
    ----------
    dataset : str
        Dataset identity/version or stable item identity, as appropriate to the record.
        Required at construction.
    version : str
        Dataset identity/version or stable item identity, as appropriate to the record.
        Required at construction.
    item_id : str
        Dataset identity/version or stable item identity, as appropriate to the record.
        Required at construction.
    uri : str | None
        Optional external reference URI; core does not fetch it.  Default: ``None``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Stores identifiers and an optional URI only. Resolving environmental or economic factors
    belongs to external workflows.

    Examples
    --------
    Example::

        from epsm_core.specs.provenance import DatasetReference

        reference = DatasetReference(
            dataset="materials", version="1", item_id="concrete"
        )
    """

    dataset: str
    version: str
    item_id: str
    uri: str | None = None


class AssessmentReference(Spec):
    """Administrative reference to a price or lifecycle assessment context.

    Attributes
    ----------
    identifier : str
        Stable identifier within the owning collection.  Required at construction.
    currency : str | None
        Optional assessment labels or external factor reference; no cost or impact is
        calculated here.  Default: ``None``.
    price_base_year : int | None
        Optional assessment labels or external factor reference; no cost or impact is
        calculated here.  Default: ``None``.
    lifecycle_stage : str | None
        Optional assessment labels or external factor reference; no cost or impact is
        calculated here.  Default: ``None``.
    factor_source : DatasetReference | None
        Optional assessment labels or external factor reference; no cost or impact is
        calculated here.  Default: ``None``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Currency, price year and lifecycle stage are optional labels; core performs no monetary
    or environmental calculation from this record.

    Examples
    --------
    Example::

        from epsm_core.specs.provenance import AssessmentReference

        reference = AssessmentReference(
            identifier="study-2026", currency="SEK", price_base_year=2026
        )
    """

    identifier: str
    currency: str | None = None
    price_base_year: int | None = None
    lifecycle_stage: str | None = None
    factor_source: DatasetReference | None = None


class PhysicalQuantity(Spec):
    """Nominal material, glazing or equipment quantity with stable physical identity.

    Attributes
    ----------
    item_id : str
        Dataset identity/version or stable item identity, as appropriate to the record.
        Required at construction.
    element_id : str
        Stable physical element identity grouping material layers or equipment.  Required at
        construction.
    role : str
        Construction role or emitted construction name, including reverse suffix where
        needed.  Required at construction.
    kind : Literal['opaque_layer', 'glazing', 'equipment']
        Supported measure discriminator or geometric classification, according to the
        record.  Required at construction.
    physical_sha256 : str
        Digest of nominal physical configuration; metadata is not a substitute for measured
        quantities.  Required at construction.
    area_m2 : Nonnegative | None
        Net footprint or physical quantity area in square metres; optional quantities remain
        absent when unspecified. Nonnegative when supplied. Default: ``None``.
    volume_m3 : Nonnegative | None
        Optional nonnegative physical volume in m3, mass in kg or equipment count.
        Nonnegative when supplied. Default: ``None``.
    mass_kg : Nonnegative | None
        Optional nonnegative physical volume in m3, mass in kg or equipment count.
        Nonnegative when supplied. Default: ``None``.
    count : Nonnegative | None
        Optional nonnegative physical volume in m3, mass in kg or equipment count.
        Nonnegative when supplied. Default: ``None``.
    dataset_references : tuple[DatasetReference, ...]
        Explicit external catalogue references carried into audit records.  Default: ``()``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Optional quantities are nonnegative. Glazing has no invented volume/mass; equipment uses
    count. physical_sha256 stores a digest but this field itself has no digest-format
    validator.

    Examples
    --------
    Example::

        from epsm_core.specs.provenance import PhysicalQuantity

        quantity = PhysicalQuantity(
            item_id="equipment.pv.0",
            element_id="equipment.pv.0",
            role="pv",
            kind="equipment",
            physical_sha256="0" * 64,
            count=1,
        )
    """

    item_id: str
    element_id: str
    role: str
    kind: Literal["opaque_layer", "glazing", "equipment"]
    physical_sha256: str
    area_m2: Nonnegative | None = None
    volume_m3: Nonnegative | None = None
    mass_kg: Nonnegative | None = None
    count: Nonnegative | None = None
    dataset_references: tuple[DatasetReference, ...] = ()


class QuantityChange(Spec):
    """Before/after quantity record for one physical change.

    Attributes
    ----------
    action : Literal['added', 'removed', 'replaced']
        Whether the quantity is added, removed or replaced.  Required at construction.
    before : PhysicalQuantity | None
        Optional physical quantity on each side of a renovation change.  Default: ``None``.
    after : PhysicalQuantity | None
        Optional physical quantity on each side of a renovation change.  Default: ``None``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    action distinguishes added, removed and replaced. The renovation workflow creates
    matching before/after values; this model does not enforce action-dependent presence
    constraints.

    Examples
    --------
    Example::

        from epsm_core.specs.provenance import PhysicalQuantity
        from epsm_core.specs.provenance import QuantityChange

        quantity = PhysicalQuantity(
            item_id="pv",
            element_id="pv",
            role="pv",
            kind="equipment",
            physical_sha256="0" * 64,
            count=1,
        )
        change = QuantityChange(action="added", after=quantity)
    """

    action: Literal["added", "removed", "replaced"]
    before: PhysicalQuantity | None = None
    after: PhysicalQuantity | None = None


class RenovationRecord(Spec):
    """Chronological measure record with before/after physical identities and quantities.

    Attributes
    ----------
    measure : str
        Discriminator identifying the applied renovation operation.  Required at
        construction.
    effective_date : date
        Measure date, accepting ISO YYYY-MM-DD; events must be appended chronologically.
        Required at construction.
    targeted_element_ids : tuple[str, ...]
        Optional exact set of all affected physical elements; does not restrict measure
        scope.  Required at construction.
    before_sha256 : str
        Physical building hash immediately before or after the measure.  Required at
        construction.
    after_sha256 : str
        Physical building hash immediately before or after the measure.  Required at
        construction.
    parameters_json : str
        JSON serialization of the typed renovation measure.  Required at construction.
    changes : tuple[QuantityChange, ...]
        Audited added, removed and replaced physical quantities.  Required at construction.
    dataset_references : tuple[DatasetReference, ...]
        Explicit external catalogue references carried into audit records.  Default: ``()``.
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
    parameters_json preserves the typed measure. Date ordering and affected-target
    completeness are enforced by apply_renovation; this record stores the resulting evidence
    and external references.

    Examples
    --------
    Example::

        from epsm_core.specs.provenance import RenovationRecord

        record = RenovationRecord(
            measure="install_pv",
            effective_date="2026-09-06",
            targeted_element_ids=("equipment.pv.0",),
            before_sha256="0" * 64,
            after_sha256="1" * 64,
            parameters_json="{}",
            changes=(),
        )
    """

    measure: str
    effective_date: date
    targeted_element_ids: tuple[str, ...]
    before_sha256: str
    after_sha256: str
    parameters_json: str
    changes: tuple[QuantityChange, ...]
    dataset_references: tuple[DatasetReference, ...] = ()
    assessment_references: tuple[AssessmentReference, ...] = ()
