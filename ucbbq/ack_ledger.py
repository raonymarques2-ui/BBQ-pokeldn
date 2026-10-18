"""Retail-shaped reliable receipts: a later packet never acknowledges a gap."""


class AckLedger:
    def __init__(self):
        self.next=1
        self.held=set()

    def observe(self,sequence,lowest_pending=1):
        if not 1<=sequence<65535 or not 1<=lowest_pending<65535:
            raise ValueError('Invalid application sequence or pending base')
        # A peer may retire an earlier receive epoch, as in the retail window.
        self.next=max(self.next,lowest_pending)
        self.held={s for s in self.held if s>=self.next}
        if sequence>=self.next:self.held.add(sequence)
        while self.next in self.held:
            self.held.remove(self.next);self.next+=1
        if len(self.held)>1024:raise RuntimeError('Reliable receive window exceeded its bound')

    def mask(self):
        from pokeldn.ldn.reliable5 import build_mask
        return build_mask(self.held,self.next)


def repair_acknowledgements(datagram,keys,our_ip,peer_ip,ledgers,live=None):
    from pokeldn.ldn import pia6,reliable5
    import os
    header,plain,footer=pia6.parse_packet(keys.session_key,our_ip,keys.network_id,datagram)
    if plain is None:return datagram
    messages=[];changed=False
    for message in pia6.parse_messages(plain):
        body=message.payload
        ledger=ledgers.get((peer_ip,message.protocol,message.port))
        if ledger is not None and message.protocol in (0x7c,0x80,0x81):
            rm=reliable5.parse(body)
            if rm['is_ack']:
                ack=reliable5.parse_ack_payload(rm['payload'])
                index=0 if message.protocol==0x7c else 1
                if len(ack['entries'])<=index:raise ValueError('Unexpected ACK entry count')
                low=rm['lowest_pending']
                # Keep upstream's conservative outbound base. In particular,
                # the initial channel table is owned by upstream, not `live`;
                # declaring that table retired early would discard its open.
                entry=ack['entries'][index]
                entry.update(ack_id=ledger.next,mask=ledger.mask(),
                             field_0x50=low if message.protocol==0x7c else ledger.next)
                payload=reliable5.build_ack_payload(ack['entries'],unknown0=ack['unknown0'])
                body=reliable5.build_header(rm['flags'],rm['sequence_id'],len(payload),
                    lowest_pending=low,stream_id=rm['stream_id'],
                    destination_bits=rm['destination_bits'],bitmap=rm['bitmap'])+payload
                changed|=body!=message.payload
        messages.append(pia6.build_message(body,message.protocol,port=message.port,
                                           message_flags=message.message_flags))
    if not changed:return datagram
    return pia6.build_packet(keys.session_key,keys.network_id,our_ip,b''.join(messages),
        dst_var=header.dst_var,src_var=header.src_var,packet_id=header.packet_id,
        nonce8=os.urandom(8),footer_ids=footer)
