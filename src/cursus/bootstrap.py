"""Composition root; M0 deliberately constructs no service infrastructure."""

import argparse

from cursus import __version__


def main(argv: list[str] | None = None) -> int:
    """Offer offline package discovery without DB, credentials, or network access."""
    parser = argparse.ArgumentParser(
        prog="cursus",
        description="Cursus packaged baseline (M0). Runtime commands are not enabled yet.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
