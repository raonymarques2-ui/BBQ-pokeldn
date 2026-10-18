"""Observed handler 0x48 BBQ messages; unknown fields retain neutral names.

Only the tags observed in local captures are accepted. No console identity,
save data, rewards, or quest completion logic is contained here.
"""
import math
import struct
from dataclasses import dataclass
from ucbbq.bbq_catalog import Catalog


class WireError(ValueError):
    pass


# Observed one-client Ditto snapshot extension: preserve the two small opaque
# records instead of interpreting raw 0xff bytes as tagged scalar values.
DITTO_SNAPSHOT_TAIL=bytes.fromhex('b90100ff00b90100ff00')


@dataclass(frozen=True)
class Signed16:
    value: int


class Reader:
    def __init__(self, raw):
        if len(raw) > 4096:
            raise WireError('Message exceeds the experimental size limit')
        self.raw = raw
        self.pos = 0

    def take(self, count):
        if self.pos + count > len(self.raw):
            raise WireError('Truncated message')
        result = self.raw[self.pos:self.pos + count]
        self.pos += count
        return result

    def value(self, depth=0):
        if depth > 4:
            raise WireError('Tuple nesting limit')
        tag = self.take(1)[0]
        if tag < 128:
            return tag
        if 0x80 <= tag <= 0x83:
            return int.from_bytes(self.take(1 << (tag - 0x80)), 'little')
        if tag == 0x88:
            value = struct.unpack('<f', self.take(4))[0]
            if not math.isfinite(value):
                raise WireError('Non-finite progress')
            return value
        if tag == 0x85:
            return Signed16(int.from_bytes(self.take(2),'little',signed=True))
        if tag in (0xb9, 0xbc):
            count = self.value(depth + 1)
            if type(count) is not int or count > 64:
                raise WireError('Invalid collection length')
            if tag == 0xbc:
                return self.take(count)
            return tuple(self.value(depth + 1) for _ in range(count))
        raise WireError(f'Unsupported tag {tag:#x}')


def encode_value(value):
    if isinstance(value,Signed16) and -32768<=value.value<=32767:
        return b'\x85'+value.value.to_bytes(2,'little',signed=True)
    if type(value) is int and 0 <= value < 2**64:
        if value < 128:
            return bytes([value])
        for tag, width in ((0x80, 1), (0x81, 2), (0x82, 4), (0x83, 8)):
            if value < 1 << (width * 8):
                return bytes([tag]) + value.to_bytes(width, 'little')
    if type(value) is float and math.isfinite(value):
        return b'\x88' + struct.pack('<f', value)
    if type(value) is bytes and len(value) <= 64:
        return b'\xbc' + encode_value(len(value)) + value
    if type(value) is tuple and len(value) <= 64:
        return b'\xb9' + encode_value(len(value)) + b''.join(map(encode_value, value))
    raise WireError('Unsupported value')


def validate_state(state):
    if type(state) is not tuple or len(state) != 11:
        raise WireError('Expected an eleven-field BBQ state')
    for index in (1, 2, 3, 5, 6):
        quest = state[index]
        if type(quest) is not tuple or len(quest) != 4:
            raise WireError('Expected a four-field quest')
        kind, progress, condition, variation = quest
        if any(type(v) is not int or not 0 <= v <= 65535 for v in (kind, condition, variation)):
            raise WireError('Invalid quest identifiers')
        if type(progress) is not float or not math.isfinite(progress) or progress < 0:
            raise WireError('Invalid quest progress')
    if state[4] != b'\x01':
        raise WireError('Unrecognized state flag')
    for index in (0, 7, 8, 9, 10):
        if type(state[index]) is not int or not 0 <= state[index] < 2**32:
            raise WireError('Invalid state integer')
    return state


