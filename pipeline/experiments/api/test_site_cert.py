import requests

url = "https://www.spaceappschallenge.org/2026/find-a-team/advantage/?tab=members"

response = requests.get(
    url,
    verify=r"E:\sac2026\www.space.apps.nasa.gov.pem",
    timeout=30,
)

print(response.status_code)
print(len(response.content))
print("memberships" in response.text)
print("Hassan Raza Khan" in response.text)