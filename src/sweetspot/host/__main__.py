"""Chrome's entry point for the local program (feature 015; contracts/native-host.md "啟動").

Started by data/host/sweetspot-host.bat as
    python -m sweetspot.host --config <sweetspot.toml> chrome-extension://<id>/ [--parent-window=N]
It reads one message, answers it and exits. Standard output belongs to the channel, so it is set aside first and
everything else that writes to standard output goes to standard error instead.
"""

import argparse
import logging
import os
import sys
from pathlib import Path


def _claim_stdout():
    """(channel for replies, stdin) in binary mode; fd 1 and sys.stdout now point at stderr (or nowhere)."""
    channel_fd = os.dup(1)
    try:
        os.dup2(2, 1)
    except OSError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 1)
        os.close(devnull)
    sys.stdout = sys.stderr
    if sys.platform == "win32":
        import msvcrt

        msvcrt.setmode(channel_fd, os.O_BINARY)
        msvcrt.setmode(0, os.O_BINARY)
    return os.fdopen(channel_fd, "wb"), sys.stdin.buffer


def _data_dir(config_path: Path) -> Path:
    """The data folder of the settings file, also when the file cannot be loaded (014 T067): the request is still
    read and answered, and service tells the extension to fix the file (015 FR-017). A file that is not even TOML
    gives the default folder next to it, where `host install` writes the registration file too."""
    import tomllib

    from sweetspot.config import data_dir_of

    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        raw = {}
    try:
        return data_dir_of(config_path, raw)
    except (TypeError, ValueError):
        return data_dir_of(config_path, {})


def main(argv: list[str] | None = None) -> int:
    channel, stdin = _claim_stdout()
    parser = argparse.ArgumentParser(prog="sweetspot.host", add_help=False)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("origin", nargs="?")
    args, _ = parser.parse_known_args(argv)            # Chrome also passes --parent-window=N on Windows

    from sweetspot import cli
    from sweetspot.host import install, protocol, service
    from sweetspot.logs import setup_logging

    data_dir = _data_dir(args.config)
    setup_logging(data_dir, cli.load_secrets().redaction_values())
    log = logging.getLogger("sweetspot.host")
    if not args.origin or args.origin not in install.allowed_origins_in(data_dir):
        shown = (args.origin or "")[:80]
        log.warning(f"host refused origin={shown!r}: not the registered extension")
        return 1
    try:
        reply = service.answer(stdin, config_path=args.config)
        if reply is None:
            return 0
        protocol.write_message(channel, reply)
    except Exception:  # noqa: BLE001 - the log filter removes keys
        log.exception("host internal error")
        return 1
    finally:
        channel.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
