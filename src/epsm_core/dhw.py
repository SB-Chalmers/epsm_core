# SPDX-License-Identifier: MIT
"""Explicit, versioned domestic hot-water assumptions by building type.

Profiles resolve annual useful thermal demand onto the existing UseSpec. They
do not infer occupancy, read EPC observations or convert demand to purchased
energy. Loading a profile is an explicit caller choice; Sveby defaults remain
unchanged and importing this module performs no resource or network reads.
"""

from __future__ import annotations

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
