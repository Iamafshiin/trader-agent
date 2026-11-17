import argparse
import sys
from collections.abc import Sequence

from trader_agent.settings import SettingsError, load_settings


def _check_config(_: argparse.Namespace) -> int:
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(exc, file=sys.stderr)
        return 2
    for key, value in settings.summary().items():
        print(f"{key}: {value}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trader-agent",
        description="Autonomous Nobitex spot trading (paper mode)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check-config", help="validate settings and print a safe summary")
    check.set_defaults(handler=_check_config)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.handler(args)
    return result
