"""Approval gate demo: agent recommends, human approves, code executes.

Run from the repo root:
    python agents/demo_approval.py
"""

from __future__ import annotations

from resqra_agents import main_agent


DEMO_TEAMS = [
    {
        "id": "team_alpha",
        "name": "TEAM ALPHA",
        "status": "AVAILABLE",
        "capacity": 10,
        "location": {"lat": 25.6021, "lng": 85.1191},
    },
    {
        "id": "team_beta",
        "name": "TEAM BETA",
        "status": "AVAILABLE",
        "capacity": 15,
        "location": {"lat": 25.5831, "lng": 85.1581},
    },
]

SOS = "3 people stuck near Raja Bazar, water rising fast"


def recommend(incident_text: str) -> dict:
    out = main_agent.dispatch({
        "type": "new_distress_msg",
        "raw_text": incident_text,
        "source": "approval_demo",
        "teams": DEMO_TEAMS,
    })["result"]
    return out


def main() -> None:
    print("SOS:")
    print(SOS)
    out = recommend(SOS)
    incident = out["incident"]
    card = out["pending_action"]

    print()
    print(f"Priority: {incident['priority']['band']} (score {incident['priority']['score']})")
    if card is None:
        print("No eligible team -> no approval card. Coordinator review needed.")
        return

    print("Recommendation card created:")
    print(f"  id={card['id']} state={card['state']}")
    print(f"  proposed={card['proposed_team_id']}")
    for reason in card["reasons"]:
        print(f"  - {reason}")

    print()
    print("--- Coordinator REJECTS the recommendation ---")
    rejected = main_agent.decide_approval(card["id"], "REJECTED", coordinator_id="coord_1")
    print(f"card state={rejected['pending_action']['state']}")

    print()
    print("--- Re-recommend for the SAME incident after rejection ---")
    out2 = main_agent.dispatch({
        "type": "recommend_team",
        "incident": out["incident"],
        "teams": DEMO_TEAMS,
    })["result"]
    card2 = out2["pending_action"]
    if card2 is None:
        print("No other eligible team available.")
        return
    print(f"new card proposes={card2['proposed_team_id']} "
          f"(rejected team not recommended again)")
    for reason in card2["reasons"]:
        print(f"  - {reason}")

    print()
    print("--- Coordinator APPROVES the new card ---")
    approved = main_agent.decide_approval(
        card2["id"], "APPROVED", coordinator_id="coord_1"
    )
    mission = approved["mission"]
    print(f"executed={approved['executed']}")
    print(f"mission={mission['id']} status={mission['status']}")
    print(f"team={approved['team']['id']} status={approved['team']['status']}")
    print(f"incident={approved['incident']['id']} status={approved['incident']['status']}")

    print()
    print("--- Approve the same card again (double click) ---")
    again = main_agent.decide_approval(card2["id"], "APPROVED", coordinator_id="coord_1")
    print(f"executed={again['executed']} already_decided={again.get('already_decided', False)}")

    print()
    print("--- WatchAgent sweep with replan ---")
    stuck = {
        "id": "inc_sweep_demo",
        "status": "NEW",
        "people": 5,
        "urgency": "HIGH",
        "created_at": 0,
        "location": {"lat": 25.5941, "lng": 85.1371},
        "priority": {"score": 9, "band": "HIGH"},
    }
    sweep = main_agent.dispatch({
        "type": "monitor_sweep",
        "incidents": [approved["incident"], stuck],
        "teams": DEMO_TEAMS,
        "replan": True,
    })["result"]
    print(sweep["summary"])
    for auto_card in sweep["pending_actions_created"]:
        print(f"auto card: {auto_card['id']} proposes "
              f"{auto_card['proposed_team_id']} for {auto_card['incident_id']}")


if __name__ == "__main__":
    main()
