import requests

url = "https://api.spaceappschallenge.org/graphql"

query = """
query Teams($filtering: [Filter!]) {
  teams(first: 10, filtering: $filtering) {
    totalCount
    edges {
      node {
        id
        title
        ownerDetails {
          username
        }
        memberships {
          userDetails {
            fullName
            username
            country
          }
        }
      }
    }
  }
}
"""

variables = {
    "filtering": [
        {
            "field": "event",
            "value": "aWQ6NA==",
            "compare": "id"
        }
    ],
    "q": "Advantage"
}

response = requests.post(
    url,
    json={
        "query": query,
        "variables": variables
    },
    timeout=30
)

print(response.status_code)
print(response.text[:5000])