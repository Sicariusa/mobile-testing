#!/usr/bin/env python3
"""Drive a login flow BY HAND through the engine's device layer — no runner, no
YAML. Useful to see each perceive/act/validate step in isolation, or to probe a
new app's screen before writing a test case.

Defaults target the bundled sample app. Point it at any app with flags:

    python examples/manual_flow.py --serial emulator-5554
    python examples/manual_flow.py --package com.nextcloud.client \\
        --launch-activity com.nmc.android.ui.LauncherActivity \\
        --pre-tap-text "Log in" \\
        --email-id com.nextcloud.client:id/host_url_input --email https://x.invalid \\
        --login-id com.nextcloud.client:id/text_input_end_icon \\
        --expect-text "Could not find host"

Each step prints what it did and saves a screenshot into --out.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import device as dev
from engine import models, observation, validator


def _find(d, kind, value):
    el = d.find(kind, value)
    if el is None:
        raise SystemExit(f"element not found: {kind}={value!r}")
    return el


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Manual login flow via the device layer.")
    p.add_argument("--serial")
    p.add_argument("--package", default="com.example.shop")
    p.add_argument("--launch-activity", default=None)
    p.add_argument("--pre-tap-text", default=None,
                   help="Optional button text to tap before the form (e.g. 'Log in').")
    p.add_argument("--email-id", default="com.example.shop:id/email")
    p.add_argument("--email", default="test@example.com")
    p.add_argument("--password-id", default="com.example.shop:id/password")
    p.add_argument("--password", default="Password123")
    p.add_argument("--login-id", default=None)
    p.add_argument("--login-text", default="Login")
    p.add_argument("--expect-text", default="Welcome")
    p.add_argument("--expect-ocr", default="PAY NOW")
    p.add_argument("--out", default="manual-demo")
    p.add_argument("--settle", type=float, default=1.5)
    args = p.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    d = dev.connect(serial=args.serial)
    print("connected:", d.serial)

    def shot(name):
        d.screenshot(os.path.join(args.out, name))

    print("\n[0] launch", args.package)
    d.clear_data(args.package)
    d.launch(args.package, args.launch_activity)
    time.sleep(args.settle)
    print("    activity:", d.current_activity())
    shot("01_launched.png")

    if args.pre_tap_text:
        print("[*] pre-tap:", args.pre_tap_text)
        _find(d, models.STRATEGY_TEXT_EXACT, args.pre_tap_text).click()
        time.sleep(args.settle)
        shot("01b_after_pretap.png")

    print("[1] type email ->", args.email_id)
    _find(d, models.STRATEGY_RESOURCE_ID, args.email_id).set_text(args.email)
    shot("02_email.png")

    if args.password_id:
        print("[2] type password ->", args.password_id)
        _find(d, models.STRATEGY_RESOURCE_ID, args.password_id).set_text(args.password)
        shot("03_password.png")

    print("[3] tap login")
    if args.login_id:
        _find(d, models.STRATEGY_RESOURCE_ID, args.login_id).click()
    else:
        _find(d, models.STRATEGY_TEXT_EXACT, args.login_text).click()
    time.sleep(args.settle)
    after = os.path.join(args.out, "04_after_login.png")
    d.screenshot(after)

    print("\n[4] validate")
    before = observation.observe(d, os.path.join(args.out, "_before.png"))
    obs = observation.observe(d, os.path.join(args.out, "_after.png"))
    if args.expect_text:
        out = validator.validate({"type": "text_exists", "value": args.expect_text}, before, obs)
        print(f"    text_exists {args.expect_text!r:<22} -> {out.status.value:<5} validated_by={out.validated_by}")
    if args.expect_ocr:
        out = validator.validate({"type": "ocr_text_exists", "value": args.expect_ocr}, before, obs)
        print(f"    ocr_text_exists {args.expect_ocr!r:<18} -> {out.status.value:<5} validated_by={out.validated_by}")
    print("\nscreenshots in", os.path.abspath(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
