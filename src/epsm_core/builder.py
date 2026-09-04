"""Convenience assembly with explicit, externally supplied assumption profiles."""

from copy import deepcopy

from .specs import BuildingSpec, ProvenanceSpec, SourceRecord


class BuildingBuilder:
    def __init__(self, *, assumption_profile: str, assumptions: dict):
        self.profile = assumption_profile
        self.assumptions = deepcopy(assumptions)

    def build(self, *, source: str = "user", **known) -> BuildingSpec:
        records = []

        def merge(defaults, overrides, prefix=""):
            result = {}
            for key in sorted(defaults.keys() | overrides.keys()):
                path = f"{prefix}.{key}".strip(".")
                assumed = key not in overrides
                value = defaults[key] if assumed else overrides[key]
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
