
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup


def extract_memberships(html):
    soup = BeautifulSoup(html, "html.parser")

    for script in soup.find_all("script"):
        content = script.string or ""

        if "self.__next_f.push" not in content:
            continue

        # Extract the JSON array passed to __next_f.push().
        match = re.search(
            r"self\.__next_f\.push\((\[.*\])\)\s*$",
            content,
            re.DOTALL,
        )

        if not match:
            continue

        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue

        if len(payload) < 2 or not isinstance(payload[1], str):
            continue

        decoded = payload[1]

        marker = '"memberships":'
        pos = decoded.find(marker)

        if pos == -1:
            continue

        start = pos + len(marker)

        try:
            memberships, _ = json.JSONDecoder().raw_decode(
                decoded[start:].lstrip()
            )
        except json.JSONDecodeError:
            continue

        if not isinstance(memberships, list):
            continue

        return [
            {
                "user_id": member.get("user"),
                "name": (member.get("userDetails") or {}).get("fullName"),
                "username": (member.get("userDetails") or {}).get("username"),
                "country": (member.get("userDetails") or {}).get("country"),
            }
            for member in memberships
        ]

    return None


html = Path("advantage.html").read_text(encoding="utf-8")
members = extract_memberships(html)

print(json.dumps(members, indent=2, ensure_ascii=False))
