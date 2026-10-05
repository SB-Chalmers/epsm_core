# SPDX-License-Identifier: MIT
"""Explicit, versioned domestic hot-water assumptions by building type.

Profiles resolve annual useful thermal demand onto the existing UseSpec. They
do not infer occupancy, read EPC observations or convert demand to purchased
energy. Loading a profile is an explicit caller choice; Sveby defaults remain
unchanged and importing this module performs no resource or network reads.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Annotated, Literal

from pydantic import Field

from .specs import SourceRecord, UseSpec
from .specs.base import Nonnegative, Spec

BuildingType = Literal[
    "single_family", "multi_family", "office", "school", "non_residential"
]
NonemptyText = Annotated[str, Field(min_length=1, pattern=r"\S")]


class DHWProfileSpec(Spec):
    """A sourced annual DHW assumption, expressed per square metre of Atemp.

    ``epc_normal_use`` version 1 stores the historical BEN coefficients before
    production efficiency is applied. These describe standardized use, not a
    forecast of actual consumption. Storage/circulation losses and carrier
    conversion are outside this profile. The caller must use compatible Atemp
    as the building's load_reference_area_m2.

    The profile changes only the annual DHW intensity. Existing monthly or daily
    timing remains a caller assumption and is conserved by the compiler.
    """

    profile_id: NonemptyText
    building_type: BuildingType
    purpose: Literal["epc_normal_use"]
    version: Literal["1"]
    area_basis: Literal["Atemp"]
    dhw_kwh_m2_year: Nonnegative
    source_uri: NonemptyText
    source_locator: NonemptyText

    def apply_to(self, use: UseSpec) -> UseSpec:
        """Return a validated use with this DHW rate and all other inputs retained."""
        return use.updated(dhw_kwh_m2_year=self.dhw_kwh_m2_year)

    def source_record(
        self, field_path: str = "use.dhw_kwh_m2_year"
    ) -> SourceRecord:
        """Return assumption provenance for the resolved rate, never a meter claim.

        Add this record to the caller's building provenance, replacing any older
        record for the same field. Applying a profile to UseSpec alone cannot
        update the enclosing BuildingSpec provenance.
        """
        return SourceRecord(
            field_path=field_path,
            status="assumed",
            source=f"{self.source_uri}; {self.source_locator}",
            assumption_profile=self.profile_id,
        )


def load_dhw_profile(
    building_type: BuildingType,
    *,
    purpose: Literal["epc_normal_use"],
    version: str = "1",
) -> DHWProfileSpec:
    """Load a pinned, type-specific annual DHW assumption from package data.

    Parameters
    ----------
    building_type : str
        single_family, multi_family, office, school or non_residential. Mixed
        programmes need separate component profiles and explicit area shares.
    purpose : str
        Explicitly select epc_normal_use. Actual-use estimation is not inferred
        from these standardized coefficients.
    version : str
        Version of this EPSM profile resource, currently "1". The source is BEN
        BFS 2016:12 with BFS 2017:6 amendments, not the latest regulations.

    Returns
    -------
    DHWProfileSpec
        Immutable assumption with source, area basis and profile identity.

    Raises
    ------
    ValueError
        For unsupported selectors or an unreviewed change to the pinned resource.
    FileNotFoundError
        If package installation omitted the resource.

    Examples
    --------
    Example::

        from epsm_core import load_dhw_profile, load_sveby_spec

        profile = load_dhw_profile("multi_family", purpose="epc_normal_use")
        use = profile.apply_to(load_sveby_spec().use_spec(calendar_year=2024))
        assert use.dhw_kwh_m2_year == 25
    """
    expected_rates = {
        "single_family": 20.0,
        "multi_family": 25.0,
        "office": 2.0,
        "school": 2.0,
        "non_residential": 2.0,
    }
    if purpose != "epc_normal_use":
        raise ValueError(f"Unsupported DHW profile purpose: {purpose!r}")
    if version != "1":
        raise ValueError(f"Unsupported DHW profile version: {version!r}")
    if building_type not in expected_rates:
        raise ValueError(f"Unsupported DHW building type: {building_type!r}")
    resource = files("epsm_core").joinpath("standards_data/dhw_epc_normal_use_v1.json")
    with resource.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    expected = {
        "schema_version": 1,
        "profile_id": "ben.dhw.normal_use.v1",
        "purpose": "epc_normal_use",
        "version": "1",
        "area_basis": "Atemp",
        "dhw_kwh_m2_year_by_type": expected_rates,
    }
    if any(data.get(key) != value for key, value in expected.items()):
        raise ValueError("Bundled DHW values do not match the reviewed EPC normal-use v1 profile")
    return DHWProfileSpec(
        profile_id=f"{data['profile_id']}.{building_type}",
        building_type=building_type,
        purpose=data["purpose"],
        version=data["version"],
        area_basis=data["area_basis"],
        dhw_kwh_m2_year=data["dhw_kwh_m2_year_by_type"][building_type],
        source_uri=data["source_uri"],
        source_locator=data["source_locator_by_type"][building_type],
    )
