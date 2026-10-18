"""Private-reference Union Circle bootstrap experiment, one physical client.

Only application payloads are used from the reference. Pia encryption, station
IDs, packet headers, reliable sequences and acknowledgements are generated live.
This is not a general Union Circle implementation. Optional BBQ announcements
are generated separately, without copying reference quest state.
"""
import collections
import json
import os
import struct
from pathlib import Path

from ucbbq.analyze_union_session import logical_records
from ucbbq.union_loader import UnionLoader, REQUIRED_KINDS, fragment_record
from pokeldn.ldn import pia6, reliable5, channel_table
from pokeldn.sv import streams, port2
from ucbbq.bbq_wire import BBQMessage, WireError, decode as decode_bbq, initial_state, surprise_completion
from ucbbq.bbq_engine import Planner


def reference_profile(path, *, allow_experimental_generic=False):
    text = Path(path).read_text()
    # Generic profiles contain only a strict, numeric generation specification.
    # No captured payload can be passed through this format.
    try:spec=json.loads(text)
    except json.JSONDecodeError:spec=None
    if isinstance(spec,dict) and spec.get('format')=='union-circle-generic-world':
        if not allow_experimental_generic:
            raise ValueError('Generic world is experimental and not physically validated; explicit test opt-in required')
        from ucbbq.generic_world import build_profile
        return build_profile(spec)
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    records = sorted(logical_records(rows),key=lambda item:item[1])
    loader = {}
    handlers = []
    post = []
    loaded_at = None
    for direction, elapsed, data in records:
        if direction != 'out':continue
        if data[:2] == b'\x32\x01' and data[2] in REQUIRED_KINDS:
            loader.setdefault(data[2],data)
            if data[2] == 0x73 and loaded_at is None:loaded_at=elapsed
        elif data[:2] == b'\x48\x00' and len(handlers)<2:
            handlers.append(data)
    if len(handlers)!=2 or loaded_at is None:
        raise ValueError('The reference lacks a complete loader/handler opening')
    # Include the first object's setup only, ending before ambient world data.
    # Private payloads stay in this local process and are not packaged for sharing.
    for protocol in (0x7c,0x80):
        for direction,elapsed,data in logical_records(rows,protocol=protocol):
            if direction!='out' or not loaded_at<=elapsed<=loaded_at+5:continue
            if data[:2]==b'\x32\x01':continue
            post.append((elapsed-loaded_at,protocol,data))
    post.sort(key=lambda item:item[0])
    field_table=next((bytes.fromhex(r['plain']) for r in rows
        if r['direction']=='out' and r['protocol']==0x7c and r['port']==1
        and r['elapsed']>loaded_at and 'plain' in r),None)
    if field_table is None:raise ValueError('Missing field handler registration')
    channel_table.parse(field_table)
    world={}
    first_world=next((r['elapsed'] for r in rows if r['direction']=='out' and r['protocol']==0x68),None)
    if first_world is None:raise ValueError('No outbound world presence in reference')
    for row in rows:
        if row['direction']=='out' and row['protocol']==0x68 and row['elapsed']<=first_world+0.01:
            raw=bytes.fromhex(row['payload'])
            world.setdefault(raw[:6],raw)
    # Validate the loader before opening the radio.
    UnionLoader(loader)
    return dict(loader=loader,handlers=handlers,post=post,world=list(world.values()),field_table=field_table)


