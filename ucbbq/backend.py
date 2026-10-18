"""Union Circle connection experiments using an unmodified PokeLDN checkout.

This is a discovery/handshake probe, not a finished Union Circle host. No quest
completion, memory access, movement packets, trades, or raid starts are enabled.
"""
from pathlib import Path
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import sys
import time

COMM_ID = 0x0100A3D008C5C000
SCENE = 5
APP_VERSION = 21
ROOT = Path(__file__).resolve().parent
DEFAULT_REPO = None  # Supplied by the installed runtime adapter.


def validate_profile(profile):
    """Never advertise a captured trade or raid profile as a Union Circle."""
    if int(profile['communication_id'], 16) != COMM_ID or profile['scene_id'] != SCENE:
        raise ValueError('The profile is not a Scarlet/Violet Union Circle')
    if profile['protocol'] != 1 or profile['app_version'] != APP_VERSION:
        raise ValueError('Unexpected LDN protocol or application version')
    if profile['max_participants'] != 4:
        raise ValueError('A Union Circle profile must advertise four slots')
    app = bytes.fromhex(profile['application_data'])
    if len(app) != 132:
        raise ValueError('Expected 132 bytes of application data')
    return app


def game_data_for_code(profile, code):
    if not re.fullmatch(r'[0-9]{4}', code):
        raise ValueError('Use exactly four digits for the offline Union Circle code')
    app = validate_profile(profile)
    game = bytearray(app[0x5c:])
    game[:16] = code.encode('ascii').ljust(16, b'\0')
    game[0x24:0x28] = (4).to_bytes(4, 'little')
    return bytes(game)


def host_arguments(profile, code, keys, seconds, capture, presence=False):
    """Only common connection behavior; no game application payload is scheduled."""
    game = game_data_for_code(profile, code)
    if not 10 <= seconds <= 604800:
        raise ValueError('Session duration must be between 10 seconds and seven days')
    args = [
        '--keys', str(keys), '--seconds', str(seconds), '--capture', str(capture),
        '--comm-id', hex(COMM_ID), '--scene-id', str(SCENE),
        '--app-version', str(APP_VERSION), '--max-participants', '4',
        '--channel', str(profile['channel']), '--code', code,
        '--game-data', game.hex(), '--player-name', 'UC-LAB',
        '--host-player-name', 'UC-LAB',
        '--host-player-id', '00000000000000010000000000000000',
        '--scarlet-response', '--session-flags', '0', '--session-packet-id', '0',
        '--no-session-ack', '--join-seq', '0', '--update-seq', '1', '--no-identity',
        '--update-first-seq', '0', '--update-delay', '2.0',
        '--net-stations', '4', '--rtt-probe', '--clock',
    ]
    if presence:
        args.remove('--no-identity')
        args += ['--trainer-name','UC-LAB','--announce','--announce-delay','3']
    return args


def presence_opening_specs():
    """Shared stream opening observed from a real Union Circle host, not movement."""
    from pokeldn.ldn import channel_table
    from pokeldn.sv import streams
    import struct
    table=channel_table.build([(struct.pack('<II',key&255,key>>8),True)
                               for key in (0x7b,0x132,0x232,0x332)])
    return [f'0.05:0x81:5:{streams.open_payload(5).hex()}',
            f'0.06:0x81:1:{streams.open_payload(1).hex()}',
            f'0.07:0x7c:1:{streams.compress(table).hex()}:z']


def initial_stream_ack_messages():
    """A host initializes all eleven reliable streams, including idle ones."""
    from pokeldn.sv import streams
    from pokeldn.ldn import pia6
    return b''.join(pia6.build_message(
        streams.build_ack({},1,0,unknown0=1,to=1),protocol,port=port,
        message_flags=streams.MESSAGE_FLAGS_ACK)
        for protocol,port in streams.every_stream())


