"""Executable UTF-8 newline-delimited JSON bridge runner."""
from __future__ import annotations

import sys

from continuity_ai.bridge import Bridge, decode_command, encode_response
from continuity_ai.errors import ValidationError


def _validation_response() -> dict:
    return {
        "ok": False,
        "command": None,
        "error": ValidationError().to_dict(),
    }


def _handle_line(bridge: Bridge, raw_line: bytes) -> dict:
    try:
        command = decode_command(raw_line)
    except Exception:
        return _validation_response()
    return bridge.handle(command)


def main() -> int:
    """Process one UTF-8 JSON command per input line until clean EOF."""
    try:
        bridge = Bridge()
    except Exception:
        return 1

    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    while True:
        try:
            raw_line = stdin.readline()
        except Exception:
            return 1
        if raw_line == b"":
            return 0

        response = _handle_line(bridge, raw_line)
        try:
            stdout.write(encode_response(response))
            stdout.flush()
        except Exception:
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
