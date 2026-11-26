
import json
import re
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import (
    CountVectorizer,
    ENGLISH_STOP_WORDS,
)

DB_PATH = Path("spaceapps_2026.sqlite")
OUT_DIR = Path("vocabulary_v2")
OUT_DIR.mkdir(exist_ok=True)

MIN_DF = 8
MAX_FEATURES = 150_000
TOP_N = 100
EXAMPLE_COUNT = 3

# Generic terms unlikely to help distinguish projects.
# Retain scientific words such as "space", "earth", and "data"
# in the underlying text; remove only selected generic terms.
STOP_WORDS = sorted(ENGLISH_STOP_WORDS | {
    "project", "projects", "team", "teams",
    "using", "used", "uses", "based",
    "user", "users", "provides", "provide",
    "solution", "solutions",
})

# Repeated headings found in project submission templates.
# Only remove headings, not the content following them.
HEADING_RE = re.compile(
    r"(?im)^\s*(?:"
    r"intended impact|"
    r"project description|"
    r"project details|"
    r"how it works|"
    r"tools and technologies|"
    r"benefits|"
    r"future work"
    r")\s*:?\s*$"
)


def load_projects():
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query("""
            SELECT
                p.id,
                p.name,
                p.summary,
                p.details_text,
                t.challenge_title
            FROM projects p
            JOIN teams t ON t.id = p.team_id
            ORDER BY p.id
        """, conn)

    for col in ("name", "summary", "details_text"):
        df[col] = df[col].fillna("")

    def prepare(row):
        text = "\n".join([
            row["name"],
            row["summary"],
            row["details_text"],
        ])
        return HEADING_RE.sub(" ", text)

    df["text"] = df.apply(prepare, axis=1)
    return df


def make_vocabulary(df):
    vectorizer = CountVectorizer(
        lowercase=True,
        stop_words=STOP_WORDS,
        ngram_range=(1, 3),
        min_df=MIN_DF,
        max_df=0.85,
        max_features=MAX_FEATURES,
        binary=True,
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9-]{2,}\b",
        dtype=np.int32,
    )

    X = vectorizer.fit_transform(df["text"])
    phrases = vectorizer.get_feature_names_out()

    # Each row is a project; each column is a phrase.
    # Binary counts mean a project contributes at most once.
    global_df = np.asarray(X.sum(axis=0)).ravel()

    print(f"Projects: {X.shape[0]:,}")
    print(f"Candidate phrases: {X.shape[1]:,}")

    return X, phrases, global_df


def phrase_size(phrase):
    return len(phrase.split())


def sample_project_ids(X, indices, column, df):
    # Search only projects in the requested group.
    matching = X[indices, column].nonzero()[0]
    selected = indices[matching[:EXAMPLE_COUNT]]

    return json.dumps(
        df.iloc[selected]["id"].tolist(),
        ensure_ascii=False,
    )


def analyze_challenge(
    df, X, phrases, global_df, challenge, indices
):
    total = X.shape[0]
    n_inside = len(indices)
    n_outside = total - n_inside

    inside_df = np.asarray(
        X[indices].sum(axis=0)
    ).ravel()

    outside_df = global_df - inside_df

    # Smoothed probabilities avoid division by zero.
    p_inside = (inside_df + 0.5) / (n_inside + 1)
    p_outside = (outside_df + 0.5) / (n_outside + 1)

    # Positive values mean the phrase is more common
    # inside this challenge than outside it.
    enrichment = np.log2(p_inside / p_outside)

    rows = []

    for j, phrase in enumerate(phrases):
        if inside_df[j] < 5:
            continue

        rows.append({
            "challenge": challenge,
            "phrase": phrase,
            "ngram_size": phrase_size(phrase),
            "challenge_count": int(inside_df[j]),
            "global_count": int(global_df[j]),
            "challenge_fraction": float(
                inside_df[j] / n_inside
            ),
            "outside_fraction": float(
                outside_df[j] / n_outside
            ),
            "log2_enrichment": float(enrichment[j]),
            "column": j,
        })

    result = pd.DataFrame(rows)

    if result.empty:
        return result

    return result


def add_examples(ranked, X, indices, df):
    ranked = ranked.copy()

    ranked["example_project_ids"] = [
        sample_project_ids(
            X, indices, int(column), df
        )
        for column in ranked["column"]
    ]

    return ranked.drop(columns=["column"])


def main():
    df = load_projects()
    X, phrases, global_df = make_vocabulary(df)

    global_rows = []

    for size in (1, 2, 3):
        indices = [
            j for j, phrase in enumerate(phrases)
            if phrase_size(phrase) == size
        ]

        ranked = sorted(
            indices,
            key=lambda j: (-global_df[j], phrases[j])
        )[:TOP_N]

        for rank, j in enumerate(ranked, start=1):
            global_rows.append({
                "ngram_size": size,
                "rank": rank,
                "phrase": phrases[j],
                "project_count": int(global_df[j]),
                "project_fraction": float(
                    global_df[j] / len(df)
                ),
                "example_project_ids": sample_project_ids(
                    X, np.arange(len(df)), j, df
                ),
            })

    pd.DataFrame(global_rows).to_csv(
        OUT_DIR / "global_ngrams.csv",
        index=False,
    )

    all_challenge_rows = []

    for challenge, group in df.groupby("challenge_title"):
        indices = group.index.to_numpy()

        result = analyze_challenge(
            df, X, phrases, global_df, challenge, indices
        )

        if result.empty:
            continue

        for size in (1, 2, 3):
            subset = result[
                result["ngram_size"] == size
            ]

            # Most common phrases within the challenge.
            frequency = subset.sort_values(
                ["challenge_count", "phrase"],
                ascending=[False, True],
            ).head(TOP_N)

            # Distinctive phrases with a minimum prevalence
            # to avoid ranking extremely rare phrases first.
            enriched = subset[
                subset["challenge_count"] >= max(
                    10, int(len(indices) * 0.005)
                )
            ].sort_values(
                [
                    "log2_enrichment",
                    "challenge_count",
                    "phrase",
                ],
                ascending=[False, False, True],
            ).head(TOP_N)

            for ranking, selected in (
                ("frequency", frequency),
                ("enrichment", enriched),
            ):
                selected = add_examples(
                    selected, X, indices, df
                )
                selected.insert(1, "ranking", ranking)
                selected.insert(
                    2, "rank", range(1, len(selected) + 1)
                )
                all_challenge_rows.append(selected)

        print(
            f"{challenge}: {len(indices):,} projects, "
            f"{len(result):,} candidate phrases"
        )

    combined = pd.concat(
        all_challenge_rows, ignore_index=True
    )

    combined.to_csv(
        OUT_DIR / "challenge_ngrams.csv",
        index=False,
    )

    # Potential boilerplate: phrases occurring in at least
    # half of all projects. These deserve manual inspection.
    boilerplate = pd.DataFrame({
        "phrase": phrases,
        "project_count": global_df,
        "project_fraction": global_df / len(df),
    })

    boilerplate = boilerplate[
        boilerplate["project_fraction"] >= 0.50
    ].sort_values(
        "project_count", ascending=False
    )

    boilerplate.to_csv(
        OUT_DIR / "boilerplate_candidates.csv",
        index=False,
    )

    print("\nOutput files:")
    for path in sorted(OUT_DIR.glob("*.csv")):
        print(f"  {path} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
