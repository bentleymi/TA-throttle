#!/usr/bin/env python3
"""Emit one JSON event per cycle with CPU frequency and thermal throttle state."""
import sys

from throttle_common import discover, emit


def main():
    try:
        data = discover()
    except Exception:
        data = {"status": "absent", "cpu_count": 0, "governors": {}, "packages": {}}
    emit(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
