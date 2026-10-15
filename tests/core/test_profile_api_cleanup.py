"""Core retains physical converters after definition selection moves to Data."""

import importlib

import pytest

import epsm_core


@pytest.mark.parametrize('module,names', [
    ('epsm_core', ('load_sveby_spec', 'load_sveby_residential_v2', 'load_sveby_office_v1',
                   'load_sveby_school_v1', 'load_dhw_profile', 'load_generic_other_v1')),
    ('epsm_core.standards', ('load_sveby_spec', 'load_sveby_residential_v2')),
    ('epsm_core.nonresidential', ('load_sveby_office_v1', 'load_sveby_school_v1')),
    ('epsm_core.dhw', ('load_dhw_profile',)),
    ('epsm_core.generic_programme', ('load_generic_other_v1',)),
])
def test_redundant_definition_selectors_are_removed(module, names):
    public = importlib.import_module(module)
    assert not any(hasattr(public, name) for name in names)


def test_advanced_physical_converters_remain_public():
    for name in ('SvebyResidentialSpec', 'SvebyNonResidentialSpec',
                 'DHWProfileSpec', 'GenericOtherProgramme'):
        assert getattr(epsm_core, name)


def test_illustrative_preset_keeps_original_physical_operation():
    import hashlib

    # Captured from pre-cleanup Core f9d785a's existing illustrative preset.
    operation = epsm_core.Building(preset='illustrative-reference').operation
    assert hashlib.sha256(operation.model_dump_json().encode()).hexdigest() == (
        'f8a1cabfcb5f2ba5c859a3b27519c3f482016c3b396615d89f3190c7897aca9a'
    )
