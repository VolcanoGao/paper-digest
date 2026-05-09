"""Standalone entrypoint to run the platform pipeline once.

Usage:
    .venv/bin/python -m app.jobs.daily_platform
"""
from __future__ import annotations

import logging

from app.pipeline.platform_run import run_platform_pipeline


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    stats = run_platform_pipeline()
    print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
