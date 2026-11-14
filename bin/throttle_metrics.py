#!/usr/bin/env python3
"""Emit flat numeric metrics (one JSON event per cycle) for analytics."""
import sys

from throttle_common import discover, emit, metrics_payload


def main():
    try:
        emit(metrics_payload(discover()))
    except Exception:
        emit({"cpu_count": 0, "pkg_count": 0})
    return 0


if __name__ == "__main__":
    sys.exit(main())
