"""Resolve the dashboard renderer style with strict validation."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping


VALID_STYLES = ("modern", "nerd", "cinematic")


def resolve_style(
    cli_style: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    environment = os.environ if environ is None else environ
    style = cli_style if cli_style is not None else environment.get("BHOLA_STYLE", "modern")
    if style not in VALID_STYLES:
        allowed = ", ".join(VALID_STYLES)
        raise ValueError(f"invalid dashboard style {style!r}; expected one of: {allowed}")
    return style


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--style")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        print(resolve_style(args.style))
    except ValueError as error:
        print(f"Bhola Pulse: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
