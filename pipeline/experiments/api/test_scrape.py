
import requests

URL = "https://api.spaceappschallenge.org/graphql"

query = """
query Event($id: EncodedID!) {
  event(id: $id) {
    id
    name
    cachedLocalEvents
    cachedTeams
    cachedProjects
    cachedEventRegistrations
  }
}
"""

payload = {
    "operationName": "Event",
    "variables": {"id": "aWQ6NA=="},
    "query": query,
}

response = requests.post(
    URL,
    json=payload,
    headers={"Accept": "application/json"},
    timeout=30,
)

print("HTTP status:", response.status_code)
print(response.text[:5000])
