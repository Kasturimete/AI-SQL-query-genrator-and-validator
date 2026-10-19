"""Local NL-to-SQL classroom demo. Uses only Python's standard library."""
from __future__ import annotations

import json
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "college.db"
PORT = 8000

SAMPLES = [
    {"question": "Show all students", "sql": "SELECT student_id, name, age, department FROM Student ORDER BY student_id;"},
    {"question": "List the names of students in Computer Science", "sql": "SELECT name FROM Student WHERE department = 'Computer Science' ORDER BY name;"},
    {"question": "Show each student with the courses they enrolled in", "sql": "SELECT s.name AS student, c.course_name AS course, e.grade FROM Enrollment e JOIN Student s ON s.student_id = e.student_id JOIN Course c ON c.course_id = e.course_id ORDER BY s.name, c.course_name;"},
    {"question": "How many students are enrolled in each course?", "sql": "SELECT c.course_name, COUNT(e.student_id) AS student_count FROM Course c LEFT JOIN Enrollment e ON e.course_id = c.course_id GROUP BY c.course_id, c.course_name ORDER BY c.course_name;"},
    {"question": "Find students older than 20", "sql": "SELECT name, age, department FROM Student WHERE age > 20 ORDER BY age DESC, name;"},
    {"question": "Show the average grade for each course", "sql": "SELECT c.course_name, ROUND(AVG(e.grade), 1) AS average_grade FROM Course c JOIN Enrollment e ON e.course_id = c.course_id GROUP BY c.course_id, c.course_name ORDER BY c.course_name;"},
]


def initialize_db() -> None:
    with sqlite3.connect(DB_PATH) as db:
        db.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS Student (
            student_id INTEGER PRIMARY KEY, name TEXT NOT NULL, age INTEGER NOT NULL,
            department TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS Course (
            course_id INTEGER PRIMARY KEY, course_name TEXT NOT NULL UNIQUE,
            credits INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS Enrollment (
            student_id INTEGER NOT NULL REFERENCES Student(student_id),
            course_id INTEGER NOT NULL REFERENCES Course(course_id),
            grade REAL, PRIMARY KEY (student_id, course_id)
        );
        """)
        if db.execute("SELECT COUNT(*) FROM Student").fetchone()[0] == 0:
            db.executemany("INSERT INTO Student VALUES (?, ?, ?, ?)", [
                (1, "Aisha Khan", 20, "Computer Science"), (2, "Rohan Patel", 22, "Mathematics"),
                (3, "Mei Chen", 19, "Computer Science"), (4, "Daniel Kim", 21, "Physics"),
                (5, "Sara Ahmed", 23, "Mathematics"),
            ])
            db.executemany("INSERT INTO Course VALUES (?, ?, ?)", [
                (101, "Database Systems", 4), (102, "Linear Algebra", 3),
                (103, "Web Development", 3), (104, "Physics I", 4),
            ])
            db.executemany("INSERT INTO Enrollment VALUES (?, ?, ?)", [
                (1, 101, 91), (1, 103, 88), (2, 102, 85), (2, 101, 79),
                (3, 101, 95), (3, 103, 92), (4, 104, 81), (5, 102, 90),
            ])


def generate_sql(question: str) -> str:
    """Transparent rule-based NL-to-SQL mapping for the classroom examples."""
    q = " ".join(question.lower().strip().split())
    if not q:
        raise ValueError("Enter a question first.")
    if any(term in q for term in ("average grade", "average score", "avg grade")):
        return SAMPLES[5]["sql"]
    if any(term in q for term in ("how many", "count")) and "course" in q:
        return SAMPLES[3]["sql"]
    if any(term in q for term in ("enrolled in", "enrollments", "student with the course", "student and course")):
        return SAMPLES[2]["sql"]
    department = re.search(r"(?:in|from)\s+(computer science|mathematics|physics)\b", q)
    if department:
        value = {"computer science": "Computer Science", "mathematics": "Mathematics", "physics": "Physics"}[department.group(1)]
        return "SELECT name FROM Student WHERE department = " + sql_literal(value) + " ORDER BY name;"
    age = re.search(r"(?:older than|over|above)\s+(\d{1,2})", q)
    if age:
        return f"SELECT name, age, department FROM Student WHERE age > {int(age.group(1))} ORDER BY age DESC, name;"
    if "student" in q and any(word in q for word in ("all", "list", "show", "every")):
        return SAMPLES[0]["sql"]
    raise ValueError("I couldn't map that request to a supported query. Try one of the examples below.")


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex|trigger|transaction|commit|rollback)\b", re.I)
ALLOWED_TABLES = {"student", "course", "enrollment"}


def validate_and_run(sql: str) -> dict:
    normalized = sql.strip()
    if not normalized:
        raise ValueError("SQL query is empty.")
    if not re.match(r"^select\b", normalized, re.I):
        raise ValueError("Only SELECT queries are allowed.")
    # Allow a single optional trailing semicolon, never multiple statements.
    body = normalized[:-1] if normalized.endswith(";") else normalized
    if ";" in body:
        raise ValueError("Only one SQL statement is allowed.")
    if FORBIDDEN.search(body):
        raise ValueError("The query contains a blocked SQL command.")
    # The SQLite authorizer is the final guard; the read-only URI independently prevents writes.
    connection = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    allowed = {"select", "read", "function"}
    def authorize(action, arg1, arg2, database, source):
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION):
            if action == sqlite3.SQLITE_READ and arg1.lower() not in ALLOWED_TABLES and arg1.lower() != "sqlite_master":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
    connection.set_authorizer(authorize)
    try:
        # Prepare first to validate syntax and table/column references without executing side effects.
        connection.execute("EXPLAIN " + body)
        cursor = connection.execute(body)
        columns = [d[0] for d in cursor.description or []]
        rows = [dict(row) for row in cursor.fetchmany(200)]
        return {"columns": columns, "rows": rows, "row_count": len(rows)}
    finally:
        connection.close()


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict, content_type="application/json; charset=utf-8"):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if urlparse(self.path).path == "/api/examples":
            self._send(200, {"examples": SAMPLES})
            return
        if urlparse(self.path).path in ("/", "/index.html"):
            page = (ROOT / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(page)
            return
        self._send(404, {"error": "Not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/api/query":
            self._send(404, {"error": "Not found"})
            return
        try:
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            question = str(payload.get("question", ""))[:500]
            sql = str(payload.get("sql", ""))[:2000] or generate_sql(question)
            result = validate_and_run(sql)
            self._send(200, {"question": question, "sql": sql, "validated": True, **result})
        except (ValueError, sqlite3.Error, json.JSONDecodeError) as exc:
            self._send(400, {"error": str(exc)})

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))


if __name__ == "__main__":
    initialize_db()
    print(f"Student/Course SQL demo running at http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