class LiveUnion:
    def __init__(self,profile,send,keys,our_ip,host_var,peer_ip,peer_var,host_station,peer_station,log,bbq_sync=False,auto_limit=0,auto_interval=2.0,bp_target=0):
        self.profile=profile;self.loader=UnionLoader(profile['loader'],timeout=60)
        self.send_packet=send;self.keys=keys;self.our_ip=our_ip;self.host_var=host_var
        self.peer_ip=peer_ip;self.peer_var=peer_var
        self.host_station=host_station;self.peer_station=peer_station;self.log=log
        self.next=collections.defaultdict(lambda:1);self.next[(0x7c,1)]=2
        self.window=reliable5.SendWindow(0.5)
        self.receive_windows={};self.fragments={}
        self.started=False;self.handler_steps=set();self.seated=False
        self.post_at=None;self.post_index=0;self.world_at=0;self.world_enabled=False
        self.peer_field_handlers=set();self.peer_field_ready_at=None
        self.bbq_sync=bbq_sync;self.bbq_state=initial_state();self.bbq_revision=0
        self.bbq_world_announced=False
        self.bbq_planner=Planner();self.bbq_peer_snapshots=0
        self.bbq_auto_limit=auto_limit;self.bbq_auto_interval=auto_interval
        self.bbq_auto_enabled=False;self.bbq_auto_failed=False;self.bbq_auto_done=False
        self.bbq_auto_count=0;self.bbq_auto_next=0;self.bbq_response_floor=-1
        self.bbq_response_deadline=None;self.bbq_expected_bp=0
        self.bbq_counts={0:0,1:0,2:0};self.bbq_last_error=''
        self.departure=None
        from ucbbq.bp_goal import BPGoal
        self.bp_goal=BPGoal(bp_target) if bp_target else None
        self.peer_bbq_revision=None;self.peer_bbq_state=None
        self.bp_receipt=None
        self.application_exchange_sent=False
        self.seat_announcement_at=None

    def _start_application_exchange(self,now):
        required={0x4600000080,0x4700000080}
        if (self.application_exchange_sent or self.seated or self.seat_announcement_at is None
                or now<self.seat_announcement_at+.5
                or self.loader.phase not in ('waiting_handler_setup','waiting_peer_67')
                or not required.issubset(self.peer_field_handlers)):
            return
        self.application_exchange_sent=True
        self.emit(0x80,2,port2.build_announce(self.host_station,kind=12,capacity=4),now)
        self.log('seat_announcement_repeated_after_peer_registration')

    def request_disband(self,now):
        from ucbbq.group_shutdown import HostDeparture
        if self.departure is None:
            self.bbq_auto_enabled=False
            if self.bp_goal is not None:self.bp_goal.interrupt()
            self.departure=HostDeparture(self.host_station.to_bytes(8,'big'),self.host_var,
                self.our_ip,self.peer_station.to_bytes(8,'big'),self.peer_var,now)
            self.log('host_disband_requested')

    def complete_next(self,expected_revision,now):
        if self.departure is not None:raise ValueError('Group is disbanding')
        if self.bp_goal is not None and (not self.bp_goal.can_schedule or self.peer_bbq_state is None):
            raise ValueError('BP completion receipt is pending or peer state is unavailable')
        if not self.bbq_sync or not self.bbq_world_announced or self.loader.world_progress!=2:
            raise ValueError('Generated BBQ world is not ready')
        if type(expected_revision) is not int or expected_revision!=self.bbq_revision:
            raise ValueError('Stale BBQ revision')
        messages=self.bbq_planner.next(self.bbq_state,self.host_station,self.bbq_revision+1)
        for message in messages:self.game(message.encode(),now)
        first=messages[0];self.bbq_state=first.state;self.bbq_revision=messages[-1].revision
        reward=getattr(first.completion[5],'value',first.completion[5])
        self.bbq_expected_bp+=reward
        self.bbq_counts[first.completion[4]]+=1
        self.log('host_bbq_completion_sent',revision=self.bbq_revision,
                 quest_type=first.completion[0],grade=first.completion[4],
                 expected_bp=reward,expected_bp_total=self.bbq_expected_bp,
                 group_type=self.bbq_state[6][0])
        if self.bp_goal is not None:
            token=str(self.bbq_revision)
            expected_peer=list(self.peer_bbq_state)
            expected_peer[6]=self.bbq_state[6]
            if first.completion[4]==2:expected_peer[10]+=1
            self.bp_goal.begin(token,reward)
            self.bp_receipt=(self.peer_bbq_revision+1,tuple(expected_peer))
            self.bbq_response_deadline=now+15
        return dict(revision=self.bbq_revision,expected_bp=reward)

    def announce_bbqs(self,now):
        self.bbq_revision+=1
        self.game(BBQMessage(1,self.bbq_revision,self.bbq_state).encode(),now)
        self.log('host_bbq_snapshot_sent',revision=self.bbq_revision,
                 quests=[dict(type=q[0],progress=q[1],condition=q[2],variation=q[3])
                         for q in self.bbq_state[1:4]])

    def increment_item(self,expected_revision,now):
        """One controlled non-completing event; never cross the ten-item goal."""
        if self.departure is not None:raise ValueError('Group is disbanding')
        if not self.bbq_sync or not self.bbq_world_announced or self.loader.world_progress!=2:
            raise ValueError('Generated BBQ world is not ready')
        if type(expected_revision) is not int or expected_revision!=self.bbq_revision:
            raise ValueError('Stale BBQ revision')
        quest=self.bbq_state[1]
        if quest[0]!=11 or quest[1]<0 or quest[1]>=9 or not quest[1].is_integer():
            raise ValueError('Only a non-completing item increment is supported')
        updated=list(self.bbq_state)
        updated[1]=(quest[0],quest[1]+1.0,quest[2],quest[3])
        revision=self.bbq_revision+1
        message=BBQMessage(2,revision,tuple(updated),11,amount=1.0)
        self.game(message.encode(),now)
        self.bbq_state=tuple(updated);self.bbq_revision=revision
        self.log('host_bbq_item_increment_sent',revision=revision,
                 amount=1.0,total=self.bbq_state[1][1],completion=False)
        return dict(revision=revision,total=self.bbq_state[1][1])

    def complete_surprise(self,expected_revision,now):
        if self.departure is not None:raise ValueError('Group is disbanding')
        if not self.bbq_sync or not self.bbq_world_announced or self.loader.world_progress!=2:
            raise ValueError('Generated BBQ world is not ready')
        if type(expected_revision) is not int or expected_revision!=self.bbq_revision:
            raise ValueError('Stale BBQ revision')
        message=surprise_completion(self.host_station,self.bbq_revision+1,self.bbq_state)
        self.game(message.encode(),now)
        self.bbq_state=message.state;self.bbq_revision=message.revision
        self.log('host_bbq_surprise_completion_sent',revision=self.bbq_revision,
                 old_type=9,new_type=22,expected_client_bp_increment=20)
        return dict(revision=self.bbq_revision,expected_client_bp_increment=20,new_type=22)

    def _wire(self,protocol,port,body,flags=0):
        message=pia6.build_message(body,protocol,port=port,message_flags=flags)
        mesh=protocol in (0x68,0x80,0x81)
        packet=pia6.build_packet(self.keys.session_key,self.keys.network_id,self.our_ip,message,
            dst_var=1 if mesh else self.peer_var,src_var=self.host_var,packet_id=0,
            footer_ids=(self.peer_var,) if mesh else (),nonce8=os.urandom(8))
        self.send_packet(packet,self.peer_ip)

    def emit(self,protocol,port,data,now,flags=7):
        key=(protocol,port);sequence=self.next[key];self.next[key]+=1
        if sequence==1:flags|=8
        if len(data)>300:
            data=streams.compress(data);flags|=16
        low=self.window.lowest(key,sequence)
        body=reliable5.build_header(flags,sequence,len(data),lowest_pending=low,
            destination_bits=0 if protocol==0x7c else 3,
            bitmap=() if protocol==0x7c else (2,))+data
        if len(self.window.pending)>=512:raise RuntimeError('Union bootstrap send window is full')
        self.window.sent(key,sequence,body,now)
        self._wire(protocol,port,body)

    def game(self,data,now):
        for flags,fragment in fragment_record(data):self.emit(0x80,0,fragment,now,flags)

    def begin(self,now):
        if self.started:return
        self.started=True
        for raw in self.loader.begin(now):self.game(raw,now)
        self.log('loader_started',phase=self.loader.phase)

    def receive(self,message,now):
        if message.protocol==0x98 and self.departure is not None:
            if self.departure.acknowledge(message.payload,now):
                self.log('host_disband_acknowledged')
            return
        if message.protocol not in (0x7c,0x80):return
        rm=reliable5.parse(message.payload);key=(message.protocol,message.port)
        if rm['is_ack']:
            entries=reliable5.parse_ack_payload(rm['payload'])['entries']
            if entries:self.window.acked(key,entries[0]['ack_id'],entries[0]['mask'])
            return
        window=self.receive_windows.setdefault(key,reliable5.ReceiveWindow())
        for part in window.take(rm['sequence_id'],rm):
            data=part['payload']
            if part['flags']&16:data=streams.decompress(data)
            if part['flags']&2:self.fragments[key]=[]
            if key not in self.fragments:continue
            self.fragments[key].append(data)
            if not part['flags']&4:continue
            raw=b''.join(self.fragments.pop(key))
            self._application(key,raw,now)

    def _application(self,key,raw,now):
        if key==(0x7c,1):
            try:entries=channel_table.parse(raw)
            except (ValueError,IndexError):return
            for handler,opened in entries:
                if opened:self.peer_field_handlers.add(int.from_bytes(handler,'little'))
                else:self.peer_field_handlers.discard(int.from_bytes(handler,'little'))
            required={0x1e,0x10000001e,0x1f,0x24,0x25,0x2a}
            if self.peer_field_ready_at is None and required.issubset(self.peer_field_handlers):
                self.peer_field_ready_at=now
                self.log('peer_field_handlers_ready')
            if any(k==struct.pack('<II',0x48,0) and opened for k,opened in entries):
                self.log('peer_handler_48_open')
            self._start_application_exchange(now)
            return
        if key==(0x7c,2) and port2.parse_join(raw) is not None and not self.seated:
            self.seated=True
            self.emit(0x7c,2,port2.build_join(),now)
            self.emit(0x80,2,port2.build_accept(self.host_station,code=0),now)
            self.emit(0x80,2,port2.build_accept(self.peer_station,code=1),now)
            self.log('application_seats_sent')
            return
        if key!=(0x80,0):return
        if raw[:2]==b'\x48\x00':
            if self.bbq_sync:
                try:message=decode_bbq(raw)
                except WireError as exc:
                    self.log('peer_bbq_decode_rejected',reason=str(exc));return
                self.log('peer_bbq_message',opcode=message.opcode,revision=message.revision,
                         quest_type=message.quest_type,amount=message.amount)
                if message.opcode==1:
                    self.handler_steps.add(message.revision)
                    self.bbq_peer_snapshots+=1
                    if self.bp_goal is not None and self.bp_goal.pending is not None:
                        revision,state=self.bp_receipt
                        if message.revision==revision and message.state==state:
                            self.bp_goal.record_evidence(self.bp_goal.pending.token,processed=True)
                        elif message.revision>=revision:
                            self.bp_goal.interrupt();self.bbq_auto_failed=True
                            self.bbq_last_error='unexpected_peer_state'
                            self.log('bbq_bp_uncertain',reason=self.bbq_last_error)
                    if self.peer_bbq_revision is None or message.revision>self.peer_bbq_revision:
                        self.peer_bbq_revision=message.revision;self.peer_bbq_state=message.state
                    if (self.bp_goal is not None and self.bp_goal.pending is None
                            and message.state[6][0]==5):
                        current=list(self.bbq_state);current[6]=message.state[6]
                        self.bbq_state=tuple(current)
            elif raw[:3]==b'\x48\x00\x01' and len(raw)>=4:
                self.handler_steps.add(raw[3])
            if self.handler_steps.issuperset((1,2)):
                if self.loader.handlers_ready(now):self.log('handler_48_exchange_complete')
            return
        if raw[:2]!=b'\x32\x01' or len(raw)<3 or raw[2] not in REQUIRED_KINDS:return
        before=self.loader.phase
        progress_before=self.loader.world_progress
        actions=self.loader.receive(raw,now)
        if self.loader.phase=='waiting_handler_setup' and before=='waiting_peer_65':
            table=channel_table.build([(struct.pack('<II',k&255,k>>8),True)
                                      for k in (0x4680,0x4780,0x48)])
            self.emit(0x7c,1,table,now)
            # Preserve the opening order from the physically successful host.
            # Registration can follow the first announcement; it cannot gate it.
            if self.bbq_sync:
                self.announce_bbqs(now);self.announce_bbqs(now)
            else:
                for record in self.profile['handlers']:self.game(record,now)
            self.emit(0x80,2,port2.build_announce(self.host_station,kind=12,capacity=4),now)
            self.seat_announcement_at=now
        for action in actions:self.game(action,now)
        if self.loader.phase!=before:self.log('loader_phase',phase=self.loader.phase)
        if self.loader.world_progress!=progress_before:
            self.log('world_loading_progress',marker=self.loader.world_progress)
            if self.bbq_sync and self.loader.world_progress==2 and not self.bbq_world_announced:
                self.announce_bbqs(now)
                self.bbq_world_announced=True
        if self.loader.peer_loaded and self.post_at is None:
            self.post_at=now
            self.log('peer_loaded_unverified_map')

    def tick(self,now):
        if self.departure is not None:
            body=self.departure.tick(now)
            if body is not None:self._wire(0x98,0,body)
            return
        old=self.loader.phase;self.loader.tick(now)
        if old!=self.loader.phase:self.log('loader_phase',phase=self.loader.phase)
        if self.bp_goal is not None and self.loader.phase=='timed_out':
            self.bbq_auto_failed=True;self.bbq_last_error='world_loading_timeout'
        self._start_application_exchange(now)
        for key,sequence,body in self.window.due(now):
            self._wire(*key,reliable5.set_lowest_pending(body,self.window.lowest(key,sequence)),flags=0x40)
        if self.post_at is not None:
            if not self.world_enabled:
                # The reference announces its field handlers at this milestone.
                self.emit(0x7c,1,self.profile['field_table'],now)
                self.world_enabled=True
            sent=0
            gate=self.profile.get('requires_peer_field_handlers',False)
            post_ready=not gate or self.peer_field_ready_at is not None
            post_base=max(self.post_at,self.peer_field_ready_at) if gate and post_ready else self.post_at
            while post_ready and self.post_index<len(self.profile['post']) and sent<3:
                delay,protocol,data=self.profile['post'][self.post_index]
                if now-post_base<max(0,delay):break
                for flags,fragment in fragment_record(data):self.emit(protocol,0,fragment,now,flags)
                self.post_index+=1;sent+=1
            if (now>=self.world_at and (not self.profile.get('world_after_objects',self.profile.get('synthetic'))
                                       or self.post_index==len(self.profile['post']))):
                for raw in self.profile['world']:self._wire(0x68,0,raw)
                self.world_at=now+0.1
        if self.bp_goal is not None:
            self._tick_bp_goal(now)
            return
        if (self.bbq_auto_enabled and self.bbq_auto_limit and self.bbq_world_announced
                and not self.bbq_auto_failed and not self.bbq_auto_done):
            if self.bbq_peer_snapshots<=self.bbq_response_floor:
                if self.bbq_response_deadline is not None and now>=self.bbq_response_deadline:
                    self.bbq_auto_failed=True
                    self.bbq_last_error='application_timeout'
                    self.log('bbq_auto_paused',reason='No application snapshot after completion')
                return
            if self.bbq_auto_count>=self.bbq_auto_limit:
                self.bbq_auto_done=True
                self.log('bbq_auto_finished',completed=self.bbq_auto_count,expected_bp=self.bbq_expected_bp)
            elif now>=self.bbq_auto_next and not self.window.pending:
                try:self.complete_next(self.bbq_revision,now)
                except (ValueError,WireError) as exc:
                    self.bbq_auto_failed=True;self.bbq_last_error=str(exc)
                    self.log('bbq_auto_paused',reason=str(exc));return
                self.bbq_auto_count+=1;self.bbq_response_floor=self.bbq_peer_snapshots
                self.bbq_response_deadline=now+15;self.bbq_auto_next=now+self.bbq_auto_interval

    def _tick_bp_goal(self,now):
        goal=self.bp_goal
        if goal.pending is not None and not goal.uncertain:
            if not self.window.pending:
                if goal.record_evidence(goal.pending.token,delivered=True):
                    self.log('bbq_bp_accounted',computed_bp=goal.earned,completed=goal.completed)
            if goal.pending is not None and now>=self.bbq_response_deadline:
                goal.interrupt();self.bbq_auto_failed=True
                self.bbq_last_error='completion_receipt_timeout'
                self.log('bbq_bp_uncertain',reason=self.bbq_last_error)
        if goal.reached:
            if not self.bbq_auto_done:
                self.bbq_auto_done=True
                self.log('bbq_bp_target_reached',computed_bp=goal.earned,target=goal.target)
            return
        if (self.bbq_auto_enabled and self.bbq_world_announced and goal.can_schedule
                and not self.bbq_auto_failed and now>=self.bbq_auto_next
                and self.peer_bbq_state is not None and not self.window.pending):
            try:self.complete_next(self.bbq_revision,now)
            except (ValueError,WireError) as exc:
                self.bbq_auto_failed=True;self.bbq_last_error=str(exc);return
            self.bbq_auto_count+=1
            self.bbq_auto_next=now+self.bbq_auto_interval
