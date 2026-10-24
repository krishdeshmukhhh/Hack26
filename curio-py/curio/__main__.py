"""Curio entry point: `python -m curio`."""

from __future__ import annotations

from curio.app import run


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