class IdentityGate:
    """Do not send a transfer before admission and the peer's receive is posted."""
    def __init__(self):
        self.admitted=False
        self.receive_posted=False
        self.pending={}
        self.peer_chunks=set()
        self.peer_bytes=0
        self.game_pending={}

    @property
    def ready(self):return self.admitted and self.receive_posted

    def offer(self, sequence, payload):
        if self.ready:return True
        if sequence not in self.pending:
            if len(self.pending)>=128:raise RuntimeError('Identity startup queue exceeded its bound')
            self.pending[sequence]=payload
        return False

    def release(self):
        if not self.ready:return []
        packets=list(self.pending.values())
        self.pending.clear()
        return packets

    @property
    def peer_identity_complete(self):return self.peer_bytes==0xf388

    def receive_identity(self,sequence,record):
        if len(record)<11 or record[0] not in (1,2) or record[1]!=0:return
        size=int.from_bytes(record[7:11],'big')
        if size!=len(record)-11 or not 0<size<=1384:return
        if sequence not in self.peer_chunks:
            if self.peer_bytes+size>0xf388:raise ValueError('Peer identity exceeds its advertised capacity')
            self.peer_chunks.add(sequence)
            self.peer_bytes+=size

    def offer_game(self,key,payload):
        if self.peer_identity_complete:return True
        if key not in self.game_pending:
            if len(self.game_pending)>=64:raise RuntimeError('Game startup queue exceeded its bound')
            self.game_pending[key]=payload
        return False

    def release_game(self):
        if not self.peer_identity_complete:return []
        result=list(self.game_pending.values())
        self.game_pending.clear()
        return result


