"""Fuzzy free-text DB-match: structured fields exact, prose columns by content overlap."""

from __future__ import annotations

from eops_gym.domains.itsm.data_model import Notification
from eops_gym.domains.itsm.environment import get_environment
from eops_gym.evaluator.evaluator_env import compare_dbs
from eops_gym.utils.text_match import fuzzy_text_match, text_overlap


def test_fuzzy_text_match():
    gold = "Update on INC0000003 (Printer connectivity issue)"
    verbose = "Update on your incident INC0000003 — printer connectivity work has resumed"
    assert text_overlap(gold, verbose) >= 0.5
    assert fuzzy_text_match(gold, verbose)                 # agent superset of gold
    assert fuzzy_text_match(None, None)                    # both empty -> no requirement
    assert fuzzy_text_match("", "anything")                # empty gold -> match
    assert not fuzzy_text_match(gold, None)                # gold has content, pred empty
    assert not fuzzy_text_match(gold, "vacation request approved")  # unrelated


def _db_with_notification(**overrides):
    db = get_environment().tools.db.model_copy(deep=True)
    fields = dict(
        notification_id="NOTIF_900", incident_id="INC_003", org_id="ORG_001",
        email="carlos.rodriguez@techcorp.com", type="update", status="queued",
        subject="Work resumed on INC0000003", message="the replacement part arrived",
        created_on="2024-06-01T00:00:00", updated_on="2024-06-01T00:00:00",
    )
    fields.update(overrides)
    db.notification["NOTIF_900"] = Notification(**fields)
    return db


def test_compare_dbs_freetext_is_fuzzy():
    gold = _db_with_notification()
    # Different prose, same meaning -> still matches.
    paraphrase = _db_with_notification(
        subject="Update: work on INC0000003 has resumed now",
        message="the part we were waiting on has arrived",
    )
    matched, mismatches = compare_dbs(gold, paraphrase)
    assert matched, mismatches


def test_compare_dbs_structured_is_exact():
    gold = _db_with_notification()
    for over in ({"email": "aisha.williams@techcorp.com"}, {"type": "alert"}, {"status": "sent"}):
        matched, mismatches = compare_dbs(gold, _db_with_notification(**over))
        assert not matched, f"{over} should not match"
        assert any("NOTIF_900" in m for m in mismatches)


def test_compare_dbs_unrelated_freetext_fails():
    gold = _db_with_notification()
    matched, _ = compare_dbs(gold, _db_with_notification(subject="vacation request approved"))
    assert not matched


def test_compare_dbs_extra_or_missing_row_fails():
    gold = _db_with_notification()
    base = get_environment().tools.db                 # no NOTIF_900
    matched, mismatches = compare_dbs(gold, base)
    assert not matched and any("missing" in m for m in mismatches)


def test_freetext_unchanged_by_gold_is_ignored():
    # gold leaves INC_003.worknotes at its seed value; the agent overwrote it with an unrelated
    # note. Since the task never set worknotes, the agent's value must NOT be penalised.
    base = get_environment().tools.db
    gold = base.model_copy(deep=True)                 # unchanged vs baseline
    pred = base.model_copy(deep=True)
    pred.incident["INC_003"].worknotes = "agent added a transition note about the vendor part"
    assert compare_dbs(gold, pred, baseline_db=base)[0]      # ignored -> match
    assert not compare_dbs(gold, pred)[0]                    # no baseline -> (incorrectly) fails
