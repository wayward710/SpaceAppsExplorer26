
import json
import re
import sqlite3
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

RAW_DIR = Path("spaceapps_2026_raw")
MEMBERS_DIR = Path("spaceapps_2026_members")
DB_PATH = Path("spaceapps_2026.sqlite")


class HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip_depth += 1
        elif not self.skip_depth and tag in (
            "p", "div", "br", "li", "h1", "h2", "h3", "h4"
        ):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth and tag in (
            "p", "div", "li", "h1", "h2", "h3", "h4"
        ):
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)

    def text(self):
        return re.sub(r"\s+", " ", "".join(self.parts)).strip()


def clean_html(value):
    if not value:
        return ""

    parser = HTMLTextExtractor()
    parser.feed(str(value))
    return unescape(parser.text())


def as_text(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def create_schema(conn):
    conn.executescript("""
        PRAGMA foreign_keys = ON;

        CREATE TABLE teams (
            id TEXT PRIMARY KEY,
            title TEXT,
            slug TEXT,
            url TEXT,
            challenge_id TEXT,
            challenge_title TEXT,
            location_id TEXT,
            location_title TEXT,
            location_country TEXT,
            owner_id TEXT,
            submitted INTEGER NOT NULL
        );

        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL UNIQUE,
            name TEXT,
            summary TEXT,
            details_html TEXT,
            details_text TEXT,
            demo_link TEXT,
            project_link TEXT,
            ai_tools_usage TEXT,
            data_references TEXT,
            project_references TEXT,
            submitted_at TEXT,
            FOREIGN KEY(team_id) REFERENCES teams(id)
        );

        CREATE TABLE members (
            id TEXT PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            country TEXT
        );

        CREATE TABLE team_members (
            team_id TEXT NOT NULL,
            member_id TEXT NOT NULL,
            PRIMARY KEY(team_id, member_id),
            FOREIGN KEY(team_id) REFERENCES teams(id),
            FOREIGN KEY(member_id) REFERENCES members(id)
        );

        CREATE INDEX idx_teams_challenge
            ON teams(challenge_title);

        CREATE INDEX idx_teams_country
            ON teams(location_country);

        CREATE INDEX idx_members_name
            ON members(full_name);

        CREATE INDEX idx_members_country
            ON members(country);

        CREATE INDEX idx_team_members_member
            ON team_members(member_id);

        CREATE VIRTUAL TABLE project_fts USING fts5(
            name,
            summary,
            details_text,
            content='projects',
            content_rowid='rowid',
            tokenize='unicode61 remove_diacritics 2'
        );

        CREATE TRIGGER projects_ai AFTER INSERT ON projects BEGIN
            INSERT INTO project_fts(
                rowid, name, summary, details_text
            )
            VALUES (
                new.rowid, new.name, new.summary, new.details_text
            );
        END;
    """)


def import_projects(conn):
    count = 0

    for path in sorted(RAW_DIR.glob("teams_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))

        for edge in data["data"]["teams"]["edges"]:
            team = edge["node"]

            if not team.get("projectSubmitted"):
                continue

            project = team.get("projectDetails") or {}
            challenge = team.get("challengeDetails") or {}
            location = team.get("locationDetails") or {}
            team_meta = team.get("meta") or {}
            location_meta = location.get("meta") or {}

            team_id = team["id"]
            project_id = project.get("id")

            if not project_id:
                raise ValueError(f"Missing project ID: {team_id}")

            conn.execute("""
                INSERT INTO teams VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                team_id,
                team.get("title"),
                team_meta.get("slug"),
                team_meta.get("relativeUrl"),
                challenge.get("id"),
                challenge.get("title"),
                location.get("id"),
                location.get("displayName") or location.get("title"),
                location.get("country"),
                team.get("owner"),
                1,
            ))

            conn.execute("""
                INSERT INTO projects VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, (
                project_id,
                team_id,
                project.get("name"),
                as_text(project.get("summary")),
                as_text(project.get("details")),
                clean_html(project.get("details")),
                project.get("demoLink"),
                project.get("projectLink"),
                as_text(project.get("aiToolsUsage")),
                as_text(project.get("dataReferences")),
                as_text(project.get("projectReferences")),
                project.get("submittedAt"),
            ))

            count += 1

        print(f"Imported {path.name}: {count:,} projects", end="\r")

    print(f"\nImported {count:,} submitted projects.")
    return count


def import_members(conn):
    count = 0
    relationships = 0

    for path in sorted(MEMBERS_DIR.glob("*.json")):
        result = json.loads(path.read_text(encoding="utf-8"))

        if result.get("status") != "ok":
            continue

        team_id = result.get("id")

        for member in result.get("members", []):
            member_id = member.get("user_id")

            if not member_id:
                continue

            conn.execute("""
                INSERT INTO members (
                    id, full_name, username, country
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    full_name=excluded.full_name,
                    username=excluded.username,
                    country=excluded.country
            """, (
                member_id,
                member.get("name"),
                member.get("username"),
                member.get("country"),
            ))

            conn.execute("""
                INSERT OR IGNORE INTO team_members
                    (team_id, member_id)
                VALUES (?, ?)
            """, (team_id, member_id))

            count += 1
            relationships += 1

    print(f"Imported {count:,} membership records.")
    print(f"Created {relationships:,} membership relationships.")


def main():
    if DB_PATH.exists():
        raise SystemExit(
            f"{DB_PATH} already exists. "
            "Rename or delete it before rebuilding."
        )

    conn = sqlite3.connect(DB_PATH)

    try:
        create_schema(conn)
        import_projects(conn)
        import_members(conn)

        conn.commit()

        print("\nDATABASE COUNTS")
        for table in (
            "teams", "projects", "members",
            "team_members", "project_fts"
        ):
            count = conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            print(f"{table}: {count:,}")

        print("\nFTS5 TEST")
        results = conn.execute("""
            SELECT p.name, snippet(
                project_fts, 2, '[', ']', '...', 12
            )
            FROM project_fts
            JOIN projects p ON p.rowid = project_fts.rowid
            WHERE project_fts MATCH ?
            LIMIT 5
        """, ("aquifer",)).fetchall()

        for name, snippet in results:
            print(f"{name}: {snippet}")

    except Exception:
        conn.rollback()
        conn.close()
        DB_PATH.unlink(missing_ok=True)
        raise
    else:
        conn.close()


if __name__ == "__main__":
    main()
