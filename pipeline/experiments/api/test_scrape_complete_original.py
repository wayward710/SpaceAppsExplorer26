
import json
import time
from pathlib import Path

import requests

URL = "https://api.spaceappschallenge.org/graphql"
OUTPUT = Path("spaceapps_2026_raw")
OUTPUT.mkdir(exist_ok=True)

with open("Pasted text(7).txt", encoding="utf-8") as f:
    operations = json.load(f)

template = next(
    op for op in operations
    if op["operationName"] == "Teams"
)

query = template["query"]
variables = template["variables"].copy()
variables["first"] = 100

session = requests.Session()
session.headers.update({"Accept": "application/json"})

cursor = None
page_number = 0
total_records = 0

while True:
    filename = OUTPUT / f"teams_{page_number:04d}.json"

    if filename.exists():
        result = json.loads(filename.read_text(encoding="utf-8"))
    else:
        variables["after"] = cursor or ""

        response = session.post(
            URL,
            json={
                "operationName": "Teams",
                "variables": variables,
                "query": query,
            },
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()

        if result.get("errors"):
            raise RuntimeError(result["errors"])

        # Save atomically to avoid incomplete checkpoints.
        temporary = filename.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(result, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(filename)

    teams = result["data"]["teams"]
    edges = teams["edges"]
    info = teams["pageInfo"]

    total_records += len(edges)

    print(
        f"Page {page_number}: "
        f"{len(edges)} teams, "
        f"{total_records} collected / "
        f"{teams['totalCount']} total"
    )

    if not info["hasNextPage"]:
        break

    cursor = info["endCursor"]
    if not cursor:
        raise RuntimeError("Missing pagination cursor")

    page_number += 1
    time.sleep(0.5)

print("Collection complete:", total_records)
