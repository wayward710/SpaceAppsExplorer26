
import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import pandas as pd

XML_PATH = Path("thesaurus-SKOS.xml")
CANDIDATES_PATH = Path("keyword_review/keyword_candidates.csv")
OUTPUT_PATH = Path("keyword_review/nasa_thesaurus_matches.csv")

SKOS = "http://www.w3.org/2004/02/skos/core#"
SKM = "http://synaptica.net/skm/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

def tag(ns, name):
    return f"{{{ns}}}{name}"

def normalize(text):
    return re.sub(r"\s+", " ", str(text).casefold()).strip()

def load_thesaurus():
    concepts = {}

    for _, element in ET.iterparse(XML_PATH, events=("end",)):
        if element.tag != tag(SKOS, "Concept"):
            continue

        uri = element.get(tag(RDF, "about"))
        preferred = element.findtext(tag(SKOS, "prefLabel"))

        if uri and preferred:
            concepts[uri] = {
                "id": uri.removeprefix("#"),
                "label": preferred,
                "alternates": [
                    node.text
                    for node in element.findall(tag(SKOS, "altLabel"))
                    if node.text
                ],
                "use": [
                    node.get(tag(RDF, "resource"))
                    for node in element.findall(tag(SKM, "Use"))
                ],
                "broader": [
                    node.get(tag(RDF, "resource"))
                    for node in element.findall(tag(SKOS, "broader"))
                ],
            }

        element.clear()

    return concepts

def build_lookup(concepts):
    lookup = defaultdict(set)

    for uri, concept in concepts.items():
        # Nonpreferred entries redirect to authorized concepts.
        if concept["use"]:
            for target in concept["use"]:
                if target in concepts:
                    lookup[(normalize(concept["label"]), "use")].add(target)
            continue

        lookup[(normalize(concept["label"]), "preferred")].add(uri)

        for alt in concept["alternates"]:
            lookup[(normalize(alt), "alternate")].add(uri)

    return lookup

def main():
    concepts = load_thesaurus()
    lookup = build_lookup(concepts)
    candidates = pd.read_csv(CANDIDATES_PATH).fillna("")

    rows = []

    for candidate in candidates.to_dict("records"):
        phrase = normalize(candidate["keyword"])

        matches = []
        for match_type in ("preferred", "alternate", "use"):
            for uri in sorted(lookup.get((phrase, match_type), set())):
                concept = concepts[uri]
                matches.append({
                    "match_type": match_type,
                    "concept_id": concept["id"],
                    "preferred_label": concept["label"],
                    "broader_ids": [
                        ref.removeprefix("#")
                        for ref in concept["broader"]
                        if ref
                    ],
                })

        if not matches:
            status = "unmatched"
        elif len({m["concept_id"] for m in matches}) > 1:
            status = "ambiguous"
        else:
            status = matches[0]["match_type"]

        rows.append({
            "keyword": candidate["keyword"],
            "global_project_count": candidate["global_project_count"],
            "original_decision": candidate["decision"],
            "status": status,
            "matches": json.dumps(matches, ensure_ascii=False),
        })

    result = pd.DataFrame(rows)
    result.to_csv(OUTPUT_PATH, index=False)

    print(f"NASA concept records: {len(concepts):,}")
    print(f"Candidate phrases: {len(result):,}")
    print("\nMATCH STATUS")
    print(result["status"].value_counts().to_string())

    print("\nMOST COMMON MATCHED PHRASES")
    print(
        result[result["status"] != "unmatched"]
        .sort_values("global_project_count", ascending=False)
        [["keyword", "status", "global_project_count"]]
        .head(30)
        .to_string(index=False)
    )

    print(f"\nSaved: {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
