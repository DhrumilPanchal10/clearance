"""Episodic memory + playbook consolidation tests (plan T7.4)."""

from __future__ import annotations

from pathlib import Path

from clearance.memory.episodic import Episode, EpisodicMemory, consolidate


def _ep(outcome: str, reason: str | None = None, version: str = "L34220") -> Episode:
    return Episode(payer="medicare", procedure="lumbar_spine_mri", outcome=outcome,
                   denial_reason=reason, policy_version=version)


def test_consolidate_summarises_group() -> None:
    eps = [_ep("approved"), _ep("approved"), _ep("denied", "criteria_not_met"),
           _ep("denied", "criteria_not_met")]
    notes = consolidate(eps)
    assert len(notes) == 1
    note = notes[0]
    assert note.approvals == 2 and note.denials == 2
    assert note.top_denial_reasons[0] == ("criteria_not_met", 2)
    assert "criteria not met" in note.guidance


def test_below_min_episodes_no_note() -> None:
    assert consolidate([_ep("approved")]) == []


def test_version_change_expires_note(tmp_path: Path) -> None:
    mem = EpisodicMemory(tmp_path / "e.jsonl", tmp_path / "p.json")
    for _ in range(3):
        mem.record(_ep("approved", version="L34220"))
    mem.consolidate()
    assert mem.get_note("medicare", "lumbar_spine_mri", "L34220") is not None
    assert mem.get_note("medicare", "lumbar_spine_mri", "L99999") is None


def test_consolidate_uses_latest_version_cohort() -> None:
    eps = [_ep("denied", "old_reason", version="OLD")] * 5 + [
        _ep("approved", version="NEW"),
        _ep("approved", version="NEW"),
        _ep("approved", version="NEW"),
    ]
    notes = consolidate(eps)
    assert len(notes) == 1
    assert notes[0].policy_version == "NEW"
    assert notes[0].approvals == 3 and notes[0].denials == 0
