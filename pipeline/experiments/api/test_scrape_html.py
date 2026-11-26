import truststore
truststore.inject_into_ssl()

import requests

url = "https://www.spaceappschallenge.org/2026/find-a-team/advantage/?tab=members"

response = requests.get(
    url,
    headers={"User-Agent": "Mozilla/5.0"},
    timeout=30,
    verify=False
)

print("Status:", response.status_code)
print("Content type:", response.headers.get("Content-Type"))
print("Length:", len(response.content))

for term in ["memberships", "Hassan Raza Khan", "Gergo Meszaros"]:
    print(f"{term!r}:", term in response.text)

with open("advantage.html", "w", encoding="utf-8") as f:
    f.write(response.text)
