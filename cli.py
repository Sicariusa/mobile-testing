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
import json
import os
import sys
import time

# Live screens carry glyphs (e.g. U+202F) the Windows cp1252 console can't
# encode; print UTF-8 and never let a stray character crash a report.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from engine import device as device_mod
from engine import inspect as inspect_mod
from engine.observation import observe


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


def cmd_inspect(args: argparse.Namespace) -> int:
    """Fetch the selectors of the CURRENT screen (any screen/popup) into a
    bundle, so a flow can be authored/verified against real ids."""
    try:
        dev = device_mod.connect(serial=args.serial)
    except device_mod.DeviceError as exc:
        print(f"Device error: {exc}", file=sys.stderr)
        return 3

    if args.apk:
        try:
            meta = device_mod.read_apk_metadata(args.apk)
            dev.install(args.apk)
            if args.launch and meta.get("package"):
                dev.launch(meta["package"], meta.get("launch_activity"))
                time.sleep(2)
        except device_mod.DeviceError as exc:
            print(f"APK step failed: {exc}", file=sys.stderr)

    out_dir = os.path.join(args.screens_dir, args.label)
    os.makedirs(out_dir, exist_ok=True)
    obs = observe(dev, os.path.join(out_dir, "screenshot.png"))
    els = obs.elements()
    interesting = inspect_mod.interesting(els)

    with open(os.path.join(out_dir, "hierarchy.xml"), "w", encoding="utf-8") as fh:
        fh.write(obs.hierarchy_xml or "")
    bundle = {
        "package": obs.package, "activity": obs.activity,
        "structural_fingerprint": obs.structural_fingerprint(),
        "content_fingerprint": obs.content_fingerprint(),
        "window": obs.window(),
        "element_count": len(els), "interesting_count": len(interesting),
        "elements": [e.as_dict() for e in els],
    }
    with open(os.path.join(out_dir, "observation.json"), "w", encoding="utf-8") as fh:
        json.dump(bundle, fh, indent=2, ensure_ascii=False)
    md = (f"# Screen: {args.label}\n\n"
          f"- package: `{obs.package}`\n- activity: `{obs.activity}`\n"
          f"- structural fingerprint: `{obs.structural_fingerprint()}`\n"
          f"- elements: {len(els)} ({len(interesting)} interesting)\n\n"
          + inspect_mod.format_table(els) + "\n")
    with open(os.path.join(out_dir, "inventory.md"), "w", encoding="utf-8") as fh:
        fh.write(md)

    print(f"Screen: {args.label}   activity={obs.activity}")
    print(inspect_mod.format_table(els))
    if not interesting:
        print("\n⚠ No interesting elements — the app may use a custom/Canvas/WebView "
              "surface; OCR of the screenshot is the perception fallback.")
    print(f"\nSaved bundle → {out_dir}\\ (observation.json, hierarchy.xml, "
          "screenshot.png, inventory.md)")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    """Re-print a finished run's per-step verdicts from its timeline.json —
    no device, no re-execution."""
    path = args.from_report
    if not path:
        runs = sorted((os.path.join("reports", d) for d in os.listdir("reports")),
                      reverse=True) if os.path.isdir("reports") else []
        path = next((os.path.join(r, "timeline.json") for r in runs
                     if os.path.exists(os.path.join(r, "timeline.json"))), None)
    if not path or not os.path.exists(path):
        print("No timeline.json found — pass --from-report <path>.", file=sys.stderr)
        return 2
    with open(path, "r", encoding="utf-8") as fh:
        tl = json.load(fh)
    meta, steps = tl.get("meta", {}), tl.get("steps", [])
    print(f"Replay: {meta.get('name','?')}  overall={meta.get('overall','?')}")
    print(f"{'#':>2}  {'status':<8} {'action':<22} {'resolved':<12} {'validated':<10} reason")
    for s in steps:
        print(f"{s.get('index','?'):>2}  {str(s.get('status','')):<8} "
              f"{str(s.get('action','')):<22} {str(s.get('resolved_by') or ''):<12} "
              f"{str(s.get('validated_by') or ''):<10} {s.get('failure_reason') or ''}")
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
    p.add_argument("--inspect", action="store_true",
                   help="Fetch the current screen's selectors into a bundle.")
    p.add_argument("--label", default="screen",
                   help="Name for the inspected screen's folder (default: screen).")
    p.add_argument("--launch", action="store_true",
                   help="With --inspect + --apk: install and launch before scanning.")
    p.add_argument("--screens-dir", default="screens",
                   help="Where --inspect writes screen bundles (default: screens).")
    p.add_argument("--from-report",
                   help="For replay: path to a run's timeline.json (default: latest).")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = None
    if argv and argv[0] in ("inspect", "run", "doctor", "replay"):
        command = argv.pop(0)
    args = build_parser().parse_args(argv)
    if command == "doctor" or args.check_env:
        return cmd_check_env()
    if command == "replay":
        return cmd_replay(args)
    if command == "inspect" or args.inspect:
        return cmd_inspect(args)
    if not args.test:
        print("error: --test is required for a run (or use --check-env / inspect).",
              file=sys.stderr)
        return 2
    if args.dry_run:
        return cmd_dry_run(args)
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
