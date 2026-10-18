"""Offline API/wire preflight; version numbers are diagnostic, never a gate."""
import ast
import struct
from pathlib import Path


class CompatibilityError(RuntimeError):
    pass


def require(condition, detail):
    if not condition:
        raise CompatibilityError('Incompatible PokeLDN adapter: '+detail)


def check_host_source(source):
    tree=ast.parse(source)
    bindings=set()
    flags=set()
    for node in ast.walk(tree):
        if isinstance(node,(ast.Import,ast.ImportFrom)):
            bindings.update(a.asname or a.name.split('.')[0] for a in node.names)
        if isinstance(node,ast.Name) and isinstance(node.ctx,ast.Store):
            bindings.add(node.id)
        if isinstance(node,(ast.FunctionDef,ast.ClassDef)):
            bindings.add(node.name)
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='add_argument':
            flags.update(a.value for a in node.args if isinstance(a,ast.Constant) and isinstance(a.value,str))
    required={'main','HostTransport','pia_connect','port2','PIA_HOST_VAR'}
    require(required<=bindings,'host symbols missing: '+', '.join(sorted(required-bindings)))
    needed=set('keys seconds capture comm-id scene-id app-version max-participants channel code game-data '
               'player-name host-player-name host-player-id scarlet-response session-flags session-packet-id '
               'no-session-ack join-seq update-seq update-first-seq update-delay net-stations rtt-probe clock '
               'trainer-name record-set send-at'.split())
    missing={'--'+name for name in needed}-flags
    require(not missing,'host options missing: '+', '.join(sorted(missing)))


def check_transport_source(source):
    tree=ast.parse(source)
    cls=next((n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='HostTransport'),None)
    require(cls is not None,'HostTransport class is unavailable')
    methods={n.name for n in cls.body if isinstance(n,ast.FunctionDef)}
    expected={'send','recv','wait_readable','stop','_on_event'}
    require(expected<=methods,'HostTransport methods changed: '+', '.join(sorted(expected-methods)))
    attrs={n.attr for n in ast.walk(cls) if isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name) and n.value.id=='self'}
    expected={'participants','our_ip','ssid','_err'}
    require(expected<=attrs,'HostTransport state changed: '+', '.join(sorted(expected-attrs)))


def check_wire_contracts():
    from pokeldn import sv
    from pokeldn.ldn import pia6,pia_connect,reliable5,channel_table
    from pokeldn.sv import streams,port2
    # Fixed, non-personal fixtures. No radio, network, settings or key-file I/O.
    body=b'BBQ compatibility fixture'
    require(streams.decompress(streams.compress(body))==body,'stream compression contract changed')
    raw=reliable5.build_header(7,1,len(body),lowest_pending=1,destination_bits=3,bitmap=(2,))+body
    parsed=reliable5.parse(raw)
    require(parsed['sequence_id']==1 and parsed['payload']==body and parsed['bitmap']==[2],
            'reliable framing changed')
    window=reliable5.SendWindow(.5);window.sent((0x80,0),1,raw,0)
    require(window.lowest((0x80,0),9)==1 and bool(window.due(.6)),'reliable retry contract changed')
    window.acked((0x80,0),2)
    require(not window.pending,'reliable acknowledgement contract changed')
    receive=reliable5.ReceiveWindow()
    require(receive.take(2,'two')==[] and receive.take(1,'one')==['one','two'],
            'reliable ordering contract changed')
    ack=reliable5.parse_ack_payload(reliable5.build_ack_payload([dict(stream_id=0,ack_id=2,field_0x50=2)]))
    require(ack['entries'][0]['ack_id']==2,'bulk acknowledgement contract changed')
    table=[(struct.pack('<II',0x80,0x46),True)]
    require(channel_table.parse(channel_table.build(table))==table,'channel registration contract changed')
    host=bytes(range(8));peer=bytes(range(8,16))
    leave=pia_connect.build_session_migration_v11(host,198,'169.254.1.1',peer,200,tail=1)
    expected=b'\x07'+host+b'\0\0\0\xc6\0'+bytes((169,254,1,1))+b'09'+peer+b'\0\0\0\xc8\0\x01'
    require(leave==expected,'host-departure wire format changed')
    require(pia_connect.build_session_migration_ack_v11(peer,200,host,198)==b'\x08'+peer+b'\0\0\0\xc8'+host+b'\0\0\0\xc6',
            'host-departure acknowledgement format changed')
    require(port2.parse_join(port2.build_join()) is not None,'application-seat join format changed')
    announcement=port2.build_announce(123,kind=12,capacity=4)
    require(announcement[:1]==b'\x07','application-seat announcement format changed')
    keys=sv.session_keys(bytes(range(16)))
    packet=pia6.build_packet(keys.session_key,keys.network_id,'169.254.1.1',
        pia6.build_message(body,0x80,port=0),dst_var=1,src_var=198,packet_id=0,
        footer_ids=(200,),nonce8=bytes(8))
    header,plain,footer=pia6.parse_packet(keys.session_key,'169.254.1.1',keys.network_id,packet)
    require(plain is not None and header.src_var==198 and footer==[200]
            and list(pia6.parse_messages(plain))[0].payload==body,'Pia encryption/framing contract changed')


def check(root):
    root=Path(root)
    try:
        check_host_source((root/'bin/sv_host.py').read_text(encoding='utf-8'))
        check_transport_source((root/'pokeldn/ldn/transport.py').read_text(encoding='utf-8'))
        check_wire_contracts()
    except CompatibilityError:
        raise
    except Exception as error:
        raise CompatibilityError('PokeLDN preflight failed before opening the radio: '+str(error)) from error
