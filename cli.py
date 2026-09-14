#!/usr/bin/env python3
"""Command-line entrypoint for the Mobile QA Test Runner.

    python cli.py --check-env
    python cli.py --apk app.apk --test testcases/login.yaml

``--check-env`` diagnoses tooling and whether a live run is possible; it never
throws. A real run connects a device, executes the test case, and prints the
overall result plus the path to the HTML report.
"""
from __future__ import annotations

import argparse
import sys

from engine import device as device_mod


_LEVEL_NOTE = {
    "REQUIRED": "required",
    "REQUIRED-FOR-LIVE-RUN": "required for live run",
    "OPTIONAL": "optional",
}


def cmd_check_env() -> int:
    report = device_mod.probe_environment()
    print("Mobile QA Environment")
    print("─" * 48)
    for c in report["checks"]:
        mark = "✓" if c["status"] == "FOUND" else "✗"
        detail = f"  {c['detail']}" if c.get("detail") else ""
        note = _LEVEL_NOTE.get(c["level"], c["level"])
        print(f"  {c['name']:<14} {mark} {c['status']:<8} ({note}){detail}")
    print("─" * 48)
    print(f"  Core tests:  {'READY' if report['core_ready'] else 'BLOCKED'}")
    if report["live_ready"]:
        print("  Live runner: READY")
    else:
        print("  Live runner: BLOCKED")
        if not report["devices"]:
            print("               → connect an emulator or physical device "
                  "(see docs/SETUP_ANDROID.md).")
    return 0


def cmd_dry_run(args: argparse.Namespace) -> int:
    """Validate a test case and print its step plan without touching a device."""
    from engine.loader import load_testcase, TestCaseError

    try:
        tc = load_testcase(args.test)
    except (TestCaseError, OSError) as exc:
        print(f"Test case error: {exc}", file=sys.stderr)
        return 2

    data = tc.get("data", {})
    print(f"Test case: {tc['name']}")
    print(f"Package:   {tc['package']}")
    if data:
        print("Data:      " + ", ".join(f"{k}={v}" for k, v in data.items()))
    print(f"\nStep plan ({len(tc['steps'])} steps):")
    for i, step in enumerate(tc["steps"]):
        if "assert" in step:
            a = step["assert"]
            val = f" value={a.get('value')!r}" if a.get("value") is not None else ""
            print(f"  {i:>2}. assert {a.get('type')}{val}")
        else:
            tgt = f" target={step['target']}" if step.get("target") else ""
            val = f" value={step.get('value')!r}" if step.get("value") is not None else ""
            print(f"  {i:>2}. {step['action']}{tgt}{val}")
    print()
    cmd_check_env()
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    # fail early with precise guidance rather than a stack trace
    report = device_mod.probe_environment()
    if not report["live_ready"]:
        print("Cannot start a live run — environment is not ready:\n", file=sys.stderr)
        cmd_check_env()
        return 3

    from engine.runner import run

    try:
        dev = device_mod.connect(serial=args.serial)
    except device_mod.DeviceError as exc:
        print(f"Device error: {exc}", file=sys.stderr)
        return 3

    result = run(args.test, dev, apk_path=args.apk, base_dir=args.out)

    print()
    print(f"Overall: {result['overall']}")
    print("Steps:  " + " · ".join(f"{k}={v}" for k, v in result["counts"].items()))
    print(f"Report: {result['report_path']}")
    return 0 if result["overall"] == "PASS" else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cli.py", description="Android UI test runner (hierarchy + OCR).")
    p.add_argument("--apk", help="Path to the APK to install before the run.")
    p.add_argument("--test", help="Path to the YAML test case.")
    p.add_argument("--serial", help="ADB serial of the target device (default: first).")
    p.add_argument("--out", default="reports", help="Output directory (default: reports).")
    p.add_argument("--check-env", action="store_true",
                   help="Diagnose tooling/device readiness and exit.")
    p.add_argument("--dry-run", action="store_true",
                   help="Validate --test and print its step plan without a device.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.check_env:
        return cmd_check_env()
    if not args.test:
        print("error: --test is required for a run (or use --check-env).", file=sys.stderr)
        return 2
    if args.dry_run:
        return cmd_dry_run(args)
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
