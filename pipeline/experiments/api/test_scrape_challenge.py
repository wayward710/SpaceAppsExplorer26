
import requests

url = "https://api.spaceappschallenge.org/graphql"

query = """
query Challenges($first: Int!, $filtering: [Filter!]) {
  challenges(first: $first, filtering: $filtering) {
    totalCount
    edges {
      node {
        id
        title
        skills
        excerpt
        categories {
          name
          slug
        }
        meta {
          relativeUrl
        }
      }
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
"""

payload = {
    "operationName": "Challenges",
    "variables": {
        "first": 100,
        "filtering": [
            {
                "field": "event",
                "value": "aWQ6NA==",
                "compare": "id"
            }
        ]
    },
    "query": query
}

response = requests.post(url, json=payload, timeout=30)
response.raise_for_status()

result = response.json()

if result.get("errors"):
    raise RuntimeError(result["errors"])

challenges = result["data"]["challenges"]

print("Challenge count:", challenges["totalCount"])
print("More pages:", challenges["pageInfo"]["hasNextPage"])

for edge in challenges["edges"]:
    challenge = edge["node"]
    print(challenge["id"], challenge["title"])
