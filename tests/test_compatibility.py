from pathlib import Path

import pytest

from ucbbq import compatibility, native


def test_future_version_number_does_not_block_compatible_runtime(monkeypatch):
    import pokeldn
    monkeypatch.setattr(pokeldn,'__version__','999.0.0')
    assert native.check_runtime().is_dir()


def test_missing_host_option_fails_before_opening_radio():
    from pokeldn.app.paths import ROOT
    source=(Path(ROOT)/'bin/sv_host.py').read_text()
    with pytest.raises(compatibility.CompatibilityError,match='record-set'):
        compatibility.check_host_source(source.replace('--record-set','--changed-option'))


def test_changed_reliable_payload_contract_is_detected(monkeypatch):
    from pokeldn.ldn import reliable5
    original=reliable5.parse
    def incompatible(raw):
        result=original(raw)
        result['payload']=b'changed wire contract'
        return result
    monkeypatch.setattr(reliable5,'parse',incompatible)
    with pytest.raises(compatibility.CompatibilityError,match='reliable framing'):
        compatibility.check_wire_contracts()


def test_missing_app_settings_never_creates_a_settings_file(monkeypatch,tmp_path):
    from pokeldn.app import paths
    from ucbbq import i18n
    monkeypatch.setattr(paths,'DATA',tmp_path)
    assert i18n.selected_language()==''
    assert list(tmp_path.iterdir())==[]
