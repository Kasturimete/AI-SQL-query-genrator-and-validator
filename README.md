# QueryLab: Natural Language to SQL

A local classroom demo that converts supported natural-language questions into SQL, validates the SQL, and runs it against a seeded SQLite college database.

## Run it

Requires Python 3.9 or later; no external packages are needed.

```powershell
python app.py
```

Open <http://127.0.0.1:8000>. On first launch the app creates `college.db` with related `Student`, `Course`, and `Enrollment` tables and sample rows. Stop the server with Ctrl+C.

## Included requirements

The six starter prompts generate and execute these queries:

1. Show all students.
2. List students in Computer Science.
3. Show each student with their enrolled courses and grade.
4. Count students enrolled in each course.
5. Find students older than 20.
6. Calculate the average grade for each course.

The natural-language mapper is intentionally transparent and rule-based, so the demo works offline and produces repeatable answers. The editable SQL field lets a learner inspect and modify the generated query. Supported natural-language patterns are listed above; unsupported requests are rejected with a suggestion to use a starter prompt.

## Validation and safety

- Only one `SELECT` statement is accepted.
- Write/administrative SQL keywords are rejected.
- SQLite `EXPLAIN` checks syntax and referenced columns before execution.
- A SQLite authorizer allows reads from only the three sample tables and denies all other actions.
- The query connection opens the database in read-only mode; displayed results are capped at 200 rows.

## Incorrect query and correction

**Incorrect:**

```sql
SELECT s.name, c.course_name
FROM Student s
JOIN Course c ON s.student_id = c.course_id;
```

This joins unrelated identifiers (`student_id` and `course_id`), so it can pair a student and course just because their numeric IDs happen to match. It also skips the table that stores enrollment relationships.

**Correct:**

```sql
SELECT s.name, c.course_name
FROM Enrollment e
JOIN Student s ON s.student_id = e.student_id
JOIN Course c ON c.course_id = e.course_id
ORDER BY s.name, c.course_name;
```

The corrected query follows both foreign keys through `Enrollment`, returning only actual student-course registrations.
