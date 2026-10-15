"""Explicit Data inputs for regression tests of Core's physical converters."""

from epsm_data import select_dhw_profile, select_operating_profile

from epsm_core import DHWProfileSpec, SvebyNonResidentialSpec, SvebyResidentialSpec


def residential_converter():
    values = select_operating_profile('multi_family', version='2.0').to_dict()['values']
    return SvebyResidentialSpec(values)


def nonresidential_converter(category):
    return SvebyNonResidentialSpec(select_operating_profile(category).to_dict()['values'])


def dhw_converter(building_type, *, purpose, version='1'):
    values = select_dhw_profile(building_type, purpose=purpose, version=version).to_dict()['values']
    return DHWProfileSpec.model_validate({key: values[key] for key in DHWProfileSpec.model_fields})
