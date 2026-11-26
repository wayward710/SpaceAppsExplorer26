import requests

url = "https://api.spaceappschallenge.org/graphql"

query = """
query Page($input: EncodedID!) {
  page(id: $input) {
    __typename
    ... on TeamPage {
      id
      title
      memberships {
        userDetails {
          fullName
          country
        }
      }
    }
  }
}
"""

response = requests.post(
    url,
    json={
        "operationName": "Page",
        "variables": {"input": "aWQ6Nzk2OTU="},
        "query": query,
    },
    timeout=30,
)

print(response.status_code)
print(response.text[:5000])