def complete_reference_records(source, destination):
    """Supply all 62,344 bytes advertised by the StreamData identity transfer.

    Upstream's public reference omits chunks 5 and 6. Fill missing image-area
    chunks with zeros; never borrow the user's live identity or save content.
    """
    from pokeldn.sv import streams
    source,destination=Path(source),Path(destination)
    destination.mkdir(parents=True,exist_ok=False)
    total,chunk=0xf388,1384
    filled=[]
    for index in range(1,47):
        size=min(chunk,total-(index-1)*chunk)
        path=source/f'{index:03d}.bin'
        if path.exists():raw=bytearray(streams.decompress(path.read_bytes()))
        else:
            filled.append(index)
            raw=bytearray(bytes([1 if index==1 else 2,0,min(100,index*chunk*100//total)])
                          +bytes(4)+size.to_bytes(4,'big')+bytes(size))
        if len(raw)!=11+size or int.from_bytes(raw[7:11],'big')!=size:
            raise ValueError(f'Unexpected reference identity chunk {index}')
        if index==1:
            raw[0x0b:0x0f]=(12345).to_bytes(4,'little')
            raw[0x2d:0x43]=b'u-'+b'0'*20
        (destination/f'{index:03d}.bin').write_bytes(streams.compress(raw))
    (destination/'order').write_text('\n'.join(str(i) for i in range(1,47))+'\n')
    return filled


def group_start_messages():
    """Observed game-loader messages emitted by a real host on Set out together.

    These are bounded connection experiments. The meanings of the loader's
    scalar parameters are not yet established; no success is inferred here.
    No player/console ID or save record is copied into these templates.
    """
    import struct
    bodies=[(0x64,'0c000000000006000c000400060000004e61bc0000000000'),
            (0x65,'fcffffff0f000000010000000000000001000000000000000200000001000000'),
            (0x67,'0c000000000006000c00040006000000a708000000000000')]
    return [struct.pack('<HBBHII4s',0x132,kind,0,counter,0,len(bytes.fromhex(body)),bytes(4))
            +bytes.fromhex(body) for counter,(kind,body) in enumerate(bodies,1)]


def group_start_specs():
    from pokeldn.sv import streams
    from pokeldn.ldn import channel_table
    import struct
    messages=group_start_messages()
    result=[f'{delay}:0x80:0:{streams.compress(message).hex()}:z'
            for delay,message in zip((2.5,2.6,4.5),messages)]
    table=channel_table.build([(struct.pack('<II',key&255,key>>8),True)
                              for key in (0x7b,0x132,0x232,0x332,0x48)])
    result.append(f'2.65:0x7c:1:{streams.compress(table).hex()}:z')
    return result


def preserve_join_players(pia):
    """Keep each admitted console's own player record in the station list.

    The upstream trade probe replaces it with a placeholder; a real Union Circle
    host preserves it. Do not fabricate another identity for the client.
    """
    parse_join=pia.parse_session_join_v11
    build_update=pia.build_session_update_v11
    players={}
    def parse(raw):
        joined=parse_join(raw)
        if joined and joined.get('players'):
            players[bytes(joined['source_constant_id'])]=[dict(p) for p in joined['players']]
        return joined
    def update(host_id,host_var,stations,**kwargs):
        corrected=[]
        for station in stations:
            one=dict(station)
            if bytes(one['constant_id']) in players:
                one['players']=[dict(p) for p in players[bytes(one['constant_id'])]]
            corrected.append(one)
        return build_update(host_id,host_var,corrected,**kwargs)
    pia.parse_session_join_v11=parse
    pia.build_session_update_v11=update
    return players


def bootstrap(repo, radio):
    repo = Path(repo).resolve()
    if not (repo / 'pokeldn' / 'sv' / 'session.py').is_file():
        raise ValueError('PokeLDN source checkout not found')
    sys.path.insert(0, str(repo))
    sys.path.insert(0, str(repo / 'vendor' / 'LDN'))
    os.environ['POKELDN_RADIO'] = radio
    return repo


def scan(args):
    import trio
    from pokeldn.ldn import api as ldn
    keys = ldn.load_keys(str(args.keys))

    async def run():
        return await ldn.scan(keys, phyname='esp32', channels=[1, 6, 11], dwell_time=1.5)

    networks = trio.run(run)
    candidates = [n for n in networks if n.local_communication_id == COMM_ID and n.scene_id == SCENE]
    if len(candidates) != 1:
        raise ValueError(f'Expected one Union Circle; observed {len(candidates)}. Keep one group open.')
    n = candidates[0]
    profile = dict(communication_id=f'{n.local_communication_id:016x}', scene_id=n.scene_id,
                   protocol=n.protocol, app_version=n.app_version,
                   max_participants=n.max_participants, channel=n.channel,
                   application_data=bytes(n.application_data).hex())
    validate_profile(profile)
    args.profile.parent.mkdir(parents=True, exist_ok=True)
    args.profile.write_text(json.dumps(profile, indent=2) + '\n', encoding='utf-8')
    code = bytes(n.application_data)[0x5c:0x6c].rstrip(b'\0').decode('ascii', 'replace')
    print(f'Union Circle observed: scene={SCENE}, capacity=4, code={code}. Profile saved.')
    print('Host MAC, console name, SSID and keys are not copied to the profile.')
    return 0


def summarize(capture):
    """Report observable milestones without mistaking radio/Pia for game readiness."""
    result = dict(received_datagrams=0, decrypted_messages=0, session_join_requests=0,
                  station_list_acks=0, leave_requests=0, game_ready_verified=False,
                  stable_union_circle_verified=False)
    if not capture.exists():
        return result
    protocols = {}
    for line in capture.read_text(encoding='utf-8').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get('rec') == 'in':
            result['received_datagrams'] += 1
        if row.get('rec') == 'msg':
            result['decrypted_messages'] += 1
            protocol = row['protocol']
            protocols[f'0x{protocol:02x}'] = protocols.get(f'0x{protocol:02x}', 0) + 1
            if protocol == 0x98:
                body = bytes.fromhex(row.get('payload', ''))
                if body:
                    for kind, key in [(0, 'session_join_requests'), (6, 'station_list_acks'), (3, 'leave_requests')]:
                        if body[0] == kind:
                            result[key] += 1
    result['received_protocols'] = protocols
    return result


class Tee:
    def __init__(self, console, file):
        self.console, self.file = console, file

    def write(self, text):
        self.console.write(text)
        self.file.write(text)
        self.file.flush()

    def flush(self):
        self.console.flush()
        self.file.flush()


def host(args, repo):
    if getattr(args,'generic_world',False):
        from ucbbq.generic_world import advertisement_profile
        profile=advertisement_profile(args.code)
    else:profile = json.loads(args.profile.read_text(encoding='utf-8'))
    live_profile=None
    if getattr(args,'generic_world',False):
        from ucbbq.generic_world import build_profile, DEFAULT_SPEC
        live_profile=build_profile(dict(DEFAULT_SPEC))
    if args.loader_reference:
        from ucbbq.union_live import reference_profile
        live_profile=reference_profile(args.loader_reference,
            allow_experimental_generic=getattr(args,'allow_experimental_generic',False))
        if getattr(args,'private_differential',None):
            if args.bbq_auto_limit or live_profile.get('synthetic'):
                raise ValueError('Private differential tests require a working private reference and no automatic completions')
            from ucbbq.generic_world import build_profile, DEFAULT_SPEC
            from reference_differential import compose
            live_profile=compose(live_profile,build_profile(dict(DEFAULT_SPEC)),args.private_differential)
            print('PRIVATE DIFFERENTIAL TEST: mode='+args.private_differential+
                  '; captured baseline retained. Do not distribute diagnostics or profile.',flush=True)
        if live_profile.get('synthetic') and args.bbq_auto_limit and not getattr(args,'generic_world',False):
            raise ValueError('Synthetic world candidate cannot run automatic completions before physical validation')
    # The upstream host is used only as a common LDN/Pia connection probe.
    # No trade offers, record sets, channel announcements or application sends.
    module_loader=getattr(args,'host_module_loader',None)
    if module_loader is not None:
        module=module_loader(repo)
    else:
        spec = importlib.util.spec_from_file_location('uc_upstream_host', repo / 'bin' / 'sv_host.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    preserve_join_players(module.pia_connect)
    folder = args.runs / time.strftime('%Y%m%d-%H%M%S')
    folder.mkdir(parents=True, exist_ok=False)
    capture = folder / 'private-packets.jsonl'
    argv = host_arguments(profile, args.code, args.keys, args.seconds, capture,args.presence)
    if live_profile is not None and live_profile.get('synthetic'):
        for flag in ('--player-name','--host-player-name','--trainer-name'):
            argv[argv.index(flag)+1]='BBQ-HOST'
        print('Generated world profile: public avatar preset; no private world reference loaded.',flush=True)
    if live_profile is not None:
        # The application bootstrap owns port 2; do not let upstream allocate
        # conflicting announcement sequences on that same reliable stream.
        argv.remove('--announce')
        index=argv.index('--announce-delay');del argv[index:index+2]
    if args.presence:
        # A live console-hosted Union Circle announced kind 12, capacity 4.
        # Override the trade defaults in this process only; do not edit upstream.
        original_announce=module.port2.build_announce
        def union_announce(host_station_id,kind=12,capacity=4,zero=0,key=0):
            return original_announce(host_station_id,kind,capacity,zero,key)
        module.port2.build_announce=union_announce
        filled=complete_reference_records(repo/'pokeldn/sv/data/records',folder/'reference-identity')
        argv+=['--record-set',str(folder/'reference-identity')]
        print(f'[uc] Complete 62,344-byte reference identity; neutral chunks: {filled}',flush=True)
        for opening in presence_opening_specs():argv+=['--send-at',opening]
        if args.start_group:
            for opening in group_start_specs():argv+=['--send-at',opening]
    print(f'Experimental Union Circle handshake probe. Offline code: {args.code}', flush=True)
    print('Radio association and Pia admission do not establish in-game readiness.', flush=True)
    print(f'BBQ automatic experiment configured: limit {args.bbq_auto_limit}; waiting for bbq-auto.start.' if args.bbq_auto_limit
          else 'Generated BBQ announcements enabled; controlled completions available.' if args.bbq_sync
          else 'No BBQ or movement actions are implemented in this probe.', flush=True)
    print(f'Local diagnostics: {folder}', flush=True)
    metadata = dict(started=time.time(),stage='bbq_announcement' if args.bbq_sync else 'connection_only',code=args.code,
                    presence=args.presence,start_group=args.start_group,
                    bbq_sync=args.bbq_sync,
                    bbq_auto_limit=args.bbq_auto_limit,bbq_auto_interval=args.bbq_auto_interval,
                    reference_loader=live_profile is not None,
                    experiment_sources_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                        for name in ('union_live.py','bbq_wire.py','bbq_engine.py','bbq_catalog.py','union_loader.py','ack_ledger.py','generic_world.py')},
                    controller_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    upstream_host_sha256=hashlib.sha256((repo/'bin/sv_host.py').read_bytes()).hexdigest())
    from pokeldn.ldn import esp32, esp32_wlan
    radio = esp32_wlan.use_from_environment(log=print)
    radio_log = (folder/'private-radio.jsonl').open('w',encoding='utf-8')
    def observe(kind, payload):
        if kind in (esp32.MSG_STATUS, esp32.MSG_RESULT, esp32.MSG_STA_JOINED, esp32.MSG_STA_LEFT):
            row=dict(time=time.time(),kind=kind,payload=payload.hex())
            if kind==esp32.MSG_STATUS:row['status']=payload.decode(errors='replace')
            radio_log.write(json.dumps(row)+'\n');radio_log.flush()
    radio.subscribe(observe)
    metadata['firmware_version']=radio.info.firmware_version
    print(f'[uc] Radio firmware: {radio.info.firmware_version}',flush=True)
    original_transport=module.HostTransport
    class ObservedTransport(original_transport):
        def stop(self):
            try:
                if getattr(args,'in_process_runtime',False) and not getattr(self,'_mobile_stop_draining',False):
                    self._mobile_stop_draining=True
                    callback=getattr(args,'shutdown_drain',None)
                    if callback is not None:
                        callback(list(getattr(self,'_uc_live',{}).values()),
                            lambda:{p[1] for p in self.participants},self.recv,
                            lambda seconds:original_transport.wait_readable(self,seconds),self._live_log)
            finally:
                super().stop()

        def _live_send(self,packet,destination):
            original_transport.send(self,packet,destination)
            with (folder/'private-extra.jsonl').open('a',encoding='utf-8') as extra:
                extra.write(json.dumps(dict(time=time.time(),event='live_tx',dst=destination,
                                            hex=packet.hex()))+'\n')

        def _live_log(self,event,**fields):
            print(f'[uc] {event}: {fields}',flush=True)
            with (folder/'private-extra.jsonl').open('a',encoding='utf-8') as extra:
                extra.write(json.dumps(dict(time=time.time(),event=event,**fields))+'\n')

        def _tick_live(self):
            if live_profile is None:return
            now=time.monotonic()
            armed=(folder/'bbq-auto.start').exists() or getattr(args,'native_auto_start',False)
            paused=(folder/'bbq-auto.pause').exists()
            cancelled=(folder/'bbq-run.stop').exists()
            for ip,live in getattr(self,'_uc_live',{}).items():
                if ((folder/'start-group.request').exists() or getattr(args,'native_auto_start',False)) and self._identity_gate(ip).peer_identity_complete:
                    if not live.started:
                        from pokeldn.ldn import pia6
                        raw=bytearray(self._uc_station_lists[ip]);raw[1:3]=(2).to_bytes(2,'big')
                        live._wire(0x98,0,bytes(raw))
                        live.begin(now)
                live.bbq_auto_enabled=armed and not paused and not cancelled
                live.tick(now)
                if live.bp_goal is not None and (live.bp_goal.reached or live.bbq_auto_failed):
                    (folder/'stop.request').touch()
                    self._ui_publish_at=0
            if now>=getattr(self,'_ui_publish_at',0):
                from ucbbq.panel_state import live_status,publish
                peers=list(getattr(self,'_uc_live',{}).values())
                if peers:
                    status=live_status(peers[0],armed,paused,cancelled)
                    self._ui_last_stats={k:status[k] for k in ('completed','blue','red','gold','expected_bp')}
                else:
                    status=dict(phase='waiting',connected=False,ready=False,
                                **getattr(self,'_ui_last_stats',dict(completed=0,blue=0,red=0,gold=0,expected_bp=0)))
                status.update(updated=time.time(),expires_at=metadata['started']+args.seconds,
                              limit=args.bbq_auto_limit,code=args.code,host_running=True)
                if peers and peers[0].bp_goal is not None:
                    goal=peers[0].bp_goal
                    status.update(bp_target=goal.target,computed_bp=goal.earned,
                                  accounted_quests=goal.completed,uncertain=goal.uncertain,
                                  sandwich_ignored=peers[0].bbq_state[6][0]==5)
                callback=getattr(args,'status_callback',None)
                if callback is not None:callback(dict(status))
                publish(folder/'panel-status.json',status);self._ui_publish_at=now+.5
            request=folder/'bbq-progress.request.json'
            if args.bbq_sync and request.exists():
                processing=folder/'bbq-progress.processing.json'
                request.replace(processing)  # Claim once, before any network send.
                try:
                    if processing.stat().st_size>1024:raise ValueError('Oversized progress request')
                    command=json.loads(processing.read_text(encoding='utf-8-sig'))
                    if not isinstance(command,dict) or set(command)!={'action','expected_revision'}:
                        raise ValueError('Invalid progress request fields')
                    if command['action'] not in ('item_increment','surprise_completion','next_completion'):
                        raise ValueError('Unsupported progress action')
                    peers=list(getattr(self,'_uc_live',{}).values())
                    if len(peers)!=1:raise ValueError('Exactly one live peer is required')
                    action={'item_increment':peers[0].increment_item,
                            'surprise_completion':peers[0].complete_surprise,
                            'next_completion':peers[0].complete_next}[command['action']]
                    result=action(command['expected_revision'],now)
                    result=dict(sent=True,**result)
                except (ValueError,TypeError,OSError) as exc:
                    result=dict(sent=False,error=str(exc))
                (folder/'bbq-progress.result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
                processing.replace(folder/'bbq-progress.processed.json')
                self._live_log('bbq_progress_request_result',**result)

        def _identity_gate(self,ip):
            if not hasattr(self,'_uc_gates'):self._uc_gates={}
            return self._uc_gates.setdefault(ip,IdentityGate())

        def _initialize_streams(self, ip, peer_var):
            """The reference initializes streams after the *first* station list.

            Waiting for the second list's type-6 acknowledgement does not match
            the reference. An acknowledgement alone does not prove that an open
            sent before either station list created the game's receive state.
            """
            from pokeldn.ldn import pia6
            from pokeldn import sv
            if not hasattr(self,'_uc_opened'):self._uc_opened=set()
            if ip in self._uc_opened:return
            self._uc_opened.add(ip)
            keys=sv.session_keys(self.ssid)
            packet=pia6.build_packet(keys.session_key,keys.network_id,self.our_ip,
                initial_stream_ack_messages(),dst_var=1,src_var=module.PIA_HOST_VAR,
                packet_id=0,nonce8=os.urandom(8),footer_ids=(peer_var,))
            super().send(packet,ip)
            with (folder/'private-extra.jsonl').open('a',encoding='utf-8') as extra:
                extra.write(json.dumps(dict(time=time.time(),event='all_streams_initialized',
                                            dst=ip,hex=packet.hex()))+'\n')
            print('[uc] Initialized all eleven streams after the first station list.',flush=True)

        def send(self,datagram,dst_ip):
            from pokeldn.ldn import pia6,reliable5
            from pokeldn import sv
            # The upstream sender retains ownership of sequences/retransmits.
            # Hold only transfer-data packets, never acknowledgements or opens.
            if self.ssid and pia6.is_pia6(datagram):
                keys=sv.session_keys(self.ssid)
                from ucbbq.ack_ledger import repair_acknowledgements
                datagram=repair_acknowledgements(datagram,keys,self.our_ip,dst_ip,
                    getattr(self,'_uc_receipts',{}),getattr(self,'_uc_live',{}).get(dst_ip))
                header,plain,_=pia6.parse_packet(keys.session_key,self.our_ip,keys.network_id,datagram)
                if plain is not None:
                    for message in pia6.parse_messages(plain):
                        if message.protocol==0x98 and message.payload[:1]==b'\x05':
                            if not hasattr(self,'_uc_station_lists'):self._uc_station_lists={}
                            self._uc_station_lists[dst_ip]=message.payload
                        if message.protocol==0x98 and message.payload[:3]==b'\x05\x00\x00':
                            result=super().send(datagram,dst_ip)
                            self._initialize_streams(dst_ip,header.dst_var)
                            return result
                        if message.protocol==0x81 and message.port==0:
                            rm=reliable5.parse(message.payload)
                            if rm['flags']&reliable5.FLAG_APPLICATION_DATA and rm['flags']&reliable5.FLAG_ZLIB:
                                if not self._identity_gate(dst_ip).offer(rm['sequence_id'],bytes(datagram)):
                                    return
                                break
                        if message.protocol==0x80 and message.port in (0,2):
                            rm=reliable5.parse(message.payload)
                            if rm['flags']&reliable5.FLAG_APPLICATION_DATA:
                                key=(message.protocol,message.port,rm['sequence_id'])
                                if not self._identity_gate(dst_ip).offer_game(key,bytes(datagram)):return
                                break
            return super().send(datagram,dst_ip)

        def recv(self):
            from pokeldn.ldn import pia6,reliable5
            from pokeldn import sv
            from pokeldn.sv import streams
            packets=super().recv()
            if not hasattr(self,'_uc_opened'):self._uc_opened=set()
            keys=sv.session_keys(self.ssid)
            for payload,ip in packets:
                if not pia6.is_pia6(payload):continue
                header,plain,_=pia6.parse_packet(keys.session_key,ip,keys.network_id,payload)
                if plain is None:continue
                messages=list(pia6.parse_messages(plain))
                gate=self._identity_gate(ip)
                if any(m.protocol==0x98 and m.payload[:1]==b'\x00' for m in messages):
                    # A new join at the same IP must not inherit old transfer gates.
                    gate=IdentityGate()
                    self._uc_gates[ip]=gate
                    self._uc_opened.discard(ip)
                    self._uc_receipts={k:v for k,v in getattr(self,'_uc_receipts',{}).items() if k[0]!=ip}
                    if live_profile is not None:
                        from ucbbq.union_live import LiveUnion
                        from pokeldn.sv import port2
                        joined=next(m for m in messages if m.protocol==0x98 and m.payload[:1]==b'\x00')
                        j=module.pia_connect.parse_session_join_v11(joined.payload)
                        if not hasattr(self,'_uc_live'):self._uc_live={}
                        self._uc_live[ip]=LiveUnion(live_profile,self._live_send,
                            keys,self.our_ip,module.PIA_HOST_VAR,ip,header.src_var,
                            port2.station_id(j['destination_constant_id']),
                            port2.station_id(j['source_constant_id']),self._live_log,
                            bbq_sync=args.bbq_sync,auto_limit=args.bbq_auto_limit,
                            auto_interval=args.bbq_auto_interval,bp_target=getattr(args,'bp_target',0))
                from ucbbq.ack_ledger import AckLedger
                if not hasattr(self,'_uc_receipts'):self._uc_receipts={}
                for message in messages:
                    if message.protocol in (0x7c,0x80,0x81):
                        rm=reliable5.parse(message.payload)
                        if rm['flags']&reliable5.FLAG_APPLICATION_DATA:
                            ledger=self._uc_receipts.setdefault((ip,message.protocol,message.port),AckLedger())
                            ledger.observe(rm['sequence_id'],rm['lowest_pending'])
                if live_profile is not None:
                    live=getattr(self,'_uc_live',{}).get(ip)
                    if live:
                        for message in messages:live.receive(message,time.monotonic())
                    if any(m.protocol==0x98 and m.payload[:1]==b'\x03' for m in messages):
                        departed=getattr(self,'_uc_live',{}).pop(ip,None)
                        if departed and departed.bp_goal is not None and getattr(args,'native_auto_start',False):
                            departed.bp_goal.interrupt()
                            callback=getattr(args,'status_callback',None)
                            if callback is not None:
                                callback(dict(phase='cancelled',computed_bp=departed.bp_goal.earned,
                                    accounted_quests=departed.bp_goal.completed,
                                    uncertain=departed.bp_goal.uncertain,error='client_departed'))
                            (folder/'stop.request').touch()
                        if args.ui_managed:
                            if departed and departed.bbq_auto_count:
                                (folder/'bbq-run.stop').touch()
                            (folder/'bbq-auto.start').unlink(missing_ok=True)
                            (folder/'bbq-auto.pause').touch()
                        self._live_log('peer_departed')
                admitted=any(m.protocol==0x98 and m.payload[:1]==b'\x06' for m in messages)
                if admitted:gate.admitted=True
                for message in messages:
                    if message.protocol==0x81 and message.port==0:
                        rm=reliable5.parse(message.payload)
                        if (rm['flags']&reliable5.FLAG_IS_INITIALIZED
                            and rm['flags']&reliable5.FLAG_APPLICATION_DATA
                            and rm['payload']==bytes.fromhex('0000000000f38800000000')):
                            gate.receive_posted=True
                    if message.protocol==0x81 and message.port==1:
                        rm=reliable5.parse(message.payload)
                        if rm['flags']&reliable5.FLAG_APPLICATION_DATA and rm['flags']&reliable5.FLAG_ZLIB:
                            gate.receive_identity(rm['sequence_id'],streams.decompress(rm['payload']))
                if admitted and ip not in self._uc_opened:
                    self._initialize_streams(ip,header.src_var)
                released=gate.release()
                if released:
                    for packet in released:super().send(packet,ip)
                    print(f'[uc] Peer posted identity receive; released {len(released)} queued packet(s).',flush=True)
                    with (folder/'private-extra.jsonl').open('a',encoding='utf-8') as extra:
                        for packet in released:
                            extra.write(json.dumps(dict(time=time.time(),event='identity_gate_release',
                                                        dst=ip,hex=packet.hex()))+'\n')
                game_released=gate.release_game()
                if game_released:
                    for packet in game_released:super().send(packet,ip)
                    print(f'[uc] Complete peer identity received; released {len(game_released)} group-opening packet(s).',flush=True)
                    with (folder/'private-extra.jsonl').open('a',encoding='utf-8') as extra:
                        for packet in game_released:
                            extra.write(json.dumps(dict(time=time.time(),event='game_gate_release',
                                                        dst=ip,hex=packet.hex()))+'\n')
            self._tick_live()
            return packets
        def wait_readable(self, timeout):
            requested=getattr(args,'stop_requested',None)
            if requested is not None and requested():(folder/'stop.request').touch()
            if time.time()>=metadata['started']+args.seconds-8:
                (folder/'stop.request').touch()
            if (folder/'stop.request').exists():
                peers=list(getattr(self,'_uc_live',{}).values())
                if not peers:raise KeyboardInterrupt
                if len(peers)!=1:
                    raise RuntimeError('Normal disband is currently implemented for one client only')
                if peers[0].departure is None:self._ui_publish_at=0
                peers[0].request_disband(time.monotonic())
                if peers[0].peer_ip not in {p[1] for p in self.participants}:
                    peers[0].departure.observe_departure(time.monotonic())
                peers[0].tick(time.monotonic())
                phase=peers[0].departure.phase
                if phase!='waiting':
                    self._live_log('host_disband_transport_release',result=phase)
                    if phase=='timeout':
                        raise RuntimeError('Host departure acknowledgement timed out; normal disband unconfirmed')
                    raise KeyboardInterrupt
            if self._err:raise RuntimeError(self._err)
            self._tick_live()
            return super().wait_readable(min(timeout,0.05) if live_profile is not None else timeout)
    module.HostTransport=ObservedTransport
    exit_code = 1
    try:
        with (folder / 'private-console.log').open('w', encoding='utf-8') as log:
            with contextlib.redirect_stdout(Tee(sys.stdout, log)):
                exit_code = module.main(argv)
        return exit_code
    finally:
        radio.unsubscribe(observe)
        radio.close()
        radio_log.close()
        metadata.update(ended=time.time(),exit_code=exit_code,**summarize(capture))
        (folder / 'summary.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(metadata, indent=2), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', type=Path, default=DEFAULT_REPO)
    p.add_argument('--keys', type=Path, required=True)
    p.add_argument('--radio', default='esp32:auto')
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('scan')
    s.add_argument('--profile', type=Path, default=ROOT/'local-profile.json')
    h = sub.add_parser('host')
    h.add_argument('--profile', type=Path, default=ROOT/'local-profile.json')
    h.add_argument('--code', default='9577')
    h.add_argument('--seconds', type=float, default=180)
    h.add_argument('--presence',action='store_true',help='Exchange public reference identity and observed Union Circle presence opening')
    h.add_argument('--start-group',action='store_true',help='Experimental replay of the observed Set out together loader sequence; requires --presence')
    h.add_argument('--loader-reference',type=Path,help='Private successful decoded reference; enables the gated live loader via start-group.request')
    h.add_argument('--generic-world',action='store_true',help='Build advertisement, loader and objects in code; no save or private world reference required')
    h.add_argument('--allow-experimental-generic',action='store_true',help='Explicit opt-in to test a synthetic world candidate without captured payloads; no automatic run')
    h.add_argument('--private-differential',choices=('loader','objects','complex-objects','avatar','auxiliary','shared-state'),help='PRIVATE diagnostic: isolate generated components against a working captured reference; no automatic run')
    h.add_argument('--bbq-sync',action='store_true',help='Experimental generated blue BBQ announcements; no automatic completion')
    h.add_argument('--bbq-auto-limit',type=int,default=0,help='Bounded catalogue-driven run; requires bbq-auto.start in the run folder')
    h.add_argument('--bp-target',type=int,default=0,help='Computed BP goal for this run; mutually exclusive with quest-count limit')
    h.add_argument('--bbq-auto-interval',type=float,default=3.0,help='Minimum seconds between acknowledged automatic completions')
    h.add_argument('--ui-managed',action='store_true',help='Disarm the desktop-panel run on client departure')
    h.add_argument('--runs', type=Path, default=ROOT/'private-runs')
    args = p.parse_args()
    if args.command=='host' and (not 0<=args.bp_target<=1000000 or (args.bp_target and (args.bbq_auto_limit or not args.bbq_sync))):
        p.error('BP target must be 1 to 1000000 with --bbq-sync and without --bbq-auto-limit')
    if args.command=='host' and args.bp_target and args.bbq_auto_interval<3:
        p.error('BP target runs require an interval of at least three seconds')
    if args.command=='host' and args.generic_world and args.bbq_auto_limit and args.bbq_auto_interval<3:
        p.error('Generated-world automatic runs require an interval of at least three seconds')
    if args.command=='host' and args.generic_world and (not args.presence or args.loader_reference or args.start_group or args.allow_experimental_generic or args.private_differential):
        p.error('--generic-world requires --presence and cannot be combined with a reference or private/experimental profile option')
    if args.command=='host' and args.private_differential and (not args.loader_reference or args.allow_experimental_generic or args.bbq_auto_limit):
        p.error('--private-differential requires a private --loader-reference, no generic opt-in, and no automatic completions')
    if args.command=='host' and args.allow_experimental_generic and (not args.loader_reference or args.bbq_auto_limit):
        p.error('--allow-experimental-generic requires --loader-reference and cannot start automatic completions')
    if args.command=='host' and args.bbq_sync and not (args.loader_reference or args.generic_world):
        p.error('--bbq-sync requires --loader-reference or --generic-world')
    if args.command=='host' and (not 0<=args.bbq_auto_limit<=1000 or not 1<=args.bbq_auto_interval<=60):
        p.error('BBQ limit must be 0 to 1000 and interval 1 to 60 seconds')
    if args.command=='host' and args.bbq_auto_limit and not args.bbq_sync:
        p.error('--bbq-auto-limit requires --bbq-sync')
    if args.command=='host' and args.start_group and not args.presence:
        p.error('--start-group requires --presence')
    if args.command=='host' and args.loader_reference and (not args.presence or args.start_group):
        p.error('--loader-reference requires --presence and cannot be combined with --start-group')
    repo = bootstrap(args.repo, args.radio)
    return scan(args) if args.command == 'scan' else host(args, repo)


if __name__ == '__main__':
    raise SystemExit(main())
