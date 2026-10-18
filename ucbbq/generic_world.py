"""Synthetic Union Circle bootstrap candidate: no save or session input.

All payloads are built from constants or validated numeric parameters. This
single-client MVP has physical map-entry and bounded BBQ validation; it is not
a complete world implementation or a compatibility guarantee for other games.
Unmapped private player/object records are omitted; the avatar uses the public
upstream appearance preset and constructed transforms instead of a capture.
"""
import struct
import re

from ucbbq.union_loader import LoaderMessage, UnionLoader

FORMAT = 'union-circle-generic-world'
VERSION = 1
DEFAULT_SPEC = dict(format=FORMAT, version=VERSION, seed=12345678)
FIELD_KEYS = (0x29, 0x23, 0x2a, 0x1f, 0x10000001f, 0x20, 0x24, 0x25,
              0x26, 0x100000026, 0x21, 0x100000021, 0x1e, 0x10000001e)
# Public upstream record 001.bin, decompressed offsets [280:384].
# Original compressed fixture SHA256:
# 4abc162411f89a86996b50e54174df93cf4156a232296101f9724773f47ab80c
# This preset is reproduced as bounded resource indices, not read from a save.
PUBLIC_APPEARANCE_WORDS = (0, 0, 1, 193, 0, 91, 24, 99, 21, 185, 109, 23,
                           0, 10, 3, 2, 0, 0, 2, 0, 0, 0, 0, 2, 0, 0)
POSITION = (1000.0, 158.0, -975.0)
ROTATION = (0.0, 0.0, 0.0, 1.0)


def validate_spec(spec):
    if (type(spec) is not dict or set(spec) != {'format', 'version', 'seed'}
            or spec['format'] != FORMAT or type(spec['version']) is not int
            or spec['version'] != VERSION):
        raise ValueError('Unsupported generic world specification; captured payloads are not accepted')
    if type(spec['seed']) is not int or not 1 <= spec['seed'] <= 0xffffffff:
        raise ValueError('Generic seed must be an integer from 1 to 4294967295')
    return spec


def advertisement_profile(code):
    """Build a Union Circle advertisement using public PokeLDN serializers."""
    if not re.fullmatch(r'[0-9]{4}',code):raise ValueError('Use exactly four ASCII digits')
    from pokeldn import sv
    return dict(communication_id='0100a3d008c5c000',scene_id=5,protocol=1,
                app_version=21,max_participants=4,channel=11,
                application_data=sv.build_advertise_data(code=code).hex())


def marker_table(value):
    """A one-field FlatBuffer table with the observed scalar-field layout."""
    return struct.pack('<I4H3I', 12, 0, 6, 12, 4, 6, value, 0)


def environment_table(seed):
    """Build a bounded FlatBuffer with empty optional environment vectors.

    The 22-field/288-byte table layout is understood structurally. Its full game
    semantics are not established. Optional vectors are zero-filled; no world
    coordinates, save flags or original 64-bit session value are copied.
    The client must be tested to establish whether these neutral values suffice.
    """
    offsets = (4, 8, 12, 16, 280, 20, *range(24, 280, 16))
    body = bytearray(344)
    struct.pack_into('<I', body, 0, 56)
    struct.pack_into('<HH22H', body, 8, 48, 288, *offsets)
    struct.pack_into('<i', body, 56, 48)
    # The DIG region tag and two scalar defaults are protocol/game constants.
    # No claim is made that the remaining empty environment is game-equivalent.
    struct.pack_into('<I', body, 60, 0x47494400)
    struct.pack_into('<f', body, 68, 1.0)
    struct.pack_into('<f', body, 72, 20.0)
    struct.pack_into('<Q', body, 336, seed)
    return bytes(body)


def build_profile(spec):
    """Construct a profile without accessing files, radio, memory or a save."""
    validate_spec(spec)
    from pokeldn.ldn import channel_table
    from pokeldn.sv import lz4
    from ucbbq.bbq_wire import BBQMessage, initial_state

    bodies = {
        0x64: marker_table(spec['seed']),
        0x65: struct.pack('<i7I', -4, 15, 1, 0, 1, 0, 2, 1),
        0x67: marker_table(2215),
        0x6f: bytes(5916),
        0x68: environment_table(spec['seed']),
        0x66: struct.pack('<II', 0, 2),
        # 300 six-byte slots, all using the observed unused-slot sentinel.
        # No save-derived slot contents are retained.
        0x6a: (bytes([255]) * 4 + bytes(2)) * 300,
        0x73: struct.pack('<II', 1, 0),
    }
    loader = {}
    for kind, plain in bodies.items():
        compressed = kind in (0x68, 0x6a)
        loader[kind] = LoaderMessage(kind, 2 if compressed else 0, len(plain),
                                    lz4.compress(plain) if compressed else plain).serialize(0)
    profile = dict(
        loader=loader,
        handlers=[BBQMessage(1, revision, initial_state()).encode() for revision in (1, 2)],
        field_table=channel_table.build([(struct.pack('<Q', key), True) for key in FIELD_KEYS]),
        post=sorted(field_control_messages() + actor_messages(spec['seed']), key=lambda row:row[0]),
        world=presence_messages(),
        synthetic=True,
        world_after_objects=True,
        requires_peer_field_handlers=True,
        validation='physical-default-seed-mvp' if spec==DEFAULT_SPEC else 'untested-parameter-variant',
    )
    UnionLoader(profile['loader'])
    return profile


