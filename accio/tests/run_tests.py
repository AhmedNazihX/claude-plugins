#!/usr/bin/env python3
"""Run each tests/test_*.py file in its own process, several at a time (S-017).

Usage: python3 run_tests.py [--jobs N] [--verbose]

Each file runs as "python3 -m unittest <module>" with this folder as the working directory,
the same import path "unittest discover -s tests" gives. The name does not start with "test",
so discover never loads this file. Exit 0 only when every file passed.
"""
import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAX_DEFAULT_JOBS = 8


def run_file(path, verbose):
    """Run one test file. Returns (name, passed, seconds, output)."""
    cmd = [sys.executable, "-m", "unittest", path.stem] + (["-v"] if verbose else [])
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    except OSError as err:
        return path.name, False, time.monotonic() - start, f"could not start: {err}\n"
    return path.name, proc.returncode == 0, time.monotonic() - start, proc.stdout + proc.stderr


def parse_args(argv):
    default_jobs = min(os.cpu_count() or 1, MAX_DEFAULT_JOBS)
    parser = argparse.ArgumentParser(description="Run each test file in its own process.")
    parser.add_argument("--jobs", type=int, default=default_jobs, help="files to run at once")
    parser.add_argument("--verbose", action="store_true", help="pass -v to each file")
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    return args


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    files = sorted(HERE.glob("test_*.py"))
    if not files:
        print(f"no test file found in {HERE}", file=sys.stderr)
        return 1
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(lambda f: run_file(f, args.verbose), files))
    for name, passed, seconds, _ in results:
        print(f"{'passed' if passed else 'FAILED'}  {name}  {seconds:.1f}s")
    failed = [r for r in results if not r[1]]
    for name, _, _, output in failed:
        print(f"\n===== {name} =====\n{output}")
    total = time.monotonic() - start
    print(f"{len(results)} files, {len(failed)} failed, {total:.1f}s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
