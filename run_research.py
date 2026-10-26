"""Command-line research runner (used by Windows Task Scheduler and the dashboard button).

Examples:
    python run_research.py                 # one full run
    python run_research.py --skip-youtube  # news + records only
    python run_research.py --schedule      # stay running and execute daily at the configured time
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bch import config, pipeline  # noqa: E402
from bch.db import get_setting, init_db  # noqa: E402


def _setup_logging() -> None:
    log_file = config.DATA_DIR / "research.log"
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler(sys.stdout)])


def _print_progress(frac: float, msg: str) -> None:
    print(f"[{frac * 100:5.1f}%] {msg}", flush=True)


def run_once(args) -> int:
    result = pipeline.run_research(trigger=args.trigger, progress=_print_progress,
                                   skip_youtube=args.skip_youtube, skip_records=args.skip_records)
    print("Result:", result.get("status"), result.get("stats", {}))
    return 0 if result.get("status") in ("completed", "completed_with_errors", "skipped") else 1


def run_scheduler(args) -> int:
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError:
        print("APScheduler is not installed. Use Windows Task Scheduler instead (see README).")
        return 1
    hh, mm = (get_setting("research_time") or "06:30").split(":")
    sched = BlockingScheduler()
    sched.add_job(lambda: run_once(args), "cron", hour=int(hh), minute=int(mm), id="daily_research",
                  misfire_grace_time=3600, coalesce=True)
    print(f"Scheduler running: daily research at {hh}:{mm}. Press Ctrl+C to stop.")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Bodycam Research Hub - research runner")
    p.add_argument("--trigger", default="cli", help="label stored with the run (cli/scheduled/dashboard)")
    p.add_argument("--skip-youtube", action="store_true")
    p.add_argument("--skip-records", action="store_true")
    p.add_argument("--schedule", action="store_true", help="run continuously with APScheduler")
    args = p.parse_args()
    _setup_logging()
    init_db()
    return run_scheduler(args) if args.schedule else run_once(args)


if __name__ == "__main__":
    raise SystemExit(main())
