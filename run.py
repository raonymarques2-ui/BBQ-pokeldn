"""PokeLDN-native entry point. build_parser() has no hardware side effects."""
import argparse


def target_bp(value):
    try:
        number = int(value)
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError('BP target must be an integer') from None
    if not 1 <= number <= 1000000:
        raise argparse.ArgumentTypeError('BP target must be between 1 and 1000000')
    return number


def interval_seconds(value):
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError('Interval must be a number') from None
    if not 3 <= number <= 60:
        raise argparse.ArgumentTypeError('Interval must be between 3 and 60 seconds')
    return number


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keys', required=True, help='Local keys configured in PokeLDN Settings')
    parser.add_argument('--bp-target', type=target_bp, default=1000)
    parser.add_argument('--interval', type=interval_seconds, default=3)
    return parser


def main(argv=None):
    options = build_parser().parse_args(argv)
    from ucbbq.native import run
    return run(options)


if __name__ == '__main__':
    raise SystemExit(main())
