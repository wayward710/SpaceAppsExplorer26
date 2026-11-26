import json
from pathlib import Path

for path in Path("spaceapps_2026_members").glob("*.json"):
    team = json.loads(path.read_text(encoding="utf-8"))

    if team["status"] != "ok":
        continue

    countries = {
        member["country"]
        for member in team["members"]
        if member.get("country")
    }

    if len(countries) > 1:
        print(team["title"], sorted(countries))