"""Small, identity-free status record consumed by the desktop panel."""
import json
from pathlib import Path


def live_status(live,armed=False,paused=False,cancelled=False):
    ready=live.loader.world_progress==2 and live.bbq_world_announced
    if live.bbq_auto_failed:phase='error'
    elif live.bbq_auto_done:phase='finished'
    elif cancelled:phase='cancelled'
    elif not ready:phase='loading'
    elif not armed:phase='ready'
    elif paused:phase='paused'
    else:phase='running'
    if live.loader.phase=='timed_out':phase='error'
    return dict(phase=phase,connected=True,ready=ready,
                completed=sum(live.bbq_counts.values()),
                blue=live.bbq_counts[0],red=live.bbq_counts[1],gold=live.bbq_counts[2],
                expected_bp=live.bbq_expected_bp,limit=live.bbq_auto_limit,
                error=getattr(live,'bbq_last_error',''),
                pending=len(live.window.pending),group_type=live.bbq_state[6][0])


def publish(path,status):
    path=Path(path);pending=path.with_suffix('.pending')
    pending.write_text(json.dumps(status,ensure_ascii=False),encoding='utf-8')
    try:pending.replace(path)
    except PermissionError:pass  # A Windows reader can briefly hold the destination.
