import threading
from types import SimpleNamespace

import pytest

from ucbbq import platform_runtime as runtime


def test_android_worker_uses_text_without_panel_or_process_signals(monkeypatch,tmp_path,capsys):
    from ucbbq import native,backend
    from pokeldn import plugins,panel
    from pokeldn.app import runner
    def forbidden(*args,**kwargs):
        raise AssertionError('Android must not use panels or signal handlers')
    monkeypatch.setenv('POKELDN_PLATFORM','android')
    monkeypatch.setenv('POKELDN_RADIO','android://board')
    monkeypatch.setattr(panel,'show',forbidden)
    monkeypatch.setattr(runtime.signal,'signal',forbidden)
    monkeypatch.setattr(runtime,'_closing_registered',False)
    hooks=[];monkeypatch.setattr(runner,'at_app_close',hooks.append)
    monkeypatch.setattr(plugins,'data_folder',lambda _:tmp_path/'data')
    keys=tmp_path/'local.keys';keys.write_text('offline placeholder')
    runs=[]
    def host(options,root):
        assert options.in_process_runtime
        assert options.host_module_loader is runtime.mobile_host_module
        assert options.code=='4970'
        hooks[0]()
        assert options.stop_requested()
        options.status_callback(dict(phase='finished',computed_bp=20,accounted_quests=1))
        runs.append(True)
        return 0
    monkeypatch.setattr(backend,'host',host)
    result=[];errors=[]
    def work():
        try:
            for _ in range(2):
                result.append(native.run(SimpleNamespace(keys=str(keys),bp_target=20,interval=3)))
        except BaseException as error:
            errors.append(error)
    thread=threading.Thread(target=work);thread.start();thread.join(5)
    assert not thread.is_alive() and not errors
    assert result==[0,0] and len(runs)==2 and len(hooks)==1
    assert runtime._stop_target is None
    output=capsys.readouterr().out
    assert '[uc-bbq]' in output and '[panel]' not in output


def test_protocol_overrides_are_restored_even_after_an_interrupt():
    from pokeldn.ldn import pia_connect
    from pokeldn.sv import port2
    original=(pia_connect.parse_session_join_v11,pia_connect.build_session_update_v11,port2.build_announce)
    with pytest.raises(KeyboardInterrupt):
        with runtime.preserve_protocol_globals():
            pia_connect.parse_session_join_v11=lambda _:None
            pia_connect.build_session_update_v11=lambda _:None
            port2.build_announce=lambda _:None
            raise KeyboardInterrupt
    assert original==(pia_connect.parse_session_join_v11,pia_connect.build_session_update_v11,port2.build_announce)


@pytest.mark.parametrize('reply',['ack','leave','silent'])
def test_interrupted_host_drain_waits_for_exit_or_reports_timeout(reply):
    from ucbbq.group_shutdown import HostDeparture
    now=[0.];events=[];sent=[];active={'peer'}
    class Live:
        peer_ip='peer'
        departure=None
        def request_disband(self,at):
            self.departure=HostDeparture(bytes(8),198,'169.254.1.1',bytes([1])*8,200,at)
        def tick(self,at):
            body=self.departure.tick(at)
            if body is not None:sent.append(body)
    live=Live()
    def receive():
        if reply=='ack':live.departure.acknowledge(live.departure.expected_ack,now[0])
        if reply=='leave':active.clear()
    runtime.drain_departures([live],lambda:active,receive,lambda seconds:now.__setitem__(0,now[0]+seconds),
        lambda event,**fields:events.append((event,fields)),clock=lambda:now[0])
    assert sent and now[0]<6.1
    assert live.departure.phase=={'ack':'acknowledged','leave':'client_left','silent':'timeout'}[reply]


def test_mobile_loader_uses_asset_importer_instead_of_file_execution(monkeypatch):
    sentinel=SimpleNamespace(main=lambda _:0)
    calls=[]
    monkeypatch.setattr(runtime.importlib,'import_module',lambda name:calls.append(name) or sentinel)
    assert runtime.mobile_host_module(None) is sentinel
    assert calls==['bin.sv_host']
