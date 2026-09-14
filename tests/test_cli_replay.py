"""Phase 6 — replay re-prints a run's verdicts from timeline.json, no device."""
from __future__ import annotations

import json

import cli


def test_replay_reads_timeline(tmp_path, capsys):
    tl = {"meta": {"name": "Demo", "overall": "PASS"},
          "steps": [{"index": 0, "status": "PASS", "action": "tap",
                     "resolved_by": "ranked", "validated_by": None,
                     "failure_reason": None}]}
    path = tmp_path / "timeline.json"
    path.write_text(json.dumps(tl), encoding="utf-8")
    rc = cli.main(["replay", "--from-report", str(path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Demo" in out and "ranked" in out
