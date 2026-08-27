"""No-cloud smoke test for the ResQra agent base.

Run from the repo root:
    python agents/smoke_test.py
"""

from resqra_agents import main_agent


TEAMS = [
    {
        "id": "team_alpha",
        "name": "TEAM ALPHA",
        "status": "AVAILABLE",
        "capacity": 10,
        "location": {"lat": 25.60, "lng": 85.13},
    },
    {
        "id": "team_beta",
        "name": "TEAM BETA",
        "status": "AVAILABLE",
        "capacity": 15,
        "location": {"lat": 25.5831, "lng": 85.1581},
    },
]


def main() -> None:
    incident = {
        "id": "inc_test",
        "people": 6,
        "urgency": "HIGH",
        "vulnerabilities": ["children"],
        "created_at": 0,
        "location": {"lat": 25.59, "lng": 85.14},
    }

    # 1. Deterministic priority scoring.
    score = main_agent.score_incident(incident, now=60)
    assert score["band"] == "HIGH", score

    # 2. Deterministic team recommendation + approval card creation.
    rec_out = main_agent.dispatch({
        "type": "recommend_team",
        "incident": incident,
        "teams": TEAMS,
    })["result"]
    recommendation = rec_out["recommendation"]
    assert recommendation["team_id"] == "team_alpha", recommendation  # nearest eligible
    card = rec_out["pending_action"]
    assert card and card["state"] == "PENDING", card

    # 3. Rejection memory: rejected team is never proposed again.
    main_agent.decide_approval(card["id"], "REJECTED", coordinator_id="coord_test")
    again = main_agent.recommend_team(incident, TEAMS)
    assert again["recommendation"]["team_id"] == "team_beta", again
    assert any("already rejected" in r for r in again["recommendation"]["reasons"]), again

    # 4. Approve -> mission executes exactly once (idempotent double click).
    card2 = again["pending_action"]
    approved = main_agent.decide_approval(card2["id"], "APPROVED", coordinator_id="coord_test")
    assert approved["executed"] is True, approved
    assert approved["mission"]["status"] == "ACTIVE"
    assert approved["team"]["status"] == "ON_MISSION"
    assert approved["incident"]["status"] == "ASSIGNED"

    replay = main_agent.decide_approval(card2["id"], "APPROVED", coordinator_id="coord_test")
    assert replay["executed"] is False and replay.get("already_decided"), replay
    assert len(main_agent.control_room.missions.list()) == 1

    # 5. WatchAgent sweep finds hotspots/delays and can auto-propose cards.
    stuck = {
        "id": "inc_sweep",
        "status": "NEW",
        "people": 5,
        "urgency": "HIGH",
        "created_at": 0,
        "location": {"lat": 25.5941, "lng": 85.1371},
        "priority": {"band": "HIGH", "score": 9},
    }
    sweep = main_agent.control_room.watch_agent.sweep([stuck], TEAMS, replan=True, now=10_000)
    assert sweep["unassigned_high_priority"] == ["inc_sweep"], sweep
    assert sweep["pending_actions_created"], sweep

    print("agent smoke ok")


if __name__ == "__main__":
    main()
