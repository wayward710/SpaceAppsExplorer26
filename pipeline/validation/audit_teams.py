
import json
from collections import Counter
from pathlib import Path

folder = Path("spaceapps_2026_raw")
files = sorted(folder.glob("teams_*.json"))

team_ids = set()
project_ids = set()
challenges = Counter()
locations = Counter()
member_countries = Counter()

stats = Counter()
duplicate_ids = []

for file in files:
    data = json.loads(file.read_text(encoding="utf-8"))
    edges = data["data"]["teams"]["edges"]

    for edge in edges:
        team = edge["node"]
        stats["team_records"] += 1

        team_id = team["id"]
        if team_id in team_ids:
            duplicate_ids.append(team_id)
        team_ids.add(team_id)

        challenge = team.get("challengeDetails") or {}
        location = team.get("locationDetails") or {}
        project = team.get("projectDetails") or {}

        challenges[challenge.get("title") or "(missing)"] += 1
        locations[location.get("country") or "(missing)"] += 1

        if team.get("projectSubmitted"):
            stats["team_project_submitted"] += 1

        if project:
            stats["teams_with_project_details"] += 1

            if project.get("id"):
                project_ids.add(project["id"])

            if project.get("isSubmitted"):
                stats["project_is_submitted"] += 1

            for field in (
                "summary",
                "details",
                "solution",
                "aiReferences",
                "aiToolsUsage",
                "dataReferences",
            ):
                if project.get(field):
                    stats[f"nonempty_{field}"] += 1

        countries_on_team = set()

        for membership in team.get("memberships") or []:
            stats["memberships"] += 1
            user = membership.get("userDetails") or {}
            country = user.get("country")

            if country:
                member_countries[country] += 1
                countries_on_team.add(country)
            else:
                stats["memberships_missing_country"] += 1

        if len(countries_on_team) > 1:
            stats["multicountry_teams"] += 1

print("\nCOLLECTION")
print("Files:", len(files))
print("Team records:", stats["team_records"])
print("Unique teams:", len(team_ids))
print("Duplicate team IDs:", len(duplicate_ids))
print("Unique project IDs:", len(project_ids))

print("\nSUBMISSIONS")
for key in (
    "teams_with_project_details",
    "team_project_submitted",
    "project_is_submitted",
):
    print(f"{key}: {stats[key]:,}")

print("\nPROJECT CONTENT")
for field in (
    "summary",
    "details",
    "solution",
    "aiReferences",
    "aiToolsUsage",
    "dataReferences",
):
    print(f"{field}: {stats[f'nonempty_{field}']:,}")

print("\nGEOGRAPHY")
print("Memberships:", stats["memberships"])
print("Memberships missing country:",
      stats["memberships_missing_country"])
print("Multicountry teams:", stats["multicountry_teams"])
print("Distinct reported member countries:",
      len(member_countries))

print("\nTEAMS BY CHALLENGE")
for name, count in challenges.most_common():
    print(f"{count:>6,}  {name}")

print("\nTOP 20 TEAM LOCATION COUNTRIES")
for name, count in locations.most_common(20):
    print(f"{count:>6,}  {name}")

print("\nTOP 20 MEMBER COUNTRIES")
for name, count in member_countries.most_common(20):
    print(f"{count:>6,}  {name}")
