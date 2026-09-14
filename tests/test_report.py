"""Report: renders a self-contained HTML timeline with the key markers."""
from __future__ import annotations

from engine import report


def test_render_report(tmp_path):
    timeline = {
        "meta": {"name": "Demo", "package": "com.example.shop",
                 "run_id": "r1", "overall": "PASS"},
        "steps": [
            {"index": 0, "status": "PASS", "action": "tap",
             "target": {"text": "Login"}, "resolved_by": "text_exact",
             "resolved_confidence": 1.0, "validated_by": None, "duration_ms": 12,
             "recovery": {"attempts": []}, "ocr_matches": []},
            {"index": 1, "status": "PASS", "action": "assert:ocr_text_exists",
             "value": "PAY NOW", "validated_by": "ocr", "validation_confidence": 0.93,
             "recovery": {"attempts": []},
             "ocr_matches": [{"text": "PAY NOW", "confidence": 0.93}]},
            {"index": 2, "status": "BLOCKED", "action": "tap",
             "target": {"text": "Ghost"}, "recovery": {"attempts": [
                 {"method": "immediate", "outcome": "not_found", "detail": ""},
                 {"method": "ocr", "outcome": "not_found", "detail": ""}]},
             "ocr_matches": []},
        ],
    }
    out = report.render(timeline, str(tmp_path / "report.html"))
    html = open(out, encoding="utf-8").read()
    assert "Demo" in html
    assert "resolved_by" in html and "validated_by" in html
    assert "PAY NOW" in html          # ocr match rendered
    assert "recovery" in html          # recovery section rendered
    assert "BLOCKED" in html
    # color-coded badges present
    assert "#1f9d55" in html and "#c98a1b" in html
