
import json
from collections import Counter
from pathlib import Path

RAW_DIR = Path("spaceapps_2026_raw")
MEMBERS_DIR = Path("spaceapps_2026_members")

# Load submitted teams from original GraphQL collection.
submitted = {}

for path in sorted(RAW_DIR.glob("teams_*.json")):
    data = json.loads(path.read_text(encoding="utf-8"))

    for edge in data["data"]["teams"]["edges"]:
        team = edge["node"]

        if team.get("projectSubmitted"):
            submitted[team["id"]] = team

# Audit membership results.
statuses = Counter()
member_counts = Counter()
countries = Counter()
international_teams = []
missing_countries = 0
total_members = 0
processed = set()
errors = []

for path in MEMBERS_DIR.glob("*.json"):
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append((path.name, str(exc)))
        continue

    team_id = result.get("id")
    processed.add(team_id)

    status = result.get("status", "unknown")
    statuses[status] += 1

    if status != "ok":
        errors.append((result.get("title"), result.get("error", status)))
        continue

    members = result.get("members")

    if not isinstance(members, list):
        errors.append((result.get("title"), "Missing member array"))
        continue

    member_counts[len(members)] += 1
    total_members += len(members)

    team_countries = set()

    for member in members:
        country = member.get("country")

        if country:
            countries[country] += 1
            team_countries.add(country)
        else:
            missing_countries += 1

    if len(team_countries) > 1:
        international_teams.append({
            "id": team_id,
            "title": result.get("title"),
            "countries": sorted(team_countries),
            "member_count": len(members),
        })

missing_teams = set(submitted) - processed

print("\nCOLLECTION")
print(f"Submitted teams: {len(submitted):,}")
print(f"Output files: {len(list(MEMBERS_DIR.glob('*.json'))):,}")
print(f"Processed team IDs: {len(processed):,}")
print(f"Missing teams: {len(missing_teams):,}")

print("\nSTATUS")
for status, count in statuses.most_common():
    print(f"{status}: {count:,}")

print("\nMEMBERS")
print(f"Total membership records: {total_members:,}")
print(f"Missing country values: {missing_countries:,}")
print(f"International teams: {len(international_teams):,}")

print("\nTEAM SIZE DISTRIBUTION")
for size, count in sorted(member_counts.items()):
    print(f"{size:2} members: {count:,} teams")

print("\nTOP 20 MEMBER COUNTRIES")
for country, count in countries.most_common(20):
    print(f"{count:>7,}  {country}")

print("\nSAMPLE INTERNATIONAL TEAMS")
for team in international_teams[:20]:
    print(
        f"{team['title']}: "
        f"{', '.join(team['countries'])} "
        f"({team['member_count']} members)"
    )

print("\nERRORS")
for name, error in errors[:20]:
    print(f"{name}: {error}")

# Save audit results for subsequent analysis.
Path("membership_audit.json").write_text(
    json.dumps(
        {
            "submitted_teams": len(submitted),
            "processed_teams": len(processed),
            "missing_team_ids": sorted(missing_teams),
            "statuses": dict(statuses),
            "member_count_distribution": dict(member_counts),
            "countries": dict(countries),
            "international_teams": international_teams,
            "errors": errors,
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
