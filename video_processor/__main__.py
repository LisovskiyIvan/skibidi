"""Entry point for `python -m video_processor`."""

from __future__ import annotations

from .cli import main as cli_main
from .env_loader import load_env_file


def main() -> int:
    # Load secrets (e.g. HF_TOKEN) from a local .env before anything else runs.
    load_env_file()
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
