"""End-to-end local agent demo.

Run from the repo root:
    python agents/demo_agent.py

Or from this folder:
    python demo_agent.py
"""

from __future__ import annotations

from resqra_agents import main_agent


DEMO_TEAMS = [
    {
        "id": "team_alpha",
        "name": "TEAM ALPHA",
        "status": "AVAILABLE",
        "capacity": 4,
        "location": {"lat": 25.6021, "lng": 85.1191},
    },
    {
        "id": "team_beta",
        "name": "TEAM BETA",
        "status": "AVAILABLE",
        "capacity": 15,
        "location": {"lat": 25.5831, "lng": 85.1581},
    },
    {
        "id": "team_gamma",
        "name": "TEAM GAMMA",
        "status": "ON_MISSION",
        "capacity": 8,
        "location": {"lat": 25.6161, "lng": 85.1451},
    },
]


def main() -> None:
    sos = "6 people stuck near Kankarbagh school, water rising fast, 2 children"
    out = main_agent.dispatch({
        "type": "new_distress_msg",
        "raw_text": sos,
        "source": "local_demo",
        "teams": DEMO_TEAMS,
    })["result"]

    incident = out["incident"]
    priority = out["priority"]
    recommendation = out["recommendation"]

    print("Input SOS:")
    print(sos)
    print()
    print("Extracted:")
    print(f"people={incident['people']}")
    print(f"urgency={incident['urgency']}")
    print(f"vulnerabilities={', '.join(incident['vulnerabilities']) or 'none'}")
    print(f"location_text={incident['location_text']}")
    print()
    print("Priority:")
    print(f"{priority['band']}, score {priority['score']}")
    for reason in priority["reasons"]:
        print(f"- {reason}")
    print()
    print("Recommendation:")
    if recommendation and recommendation.get("team_id"):
        print(f"{recommendation['team_name']} ({recommendation['team_id']})")
        print(recommendation["card_text"])
    else:
        print("No eligible team available")

    print()
    print("Resident Chat:")
    chat = main_agent.dispatch({
        "type": "resident_chat",
        "user_id": "usr_demo",
        "message": "We are 6 near Kankarbagh school, water is rising",
    })["result"]
    print(chat["reply"])

    print()
    print("Monitor Sweep:")
    monitor = main_agent.dispatch({
        "type": "monitor_sweep",
        "incidents": [incident],
        "teams": DEMO_TEAMS,
    })["result"]
    print(monitor["summary"])


if __name__ == "__main__":
    main()
