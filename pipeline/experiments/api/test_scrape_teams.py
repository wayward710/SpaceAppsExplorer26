
import json
import requests

URL = "https://api.spaceappschallenge.org/graphql"

with open("Pasted text(7).txt", encoding="utf-8") as f:
    operations = json.load(f)

payload = next(
    op for op in operations
    if op["operationName"] == "Teams"
)

payload["variables"]["first"] = 100
payload["variables"]["after"] = ""

response = requests.post(
    URL,
    json=payload,
    timeout=60,
)
response.raise_for_status()

result = response.json()

if result.get("errors"):
    raise RuntimeError(result["errors"])

teams = result["data"]["teams"]

print("Total teams:", teams["totalCount"])
print("Returned:", len(teams["edges"]))
print("Page info:", teams["pageInfo"])

for edge in teams["edges"][:10]:
    team = edge["node"]
    project = team.get("projectDetails") or {}

    print(
        team["title"],
        "| Project:", project.get("name"),
        "| Submitted:", project.get("isSubmitted"),
    )
