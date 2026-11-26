
import json
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

SOURCE_DIR = Path("vocabulary_v2")
OUTPUT_DIR = Path("keyword_review")
OUTPUT_DIR.mkdir(exist_ok=True)

# A small, deliberately conservative synonym dictionary.
# These mappings can be expanded after reviewing examples.
ALIASES = {
    "soil water content": "soil moisture",
    "crop rotations": "crop rotation",
    "brown dwarf": "brown dwarfs",
    "synthetic aperture radar": "synthetic aperture radar",
    "sar imagery": "synthetic aperture radar",
    "l band radar": "l-band radar",
    "lunar south pole": "lunar south pole",
    "machine learning": "machine learning",
    "computer vision": "computer vision",
}

# Phrases that are submission boilerplate, malformed
# n-grams, or too generic to be useful as keywords.
REJECT_EXACT = {
    "intended impact",
    "factors considered",
    "benefits intended impact",
    "tools coding languages",
    "does does work",
    "data nisar",
    "https github com",
    "github com",
    "https www",
    "current crop",
}

REJECT_CONTAINS = (
    "intended impact",
    "factors considered",
    "coding languages",
    "github com",
    "https",
    "www",
    "does does",
)

# Initial categorization hints. These are not an
# exhaustive taxonomy and should be reviewed.
CATEGORY_TERMS = {
    "scientific_subject": {
        "soil moisture", "groundwater", "aquifer",
        "groundwater recharge", "crop rotation",
        "soil health", "climate change", "drought",
        "flooding", "wildfire", "brown dwarfs",
        "exoplanets", "orbital mechanics",
        "lunar south pole", "microgravity",
        "air quality", "water quality",
    },
    "technology": {
        "synthetic aperture radar", "l-band radar",
        "machine learning", "deep learning",
        "computer vision", "remote sensing",
        "geographic information systems",
        "augmented reality", "virtual reality",
        "natural language processing",
        "python", "javascript", "react",
    },
    "data_source": {
        "nisar", "modis", "viirs", "spherex",
        "landsat", "sentinel-1", "sentinel-2",
        "gpm", "imerg", "earthdata",
    },
    "application_area": {
        "disaster response", "precision agriculture",
        "astronaut health", "fire detection",
        "wildfire detection", "crop monitoring",
        "health monitoring", "space education",
        "lunar navigation", "mission planning",
    },
}


def normalize(phrase):
    phrase = str(phrase).lower().strip()
    phrase = re.sub(r"\s+", " ", phrase)
    phrase = phrase.strip(".,;:!?- ")

    return ALIASES.get(phrase, phrase)


def reject_reason(phrase):
    if phrase in REJECT_EXACT:
        return "known boilerplate or malformed phrase"

    if any(fragment in phrase for fragment in REJECT_CONTAINS):
        return "contains boilerplate or URL fragment"

    if re.search(r"\b(?:http|html|www|com)\b", phrase):
        return "likely URL or markup fragment"

    if len(phrase) < 3:
        return "too short"

    return ""


def classify(phrase):
    for category, terms in CATEGORY_TERMS.items():
        if phrase in terms:
            return category

    return "unclassified"


def parse_examples(value):
    if pd.isna(value) or not str(value).strip():
        return []

    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def load_candidates():
    global_df = pd.read_csv(
        SOURCE_DIR / "global_ngrams.csv"
    )

    challenge_df = pd.read_csv(
        SOURCE_DIR / "challenge_ngrams.csv"
    )

    # The challenge file contains both frequency and
    # enrichment rankings. Each phrase can appear more
    # than once, so we aggregate by normalized phrase.
    records = defaultdict(lambda: {
        "variants": set(),
        "global_count": 0,
        "challenges": {},
        "example_ids": [],
        "ngram_sizes": set(),
    })

    for row in global_df.to_dict("records"):
        original = str(row["phrase"]).strip()
        phrase = normalize(original)

        record = records[phrase]
        record["variants"].add(original)
        record["global_count"] = max(
            record["global_count"],
            int(row["project_count"]),
        )
        record["ngram_sizes"].add(
            int(row["ngram_size"])
        )

        for project_id in parse_examples(
            row.get("example_project_ids")
        ):
            if project_id not in record["example_ids"]:
                record["example_ids"].append(project_id)

    for row in challenge_df.to_dict("records"):
        original = str(row["phrase"]).strip()
        phrase = normalize(original)

        record = records[phrase]
        record["variants"].add(original)
        record["ngram_sizes"].add(
            int(row["ngram_size"])
        )

        # Challenge rows also contain the global count.
        record["global_count"] = max(
            record["global_count"],
            int(row["global_count"]),
        )

        challenge = str(row["challenge"])
        count = int(row["challenge_count"])

        record["challenges"][challenge] = max(
            record["challenges"].get(challenge, 0),
            count,
        )

        for project_id in parse_examples(
            row.get("example_project_ids")
        ):
            if project_id not in record["example_ids"]:
                record["example_ids"].append(project_id)

    return records


def main():
    records = load_candidates()
    rows = []

    for phrase, record in records.items():
        reason = reject_reason(phrase)
        category = classify(phrase)

        # Explicitly recognized concepts get a provisional
        # acceptance decision. Everything else is reviewed
        # unless a rejection rule applies.
        if reason:
            decision = "reject"
        elif category != "unclassified":
            decision = "accept"
        else:
            decision = "review"

        challenge_counts = sorted(
            record["challenges"].items(),
            key=lambda item: (-item[1], item[0]),
        )

        rows.append({
            "keyword": phrase,
            "category": category,
            "decision": decision,
            "global_project_count": record["global_count"],
            "challenge_count": len(challenge_counts),
            "top_challenges": json.dumps(
                challenge_counts[:5],
                ensure_ascii=False,
            ),
            "variants": json.dumps(
                sorted(record["variants"]),
                ensure_ascii=False,
            ),
            "example_project_ids": json.dumps(
                record["example_ids"][:5],
                ensure_ascii=False,
            ),
            "rejection_reason": reason,
            "review_notes": "",
        })

    df = pd.DataFrame(rows)

    # Prioritize multiword concepts and frequently
    # occurring phrases, while retaining single words.
    df["word_count"] = df["keyword"].str.split().str.len()

    df = df.sort_values(
        ["decision", "word_count", "global_project_count"],
        ascending=[False, False, False],
    )

    df.to_csv(
        OUTPUT_DIR / "keyword_candidates.csv",
        index=False,
    )

    accepted = df[df["decision"] == "accept"]
    review = df[df["decision"] == "review"]
    rejected = df[df["decision"] == "reject"]

    accepted.to_csv(
        OUTPUT_DIR / "provisional_keywords.csv",
        index=False,
    )

    review.to_csv(
        OUTPUT_DIR / "needs_review.csv",
        index=False,
    )

    rejected.to_csv(
        OUTPUT_DIR / "rejected_candidates.csv",
        index=False,
    )

    print(f"Total candidates: {len(df):,}")
    print(f"Provisionally accepted: {len(accepted):,}")
    print(f"Needs review: {len(review):,}")
    print(f"Rejected: {len(rejected):,}")

    print("\nPROVISIONAL KEYWORDS")
    print(
        accepted[
            ["keyword", "category", "global_project_count"]
        ].sort_values(
            "global_project_count", ascending=False
        ).head(40).to_string(index=False)
    )

    print("\nOutput files:")
    for path in sorted(OUTPUT_DIR.glob("*.csv")):
        print(f"  {path}")


if __name__ == "__main__":
    main()
