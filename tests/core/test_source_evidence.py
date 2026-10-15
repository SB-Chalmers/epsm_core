"""Optional raw evidence is portable; old provenance remains readable."""
import pytest

from epsm_core import Building, ProvenanceSpec, SourceRecord


def test_evidence_is_optional_and_roundtrips_without_changing_legacy_snapshot():
    legacy = Building(preset="illustrative-reference").to_dict()
    for record in legacy["provenance"]["records"]:
        record.pop("evidence", None)
    restored = Building.from_dict(legacy)
    assert restored.to_dict() == legacy
    record = SourceRecord(field_path="geometry.parts.0.storey_elevations_m", status="inferred",
        source="gis", evidence={"levels": 3, "raw": {"height": "9 m"}})
    restored.provenance = ProvenanceSpec(records=(record,))
    assert restored.copy().provenance == restored.provenance
    restored.geometry = restored.geometry.updated(orientation_deg=25)
    assert restored.provenance.records == ()


def test_evidence_rejects_non_json_and_nonfinite_values():
    for evidence in ({"bad": object()}, {"bad": float("nan")}, {"bad": float("inf")}):
        with pytest.raises(ValueError):
            SourceRecord(field_path="geometry", status="inferred", source="gis", evidence=evidence)
