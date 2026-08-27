"""Unit tests for ResQra agents — runs without any API key (tests regex fallback
and normalization logic) and optionally with GROQ_API_KEY for LLM tests.

Usage:
    python agents/tests/test_agents.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resqra_agents.agents.report_intake import (
    ReportIntakeAgent,
    extract,
    normalize_extraction,
    regex_extract,
    _parse_json_loose,
)
from resqra_agents.agents.resident import ResidentAgent, _degraded_extract
from resqra_agents.tools.context_builder import build_resident_context, build_rolling_summary
from resqra_agents.tools.priority_engine import compute_priority
from resqra_agents.tools.allocation_engine import recommend_team
from tests.golden_set import GOLDEN_SET


# ---------------------------------------------------------------------------
# ReportIntakeAgent tests
# ---------------------------------------------------------------------------

def test_parse_json_loose():
    assert _parse_json_loose('{"a": 1}') == {"a": 1}
    assert _parse_json_loose('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json_loose('Here is the result: {"a": 1} done.') == {"a": 1}
    assert _parse_json_loose("") is None
    assert _parse_json_loose("no json here") is None


def test_normalize_extraction():
    r = normalize_extraction({"people_count": "six", "urgency": "high"})
    assert r["people_count"] == 6
    assert r["urgency"] == "HIGH"
    assert r["needs_review"] is True  # no location

    r2 = normalize_extraction({"people_count": -1, "urgency": "invalid"})
    assert r2["people_count"] == 1  # clamped to min 1
    assert r2["urgency"] == "UNKNOWN"

    r3 = normalize_extraction({"vulnerabilities": ["children", "kids"]})
    assert "children" in r3["vulnerabilities"]
    assert "kids" in r3["other_flags"]


def test_regex_extract_basic():
    r = regex_extract("6 people stuck near Kankarbagh school, water rising fast, 2 children")
    assert r["people_count"] == 6
    assert r["urgency"] == "HIGH"
    assert "children" in r["vulnerabilities"]
    assert r["water_rising"] is True
    assert r["location_text"] is not None


def test_regex_extract_hindi():
    r = regex_extract("hum log chhe hain, paani tezi se badh raha hai, 5 log hain, bachche bhi hain")
    assert r["people_count"] == 5


def test_regex_extract_empty():
    r = regex_extract("")
    assert r["people_count"] is None
    assert r["needs_review"] is True


def test_extract_returns_source():
    r = extract("6 people stuck, water rising")
    assert "_source" in r
    assert r["_source"] in ("llm", "regex")


def test_intake_agent_process():
    agent = ReportIntakeAgent()
    result = agent.process("3 people stuck near school, water rising")
    assert result["status"] == "NEW"
    assert result["people"] == 3
    assert result["water_rising"] is True
    assert "id" in result


# ---------------------------------------------------------------------------
# ResidentAgent tests (degraded mode)
# ---------------------------------------------------------------------------

def test_resident_chat_degraded():
    agent = ResidentAgent()
    result = agent.chat("u_test", "We are 5 people, water rising near the bridge")
    assert "reply" in result
    assert result["degraded"] is True or result["source"] == "llm"
    assert result["profile_updates"]["people_with"] == 5


def test_resident_chat_safe():
    agent = ResidentAgent()
    result = agent.chat("u_test", "We are safe, 3 of us")
    assert "reply" in result


def test_degraded_extract():
    r = _degraded_extract("3 people near school, water rising, have children")
    assert r["people_with"] == 3
    assert "children" in (r["vulnerabilities"] or [])


# ---------------------------------------------------------------------------
# Context builder tests
# ---------------------------------------------------------------------------

def test_build_resident_context_empty():
    ctx = build_resident_context()
    assert ctx == "No additional context available."


def test_build_resident_context_with_data():
    ctx = build_resident_context(
        user_profile={"people_with": 3, "location_text": "near school"},
        active_incidents=[{"id": "inc_1", "people": 5, "location_text": "Kankarbagh", "status": "NEW"}],
        shelters=[{"name": "Shelter A", "capacity": 100, "current_occupancy": 30}],
    )
    assert "RESIDENT PROFILE" in ctx
    assert "ACTIVE INCIDENTS" in ctx
    assert "SHELTERS" in ctx


def test_build_rolling_summary():
    summary = build_rolling_summary([
        {"people": 5, "priority": {"score": 9}, "urgency": "HIGH", "location_text": "Kankarbagh"},
        {"people": 3, "priority": {"score": 4}, "urgency": "MEDIUM", "location_text": "Rajendra Nagar"},
    ])
    assert "8 people" in summary
    assert "Kankarbagh" in summary


# ---------------------------------------------------------------------------
# Priority engine tests (takes incident dict, not individual kwargs)
# ---------------------------------------------------------------------------

def test_priority_critical():
    incident = {
        "people": 5,
        "vulnerabilities": ["children", "elderly"],
        "urgency": "CRITICAL",
    }
    r = compute_priority(incident)
    assert r["score"] >= 8
    assert r["band"] in ("CRITICAL", "HIGH")


def test_priority_low():
    incident = {
        "people": 1,
        "vulnerabilities": [],
        "urgency": "LOW",
    }
    r = compute_priority(incident)
    assert r["score"] <= 4


# ---------------------------------------------------------------------------
# Allocation engine tests
# ---------------------------------------------------------------------------

def test_recommend_team():
    incident = {"id": "inc_1", "location": {"lat": 25.60, "lng": 85.14}, "people": 5}
    teams = [
        {"id": "team_a", "name": "Alpha", "status": "AVAILABLE", "capacity": 6,
         "location": {"lat": 25.61, "lng": 85.13}},
        {"id": "team_b", "name": "Beta", "status": "ON_MISSION", "capacity": 4,
         "location": {"lat": 25.58, "lng": 85.16}},
    ]
    rec = recommend_team(incident, teams)
    assert rec["team_id"] == "team_a"


def test_recommend_team_with_rejection():
    incident = {"id": "inc_1", "location": {"lat": 25.60, "lng": 85.14}, "people": 5}
    teams = [
        {"id": "team_a", "name": "Alpha", "status": "AVAILABLE", "capacity": 6,
         "location": {"lat": 25.61, "lng": 85.13}},
        {"id": "team_b", "name": "Beta", "status": "AVAILABLE", "capacity": 6,
         "location": {"lat": 25.58, "lng": 85.16}},
    ]
    rec = recommend_team(incident, teams, rejected_pairs={("team_a", "inc_1")})
    assert rec["team_id"] == "team_b"


# ---------------------------------------------------------------------------
# Golden set tests (regex path — always available)
# ---------------------------------------------------------------------------

def test_golden_set_regex():
    agent = ReportIntakeAgent()
    passed = 0
    failed = 0
    for case in GOLDEN_SET:
        result = agent.process(case["text"])
        ext = result.get("extraction", {})
        expected = case["expected"]
        errors = []

        if "people_count" in expected:
            got = ext.get("people_count")
            if got != expected["people_count"]:
                errors.append(f"people_count: got {got}, expected {expected['people_count']}")

        if "urgency" in expected:
            got = ext.get("urgency")
            if got != expected["urgency"]:
                errors.append(f"urgency: got {got}, expected {expected['urgency']}")

        if expected.get("has_children") and "children" not in ext.get("vulnerabilities", []):
            errors.append("missing children vulnerability")
        if expected.get("has_elderly") and "elderly" not in ext.get("vulnerabilities", []):
            errors.append("missing elderly vulnerability")
        if expected.get("has_pregnant") and "pregnant" not in ext.get("vulnerabilities", []):
            errors.append("missing pregnant vulnerability")
        if expected.get("has_injured") and "injured" not in ext.get("vulnerabilities", []):
            errors.append("missing injured vulnerability")
        if expected.get("has_disabled") and "disabled" not in ext.get("vulnerabilities", []):
            errors.append("missing disabled vulnerability")

        if "water_rising" in expected:
            got = ext.get("water_rising")
            if got != expected["water_rising"]:
                errors.append(f"water_rising: got {got}, expected {expected['water_rising']}")

        if "has_location" in expected:
            has_loc = ext.get("location_text") is not None
            if has_loc != expected["has_location"]:
                errors.append(f"has_location: got {has_loc}, expected {expected['has_location']}")

        if "needs_review" in expected:
            got = ext.get("needs_review")
            if got != expected["needs_review"]:
                errors.append(f"needs_review: got {got}, expected {expected['needs_review']}")

        if errors:
            failed += 1
            print(f"  FAIL: {case['name']}: {'; '.join(errors)}")
        else:
            passed += 1
            print(f"  PASS: {case['name']}")

    print(f"\nGolden set: {passed}/{passed + failed} passed")
    return failed == 0


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_parse_json_loose,
        test_normalize_extraction,
        test_regex_extract_basic,
        test_regex_extract_hindi,
        test_regex_extract_empty,
        test_extract_returns_source,
        test_intake_agent_process,
        test_resident_chat_degraded,
        test_resident_chat_safe,
        test_degraded_extract,
        test_build_resident_context_empty,
        test_build_resident_context_with_data,
        test_build_rolling_summary,
        test_priority_critical,
        test_priority_low,
        test_recommend_team,
        test_recommend_team_with_rejection,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print(f"  PASS: {test.__name__}")
        except Exception as e:
            failed += 1
            print(f"  FAIL: {test.__name__}: {e}")

    print(f"\nUnit tests: {passed}/{passed + failed} passed")
    print("\nGolden set (regex path):")
    golden_ok = test_golden_set_regex()

    if failed > 0 or not golden_ok:
        sys.exit(1)
    print("\nAll tests passed!")