def field_control_messages():
    """Neutral field slot registration and loading barriers.

    Slot/component role numbers are game protocol constants, not player IDs.
    Avatar/model creation is constructed separately; full game-level semantics
    still require physical validation.
    """
    result=[(0.0, 0x80, struct.pack('<HBB', 0x24, 1, 1))]
    for slot, role in ((0, 0), (4, 1), (8, 3), (12, 10)):
        result.append((0.05, 0x7c, struct.pack('<HHH', 0x1f, slot, role)))
    for index, state in enumerate((13, 5, 9)):
        result.append((0.10 + index * 0.05, 0x7c, struct.pack('<HHH', 0x1e, 0, state)))
    # Key 0x25 opcode 3 is the initial counted shared-state snapshot. The
    # recorded host supplied entries here; an empty counted set needs no
    # save-derived object hashes and still announces initialization explicitly.
    result.append((0.35, 0x7c, struct.pack('<HBB', 0x25, 3, 0)))
    result.append((0.60, 0x7c, struct.pack('<HHH', 0x1e, 0, 1)))
    result.append((0.65, 0x80, struct.pack('<HB3B', 0x2a, 4, 0xb9, 1, 1)))
    for slot, enabled in ((0, 1), (4, 0)):
        result.append((0.65, 0x80, struct.pack('<HHH', 0x1e, 11, slot)))
        result.append((0.65, 0x80, struct.pack('<HHHB', 0x1e, 10, slot, enabled)))
    return result


def actor_messages(seed):
    """Construct an avatar from the public preset and a fixed companion model.

    The generic transform is shared with presence; no captured coordinates or
    per-player records enter these objects. The remaining actor trailer is
    experimental: its variable scalar is replaced with the configured seed.
    Compatibility still needs a physical test.
    """
    flat = bytearray(120)
    struct.pack_into('<I', flat, 0, 12)
    struct.pack_into('<HHH', flat, 6, 6, 108, 4)
    struct.pack_into('<i', flat, 12, 6)
    struct.pack_into('<26I', flat, 16, *PUBLIC_APPEARANCE_WORDS)
    blob = struct.pack('<I', len(flat)) + flat
    avatar = (struct.pack('<HHH', 0x1e, 1, 0)
              + actor_transform(0x301, 8, 0)
              + bytes([len(blob)]) + blob
              + struct.pack('<II3BQ', 0, seed, 0, 0, 0, 8))
    # Fixed scalar from the downloaded Eden test host's companion descriptor.
    # Its complete field meaning is not mapped. No physical-client record is
    # used; retaining non-personal test-save scene values was explicitly allowed.
    companion = struct.pack('<HHH', 0x1e, 2, 4) + actor_transform(0, 0x76662d58, 20)
    # The type-3 auxiliary slot uses a five-field FlatBuffer with two empty
    # vectors. No opaque hash or identifier from the recorded slot is kept.
    auxiliary_flat = bytearray(84)
    struct.pack_into('<I', auxiliary_flat, 0, 20)
    struct.pack_into('<7H', auxiliary_flat, 6, 14, 12, 0, 0, 0, 4, 8)
    struct.pack_into('<iII', auxiliary_flat, 20, 14, 8, 8)
    auxiliary_blob = struct.pack('<I', len(auxiliary_flat)) + auxiliary_flat
    auxiliary = (struct.pack('<HHH', 0x1e, 3, 8)
                 + actor_transform(0, 8, 0, position=(0.0, 0.0, 0.0))
                 + bytes([len(auxiliary_blob)]) + auxiliary_blob
                 + bytes(36) + struct.pack('<II3BQ', 0, seed % 0xffffffff + 1, 0, 0, 0, 8))
    animation = (struct.pack('<HHHI3B', 0x1e, 5, 0, 3, 4, 0x52, 1)
                 + b'Top/pc_field/move/defaultwait01\0')
    return [(0.02, 0x80, animation), (0.30, 0x7c, companion),
            (0.38, 0x7c, bytes(auxiliary)), (0.40, 0x7c, bytes(avatar)),
            (0.55, 0x80, animation)]


def actor_transform(flags, resource, role, *, position=POSITION):
    return struct.pack('<IIII3ff4f3fI', flags, 0, resource, role,
                       1.0, 1.0, 1.0, 0.0, *ROTATION, *position, 0)


def presence_messages():
    result = [struct.pack('<HHH7fI', 0x11e, 4, 0, *ROTATION, *POSITION, 0)]
    for slot in (0, 4):
        result.append(struct.pack('<HHH7f', 0x11e, 6, slot, 0, 0, .5, .5, 0, .5, .5))
    for slot in (0, 4):
        result.append(struct.pack('<HHHf', 0x11e, 7, slot, 1.0))
    return result
