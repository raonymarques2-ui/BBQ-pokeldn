"""Adapter to the installed PokeLDN runtime, not a separate Python environment."""
from pathlib import Path
from types import SimpleNamespace
import os
from ucbbq.i18n import configure, tr
from ucbbq.platform_runtime import RunControl, StatusOutput, preserve_protocol_globals, mobile_host_module, drain_departures

GROUP_CODE = '4970'


def check_runtime():
    import pokeldn
    from pokeldn.app.paths import ROOT
    root = Path(ROOT)
    from ucbbq.compatibility import check
    check(root)
    print(f'[uc] PokeLDN {pokeldn.__version__}: adapter API and wire preflight passed.',flush=True)
    return root


def run(options):
    configure(select_runtime=True)
    # Never replace the board/port chosen by PokeLDN with an auto-selected port.
    root = check_runtime()
    if not os.environ.get('POKELDN_RADIO'):
        raise RuntimeError('Select the ESP32 in PokeLDN before starting this tool')
    if not Path(options.keys).is_file():
        raise RuntimeError('Configure your local keys file in PokeLDN Settings')
    from pokeldn.plugins import data_folder
    from ucbbq import backend
    data = data_folder('union-circle-bbq')
    data.mkdir(parents=True, exist_ok=True)
    control=RunControl()
    stopped=control.stopped
    output=StatusOutput(text_only=control.in_process)
    last = {}
    rendered = None

    def status(value):
        nonlocal rendered
        last.update(value)
        if value.get('error') or value.get('uncertain'):
            phase = tr('phase.error', 'Uncertain result; closing', 'Resultado incerto; encerrando')
        elif value.get('computed_bp', 0) >= options.bp_target:
            phase = tr('phase.target', 'Target reached; disbanding', 'Meta atingida; desfazendo grupo')
        elif stopped.is_set():
            phase = tr('phase.stopping', 'Disbanding group', 'Encerrando grupo')
        else:
            labels = {'waiting': tr('phase.waiting', 'Waiting for Switch', 'Aguardando Switch'),
                      'loading': tr('phase.loading', 'Loading world', 'Carregando mapa'),
                      'running': tr('phase.running', 'Completing quests', 'Concluindo missões'),
                      'ready': tr('phase.ready', 'Ready', 'Pronto')}
            phase = labels.get(value.get('phase'), value.get('phase', 'waiting'))
        lines=(tr('label.status', 'Status', 'Estado')+'\t'+phase,
               tr('label.code', 'Local code', 'Código local')+'\t'+GROUP_CODE,
               tr('label.earned', 'Computed BP earned', 'BP calculados')+'\t'+str(value.get('computed_bp', 0)),
               tr('label.target', 'BP target', 'Meta de BP')+'\t'+str(options.bp_target),
               tr('label.quests', 'Accounted quests', 'Missões contabilizadas')+'\t'+str(value.get('accounted_quests', 0)),
               tr('label.sandwich', 'Gold sandwich', 'Sandwich dourado')+'\t'+tr('value.skipped', 'Always skipped', 'Ignorado'))
        tone='error' if value.get('uncertain') or value.get('error') else 'info'
        if rendered != (lines,tone):
            output.show(tr('name', 'Union Circle BBQ Host', 'Host de BBQs do Union Circle'),lines=lines,tone=tone)
            rendered=(lines,tone)

    options_host = SimpleNamespace(
        generic_world=True, loader_reference=None, private_differential=None,
        allow_experimental_generic=False, code=GROUP_CODE, keys=Path(options.keys),
        presence=True, start_group=False, bbq_sync=True, bbq_auto_limit=0,
        bp_target=options.bp_target, bbq_auto_interval=options.interval, ui_managed=True,
        seconds=604800, runs=data/'private-runs', native_auto_start=True,
        status_callback=status, stop_requested=stopped.is_set,
        in_process_runtime=control.in_process,
        host_module_loader=mobile_host_module if os.environ.get('POKELDN_PLATFORM')=='android' else None,
        shutdown_drain=drain_departures,
    )
    # The adapter does not call the laboratory bootstrap, which overwrites radio settings.
    with control,preserve_protocol_globals():
        status({'phase': 'waiting'})
        result = backend.host(options_host, root)
        failed = bool(last.get('uncertain') or last.get('error'))
        reached = last.get('computed_bp', 0) >= options.bp_target
        text = tr('phase.finished', 'Target reached; connection closed', 'Meta atingida; conexão encerrada') if reached else tr('phase.ended', 'Run ended', 'Rodada encerrada')
        output.show(tr('name', 'Union Circle BBQ Host', 'Host de BBQs do Union Circle'), lines=(text,
            tr('label.earned', 'Computed BP earned', 'BP calculados')+f": {last.get('computed_bp', 0)} / {options.bp_target}"),
            tone='error' if failed else 'ok' if reached else 'warning')
        return 2 if failed else result