@dataclass(frozen=True)
class BBQMessage:
    opcode: int
    revision: int
    state: tuple | None
    quest_type: int | None = None
    selector: bytes = b'\xff\xff'
    amount: float | None = None
    completion: tuple | None = None
    tail: tuple = ()
    raw_tail: bytes = b''

    def encode(self):
        if self.opcode!=5:validate_state(self.state)
        if self.raw_tail and not (self.opcode==1 and self.state[6][0]==15
                                  and self.raw_tail==DITTO_SNAPSHOT_TAIL):
            raise WireError('Unsupported opaque snapshot extension')
        if type(self.revision) is not int or not 0 <= self.revision < 2**32:
            raise WireError('Invalid revision')
        prefix = b'\x48\x00' + bytes([self.opcode])
        if self.opcode == 2:
            if type(self.quest_type) is not int or not 0 <= self.quest_type <= 65535:
                raise WireError('Invalid event quest type')
            if self.selector != b'\xff\xff' or type(self.amount) is not float or not math.isfinite(self.amount) or self.amount < 0:
                raise WireError('Unsupported event')
            prefix += encode_value(self.quest_type) + self.selector + encode_value(self.amount)
        elif self.opcode in (3,5):
            if type(self.completion) is not tuple or len(self.completion)!=18:
                raise WireError('Expected an eighteen-field completion record')
            prefix += encode_value(self.completion)
        elif self.opcode != 1:
            raise WireError('Unsupported opcode')
        revision_wire=Signed16(self.revision) if 128<=self.revision<=32767 else self.revision
        result=prefix+encode_value(revision_wire)
        if self.opcode!=5:result+=encode_value(self.state)
        return result+b''.join(encode_value(value) for value in self.tail)+self.raw_tail


def decode(raw):
    reader = Reader(raw)
    if reader.take(2) != b'\x48\x00':
        raise WireError('Wrong handler')
    opcode = reader.take(1)[0]
    kind = amount = None
    completion = None
    selector = b'\xff\xff'
    if opcode == 2:
        kind = reader.value()
        selector = reader.take(2)
        amount = reader.value()
    elif opcode in (3,5):
        completion = reader.value()
    elif opcode != 1:
        raise WireError('Unsupported opcode')
    revision = reader.value()
    if isinstance(revision,Signed16):revision=revision.value
    state = reader.value() if opcode!=5 else None
    tail=[]
    raw_tail=b''
    if opcode==1 and state[6][0]==15:
        raw_tail=reader.take(len(raw)-reader.pos)
    if opcode==3 or (opcode==1 and state[6][0]==14):
        while reader.pos<len(raw):
            if len(tail)>=16:raise WireError('Too many completion extension fields')
            tail.append(reader.value())
    if reader.pos != len(raw):raise WireError('Trailing bytes')
    message = BBQMessage(opcode, revision, state, kind, selector, amount,completion,tuple(tail),raw_tail)
    message.encode()  # Validate typed fields as well as the tagged envelope.
    return message


def initial_state():
    """Three catalogued blue quests, no active bonus/group quest or history."""
    empty = (0, 0.0, 0, 0)
    return (1, (11, 0.0, 0, 2), (2, 0.0, 0, 2), (9, 0.0, 0, 0),
            b'\x01', empty, empty, 0, 0, 0, 0)


def surprise_completion(host_station,revision,state):
    """One observed blue completion, using live station identity and neutral history.

    The remaining constants mirror the controlled type-9 -> type-22 reference.
    This is deliberately not a general quest completion/replacement algorithm.
    """
    validate_state(state)
    if (type(host_station) is not int or not 0<=host_station<2**64
            or state[3]!=(9,0.0,0,0) or state[5][0] or state[6][0]
            or state[7]!=0 or state[9]!=0):
        raise WireError('Only the initial generated surprise quest is supported')
    replacement=(22,0.0,0,1)
    updated=list(state);updated[3]=replacement;updated[7]=1;updated[9]=1
    # MissionInfo tuple order is the local game's MissionInfosArray schema:
    # category,type,variation,goal,reward,reload,release,grade,difficulty,weight.
    catalog=Catalog()
    old_info=catalog.lookup(0,state[3]).descriptor()
    new_info=catalog.lookup(0,replacement).descriptor()
    empty_info=(0,0,0,Signed16(32767),0,0,0,0,0,0.0)
    details=(9,0,0,1,0,20,(host_station,),old_info,0,0,(0,),2,
             replacement,new_info,empty_info,0,empty_info,0)
    return BBQMessage(3,revision,tuple(updated),completion=details)
