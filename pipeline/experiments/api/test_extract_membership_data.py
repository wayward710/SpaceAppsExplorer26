from pathlib import Path

html = Path("advantage.html").read_text(encoding="utf-8")

for term in ["memberships", "Hassan Raza Khan"]:
    pos = html.find(term)
    print(f"\n--- {term} at position {pos} ---")
    print(html[max(0, pos - 300):pos + 1000])