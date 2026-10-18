"""Summarize a private decoded reference without exporting player or save data.

Reliable fragments are put in sequence order, independently of arrival order.
This is an offline diagnostic; it never opens a radio or controls a game.
"""
import argparse
import collections
import json
from pathlib import Path
import struct


def logical_records(rows, protocol=0x80, port=0):
    streams = collections.defaultdict(dict)
    for row in rows:
        rm = row.get('reliable', {})
        if row.get('protocol') != protocol or row.get('port') != port:
            continue
        if not (rm.get('flags', 0) & 1) or 'plain' not in row:
            continue
        key = (row['direction'], row.get('src_var', 0))
        streams[key].setdefault(rm['sequence'], row)
    for (direction, _), records in streams.items():
        fragments = []
        previous = None
        for sequence, row in sorted(records.items()):
            flags = row['reliable']['flags']
            if flags & 2:
                fragments = []
            elif previous is None or sequence != previous + 1:
                fragments = []
                previous = None
                continue
            fragments.append(row)
            previous = sequence
            if flags & 4:
                yield direction, fragments[0]['elapsed'], b''.join(
                    bytes.fromhex(fragment['plain']) for fragment in fragments)
                fragments = []
                previous = None


def summarize(rows):
    rows = list(rows)
    loader = []
    for direction, elapsed, data in logical_records(rows):
        if len(data) < 18 or data[:2] != b'\x32\x01':
            continue
        key, kind, step, counter, encoding, declared, _ = struct.unpack_from('<HBBHII4s', data)
        loader.append(dict(elapsed=round(elapsed, 3), direction=direction,
                           kind=f'0x{kind:02x}', step=step, counter=counter,
                           encoding=encoding, declared_bytes=declared,
                           wire_body_bytes=len(data)-18))
    loader.sort(key=lambda entry: entry['elapsed'])
    world = collections.Counter(row['direction'] for row in rows if row['protocol'] == 0x68)
    return dict(loader_messages=loader, world_datagrams=dict(world),
                shared_overworld_verified=False,
                note='Protocol activity alone does not establish a visible shared overworld.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('decoded', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = summarize(json.loads(line) for line in args.decoded.read_text().splitlines() if line.strip())
    args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
