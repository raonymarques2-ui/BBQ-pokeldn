"""Desktop child and mobile in-process support; never changes app guardrails."""
from contextlib import contextmanager
import importlib
import os
import signal
import sys
import threading
import time
import weakref

_stop_target = None
_closing_registered = False


def in_process():
    return (os.environ.get('POKELDN_PLATFORM') in ('android','ios')
            or threading.current_thread() is not threading.main_thread())


def _closing():
    event = _stop_target() if _stop_target is not None else None
    if event is not None:
        event.set()


class RunControl:
    def __init__(self):
        self.stopped=threading.Event()
        self.in_process=in_process()
        self.previous=None

    def __enter__(self):
        global _stop_target,_closing_registered
        if self.in_process:
            from pokeldn.app import runner
            if not _closing_registered and callable(getattr(runner,'at_app_close',None)):
                runner.at_app_close(_closing)
                _closing_registered=True
            _stop_target=weakref.ref(self.stopped)
        else:
            self.previous=signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT,lambda *_:self.stopped.set())
        return self

    def __exit__(self,*exc):
        global _stop_target
        if self.in_process:
            _stop_target=None
        elif self.previous is not None:
            signal.signal(signal.SIGINT,self.previous)


@contextmanager
def preserve_protocol_globals():
    from pokeldn.ldn import pia_connect
    from pokeldn.sv import port2
    saved=[(pia_connect,'parse_session_join_v11',pia_connect.parse_session_join_v11),
           (pia_connect,'build_session_update_v11',pia_connect.build_session_update_v11),
           (port2,'build_announce',port2.build_announce)]
    try:
        yield
    finally:
        for module,name,value in saved:
            setattr(module,name,value)


def mobile_host_module(_root):
    # Match PokeLDN's mobile launcher: compiled assets may require its importer.
    sys.modules.pop('bin.sv_host',None)
    return importlib.import_module('bin.sv_host')


class StatusOutput:
    def __init__(self,text_only=False):
        self.text_only=text_only

    def show(self,title,lines,tone):
        if self.text_only:
            # No [panel] protocol: on Android it calls the GUI saver inside the
            # plugin stack, which triggers the app's filesystem guard.
            print('[uc-bbq] '+title+' | '+' | '.join(str(s).replace('\t',': ') for s in lines),flush=True)
        else:
            from pokeldn import panel
            panel.show('uc-bbq',title,lines=lines,tone=tone)


def drain_departures(lives,active_ips,receive,wait,log,*,clock=time.monotonic,timeout=6):
    """Bounded drain before transport close after an in-process interruption."""
    if not lives:
        return
    if len(lives)!=1:
        log('mobile_disband_unconfirmed',reason='Only one client is supported')
        return
    live=lives[0];live.request_disband(clock());deadline=clock()+timeout
    while clock()<deadline:
        if live.peer_ip not in active_ips():
            live.departure.observe_departure(clock())
        live.tick(clock())
        if live.departure.phase!='waiting':
            log('mobile_disband_transport_release',result=live.departure.phase)
            return
        receive()
        wait(.05)
    log('mobile_disband_unconfirmed',reason='Departure drain deadline expired')
