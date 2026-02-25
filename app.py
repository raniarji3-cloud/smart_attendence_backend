from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
from datetime import datetime

app = Flask(__name__)
CORS(app)

DATABASE = "database.db"

# -----------------------------
# Database Connection
# -----------------------------
def connect_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# -----------------------------
# Create Tables Automatically
# -----------------------------
def create_tables():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        roll_number TEXT UNIQUE NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        status TEXT CHECK(status IN ('Present','Absent')) NOT NULL,
        sync_status INTEGER DEFAULT 0,
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
    )
    """)

    conn.commit()
    conn.close()

create_tables()


# -----------------------------
# Home Route
# -----------------------------
@app.route("/")
def home():
    return "Smart Attendance Backend Running 🚀"


# -----------------------------
# Add Student
# -----------------------------
@app.route("/add_student", methods=["POST"])
def add_student():
    data = request.get_json()

    if not data or "name" not in data or "roll_number" not in data:
        return jsonify({"error": "Invalid input"}), 400

    name = data["name"]
    roll_number = data["roll_number"]

    conn = connect_db()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO students (name, roll_number) VALUES (?, ?)",
            (name, roll_number)
        )
        conn.commit()
        student_id = cursor.lastrowid
        return jsonify({
            "message": "Student added successfully",
            "student_id": student_id
        })
    except sqlite3.IntegrityError:
        return jsonify({"error": "Roll number already exists"}), 400
    finally:
        conn.close()


# -----------------------------
# Get All Students
# -----------------------------
@app.route("/students", methods=["GET"])
def get_students():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM students")
    students = cursor.fetchall()

    result = []
    for s in students:
        result.append(dict(s))

    conn.close()
    return jsonify(result)


# -----------------------------
# Mark Attendance
# -----------------------------
@app.route("/mark_attendance", methods=["POST"])
def mark_attendance():
    data = request.get_json()

    if not data or "student_id" not in data or "status" not in data:
        return jsonify({"error": "Invalid input"}), 400

    student_id = data["student_id"]
    status = data["status"]

    if status not in ["Present", "Absent"]:
        return jsonify({"error": "Status must be Present or Absent"}), 400

    today = datetime.now().strftime("%Y-%m-%d")

    conn = connect_db()
    cursor = conn.cursor()

    
    # ✅ NEW: Check if student exists
    cursor.execute("SELECT id FROM students WHERE id=?", (student_id,))
    if not cursor.fetchone():
        conn.close()
        return jsonify({"error": "Student not found"}), 404


    # Check duplicate attendance
    cursor.execute(
        "SELECT * FROM attendance WHERE student_id=? AND date=?",
        (student_id, today)
    )
    existing = cursor.fetchone()

    if existing:
        conn.close()
        return jsonify({"message": "Attendance already marked today"})

    cursor.execute(
        "INSERT INTO attendance (student_id, date, status) VALUES (?, ?, ?)",
        (student_id, today, status)
    )
    conn.commit()
    conn.close()

    return jsonify({"message": "Attendance marked successfully"})


# -----------------------------
# Get All Attendance
# -----------------------------
@app.route("/attendance", methods=["GET"])
def get_attendance():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT attendance.id, students.name, students.roll_number,
               attendance.date, attendance.status, attendance.sync_status
        FROM attendance
        JOIN students ON attendance.student_id = students.id
    """)

    records = cursor.fetchall()
    result = [dict(r) for r in records]

    conn.close()
    return jsonify(result)


# -----------------------------
# Daily Report
# -----------------------------
@app.route("/report", methods=["GET"])
def report():
    date = request.args.get("date")

    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM students")
    total_students = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM attendance WHERE date=? AND status='Present'",
        (date,)
    )
    present = cursor.fetchone()[0]

    absent = total_students - present

    conn.close()

    return jsonify({
        "date": date,
        "total_students": total_students,
        "present": present,
        "absent": absent
    })
    
    
# -----------------------------
# Sync (Demo Version)
# -----------------------------
@app.route("/sync", methods=["POST"])
def sync():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM attendance WHERE sync_status=0")
    unsynced = cursor.fetchall()

    for record in unsynced:
        cursor.execute(
            "UPDATE attendance SET sync_status=1 WHERE id=?",
            (record["id"],)
        )

    conn.commit()
    conn.close()

    return jsonify({
        "message": "Data synced successfully",
        "records_synced": len(unsynced)
    })


# -----------------------------
# Stats Route (PLACE IT HERE)
# -----------------------------
@app.route("/stats")
def stats():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM students")
    total_students = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM attendance")
    total_attendance = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM attendance WHERE sync_status=0")
    unsynced = cursor.fetchone()[0]

    conn.close()

    return jsonify({
        "total_students": total_students,
        "total_attendance_records": total_attendance,
        "unsynced_records": unsynced
    })




# -----------------------------
# Run Server
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
