
import json
import random
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

RAW_DIR = Path("spaceapps_2026_raw")
OUTPUT_DIR = Path("spaceapps_2026_members")
OUTPUT_DIR.mkdir(exist_ok=True)

PILOT_SIZE = 20
DELAY_SECONDS = 1.5
TIMEOUT_SECONDS = 30

session = requests.Session()
session.headers.update({
    "User-Agent": "SpaceApps2026ResearchCatalog/0.1"
})


def extract_memberships(html, expected_team_id):
    soup = BeautifulSoup(html, "html.parser")

    for script in soup.find_all("script"):
        content = script.string or ""

        if "self.__next_f.push" not in content:
            continue

        match = re.search(
            r"self\.__next_f\.push\((\[.*\])\)\s*$",
            content,
            re.DOTALL,
        )

        if not match:
            continue

        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue

        if len(payload) < 2 or not isinstance(payload[1], str):
            continue

        decoded = payload[1]

        # Ensure this payload contains the expected team.
        if f'"id":"{expected_team_id}"' not in decoded:
            continue

        marker = '"memberships":'
        pos = decoded.find(marker)

        if pos < 0:
            continue

        try:
            memberships, _ = json.JSONDecoder().raw_decode(
                decoded[pos + len(marker):].lstrip()
            )
        except json.JSONDecodeError:
            continue

        if not isinstance(memberships, list):
            continue

        return [
            {
                "user_id": member.get("user"),
                "name": (member.get("userDetails") or {}).get("fullName"),
                "username": (member.get("userDetails") or {}).get("username"),
                "country": (member.get("userDetails") or {}).get("country"),
            }
            for member in memberships
        ]

    return None


def load_submitted_teams():
    teams = []

    for filename in sorted(RAW_DIR.glob("teams_*.json")):
        data = json.loads(filename.read_text(encoding="utf-8"))

        for edge in data["data"]["teams"]["edges"]:
            team = edge["node"]

            if not team.get("projectSubmitted"):
                continue

            relative_url = (team.get("meta") or {}).get("relativeUrl")

            if relative_url:
                teams.append({
                    "id": team["id"],
                    "title": team["title"],
                    "url": (
                        "https://www.spaceappschallenge.org"
                        + relative_url
                    ),
                })

    return teams


def collect_team(team):
    response = session.get(
        team["url"],
        timeout=TIMEOUT_SECONDS,
        verify=False,  # Temporary: certificate issue
    )
    response.raise_for_status()

    members = extract_memberships(response.text, team["id"])

    return {
        **team,
        "status": "ok" if members is not None else "parse_failed",
        "members": members,
    }


def main():
    #teams = load_submitted_teams()
    teams = [t for t in load_submitted_teams()
             if t["title"] == "The Entangled Devs"]

    print(f"Submitted teams: {len(teams):,}")

    random.seed(2026)
    sample = random.sample(teams, min(PILOT_SIZE, len(teams)))

    for index, team in enumerate(teams, start=1):
        output_file = OUTPUT_DIR / f"{team['id']}.json"

        if output_file.exists():
            print(f"[{index}/{len(teams)}] Skipping {team['title']}")
            continue

        try:
            result = collect_team(team)
        except requests.RequestException as exc:
            result = {
                **team,
                "status": "request_failed",
                "error": str(exc),
                "members": None,
            }

        output_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        count = len(result["members"]) if result["members"] is not None else "?"
        print(
            f"[{index}/{len(sample)}] "
            f"{team['title']}: {result['status']} "
            f"({count} members)"
        )

        time.sleep(DELAY_SECONDS)


if __name__ == "__main__":
    main()
