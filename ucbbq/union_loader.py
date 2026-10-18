"""Experimental Union Circle loader, driven by peer messages rather than timers.

This pure state machine does not open a radio. A transport must provide reliable
delivery, handler registration, participant seating and subsequent world setup.
Reaching peer_loaded here does NOT establish a functioning shared overworld.
Reference payload profiles are private research inputs, not distribution assets.
"""
from dataclasses import dataclass
import struct

HEADER = struct.Struct('<HBBHII4s')
KEY = 0x132
REQUIRED_KINDS = (0x64, 0x65, 0x67, 0x6f, 0x68, 0x66, 0x6a, 0x73)


@dataclass(frozen=True)
class LoaderMessage:
    kind: int
    encoding: int
    declared_size: int
    body: bytes

    @classmethod
    def parse(cls, raw):
        if len(raw) < HEADER.size:
            raise ValueError('Incomplete loader header')
        key, kind, step, counter, encoding, size, _ = HEADER.unpack_from(raw)
        if key != KEY or step != 0 or kind not in REQUIRED_KINDS:
            raise ValueError('Not a supported Union Circle loader message')
        body = bytes(raw[HEADER.size:])
        if encoding not in (0, 2) or size > 65536:
            raise ValueError('Unsupported loader encoding or size')
        if encoding == 0 and size != len(body):
            raise ValueError('Loader body length mismatch')
        return cls(kind, encoding, size, body)

    def serialize(self, counter):
        return HEADER.pack(KEY, self.kind, 0, counter, self.encoding,
                           self.declared_size, bytes(4)) + self.body


def validate_profile(profile):
    messages = {kind: LoaderMessage.parse(profile[kind]) for kind in REQUIRED_KINDS}
    if any(kind != message.kind for kind, message in messages.items()):
        raise ValueError('Loader profile kind mismatch')
    for kind, size in ((0x64,24),(0x65,32),(0x67,24),(0x66,8),(0x73,8)):
        if messages[kind].encoding != 0 or len(messages[kind].body) != size:
            raise ValueError(f'Unexpected loader payload dimensions for kind {kind:#x}')
    block = messages[0x6f]
    if block.encoding != 0 or block.body != bytes(5916):
        raise ValueError('Expected the observed empty 5,916-byte loader block')
    if messages[0x68].declared_size != 344 or messages[0x6a].declared_size != 1800:
        raise ValueError('Unexpected Union Circle reference payload dimensions')
    return messages


class UnionLoader:
    """Emit the observed loader phases only after the corresponding peer reply.

    A caller must prepare the 0x48 handler exchange after peer kind 0x65 before
    forwarding kind 0x67 here. This class deliberately does not claim to implement
    that handler or the avatar/entity exchanges required after loading.
    """
    def __init__(self, profile, timeout=30.0):
        if not 5 <= timeout <= 120:
            raise ValueError('Loader timeout must be 5 to 120 seconds')
        self.messages = validate_profile(profile)
        self.timeout = timeout
        self.phase = 'idle'
        self.counter = 0
        self.deadline = None
        self.peer_loaded = False
        self.world_progress = 0

    def _emit(self, kinds, now, phase):
        result = []
        for kind in kinds:
            self.counter += 1
            result.append(self.messages[kind].serialize(self.counter))
        self.phase = phase
        self.deadline = now + self.timeout
        return result

    def begin(self, now):
        if self.phase != 'idle':
            return []
        return self._emit((0x64, 0x65), now, 'waiting_peer_65')

    def receive(self, raw, now):
        self.tick(now)
        if self.phase in ('idle', 'timed_out'):
            return []
        message = LoaderMessage.parse(raw)
        if self.phase == 'peer_loaded':
            if message.kind==0x67 and message.encoding==0 and len(message.body)==24:
                marker=struct.unpack_from('<I',message.body,16)[0]
                if marker in (1,2) and marker==self.world_progress+1:
                    # Both directions advertise these two field-loading stages
                    # after kind 0x73 in the successful reference.
                    self.world_progress=marker
                    self.counter+=1
                    return [message.serialize(self.counter)]
            return []
        if self.phase == 'waiting_peer_65' and message.kind == 0x65:
            self.phase = 'waiting_handler_setup'
            self.deadline = now + self.timeout
        elif (self.phase == 'waiting_peer_67' and message.kind == 0x67
              and message.encoding == 0 and len(message.body) == 24
              and struct.unpack_from('<I',message.body,16)[0] == 2215):
            return self._emit((0x67, 0x6f, 0x68, 0x66, 0x6a), now, 'waiting_peer_6a')
        elif self.phase == 'waiting_peer_6a' and message.kind == 0x6a:
            return self._emit((0x73,), now, 'waiting_peer_73')
        elif self.phase == 'waiting_peer_73' and message.kind == 0x73:
            self.peer_loaded = True
            self.phase = 'peer_loaded'
            self.deadline = None
        return []

    def handlers_ready(self, now):
        self.tick(now)
        if self.phase != 'waiting_handler_setup':
            return False
        self.phase = 'waiting_peer_67'
        self.deadline = now + self.timeout
        return True

    def tick(self, now):
        if self.deadline is not None and now >= self.deadline:
            self.phase = 'timed_out'
            self.deadline = None
        return self.phase


def fragment_record(raw, size=1395):
    """Return uncompressed reliable fragment bodies with START/END markers.

    The transport may compress each fragment separately, as the reference does.
    It must allocate sequence numbers and retain fragments until acknowledged.
    """
    if size <= 0 or not raw:
        raise ValueError('A record and a positive fragment size are required')
    return [(1 | (2 if offset == 0 else 0) | (4 if offset+size >= len(raw) else 0),
             raw[offset:offset+size]) for offset in range(0, len(raw), size)]
