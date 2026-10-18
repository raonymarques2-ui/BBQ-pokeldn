import importlib.util
from pathlib import Path
import sys

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN))
spec = importlib.util.spec_from_file_location('bbq_plugin_entry', PLUGIN/'run.py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


@pytest.mark.parametrize('arguments', [
    ['--bp-target', '0'], ['--bp-target', '2.5'], ['--bp-target', '1000001'],
    ['--code', '4970'], ['--language', 'en'], ['--interval', '2'], ['--interval', 'nan'],
])
def test_invalid_inputs_are_rejected_before_runtime_import(arguments):
    with pytest.raises(SystemExit):
        entry.build_parser().parse_args(['--keys', 'local.keys', *arguments])


def test_group_code_is_fixed_and_no_separate_language_setting_exists():
    from ucbbq.native import GROUP_CODE
    options=entry.build_parser().parse_args(['--keys', 'local.keys'])
    assert GROUP_CODE == '4970'
    assert not hasattr(options, 'code') and not hasattr(options, 'language')


def test_registration_exposes_bp_goal_instead_of_mission_count():
    spec = importlib.util.spec_from_file_location('bbq_plugin_registration', PLUGIN/'plugin.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tools = []
    class API:
        def add_tool(self, game, tool):
            tools.append((game, tool))
    module.register(API())
    game, tool = tools[0]
    assert game == 'sv'
    flags = {field.flag for field in tool.fields}
    assert '--bp-target' in flags and '--code' not in flags and '--language' not in flags
    assert '--bbq-auto-limit' not in flags


def test_native_adapter_preserves_selected_radio_and_uses_generic_profile(monkeypatch, tmp_path):
    from ucbbq import native, backend
    from pokeldn import plugins
    monkeypatch.setenv('POKELDN_RADIO', 'esp32:COM99')
    monkeypatch.setattr(plugins, 'data_folder', lambda _: tmp_path/'data')
    keys = tmp_path/'local.keys'
    keys.write_text('placeholder for an offline adapter test')
    called = []
    def fake_host(options, root):
        import os
        assert os.environ['POKELDN_RADIO'] == 'esp32:COM99'
        assert options.generic_world and options.loader_reference is None
        assert options.bp_target == 25 and options.bbq_auto_limit == 0
        assert options.code == '4970'
        assert options.native_auto_start and not options.stop_requested()
        options.status_callback(dict(phase='finished', computed_bp=40, accounted_quests=2))
        called.append(root)
        return 0
    monkeypatch.setattr(backend, 'host', fake_host)
    options = entry.build_parser().parse_args(['--keys', str(keys), '--bp-target', '25'])
    assert native.run(options) == 0
    assert called


@pytest.mark.parametrize('locale,expected', [('pt-BR','Meta de BP ganhos'),('en','Target BP earned')])
def test_plugin_uses_app_language_for_registration_and_status(monkeypatch,locale,expected):
    from types import SimpleNamespace
    from pokeldn import plugins
    from pokeldn.app import settings, i18n as app_i18n
    from ucbbq import i18n
    pack=SimpleNamespace(id='test-app-language',locale=locale,error='',api=(1,8),
                         translations={},folder=PLUGIN)
    monkeypatch.setattr(i18n,'selected_language',lambda:pack.id)
    monkeypatch.setattr(plugins,'discover',lambda:[pack])
    monkeypatch.setattr(plugins,'enabled',lambda:[pack.id])
    i18n.configure(select_runtime=True)
    assert i18n.tr('field.target','Target BP earned','Meta de BP ganhos') == expected
    pack.translations={'plugins.union_circle_bbq.field.target':'Selected pack translation'}
    i18n.configure(select_runtime=True)
    assert i18n.tr('field.target','Target BP earned','Meta de BP ganhos')=='Selected pack translation'
    app_i18n.select('')
