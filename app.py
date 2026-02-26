from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
from datetime import datetime
from deepface import DeepFace
import os
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt_identity
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
CORS(app)

DATABASE = "database.db"
app.config["JWT_SECRET_KEY"] = "super-secret-key"
jwt = JWTManager(app)

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
        roll_number TEXT UNIQUE NOT NULL,
        image_path TEXT
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
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
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
@jwt_required()
def add_student():
    data = request.get_json()

    if not data or "name" not in data or "roll_number" not in data:
        return jsonify({"error": "Invalid input"}), 400

    name = data["name"]
    roll_number = data["roll_number"]

    conn = connect_db()
    cursor = conn.cursor()
    
    image_path = data.get("image_path", None)

    try:
        cursor.execute(
            "INSERT INTO students (name, roll_number, image_path) VALUES (?, ?, ?)",
            (name, roll_number, image_path)
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
@jwt_required()
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
@jwt_required()
def mark_attendance():
    data = request.get_json()

    if not data or "student_id" not in data or "status" not in data:
        return jsonify({"error": "Invalid input"}), 400

    student_id = int(data["student_id"])
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

@app.route("/verify_attendance", methods=["POST"])
@jwt_required()
def verify_attendance():
    try:
        student_id = request.form.get("student_id")
        image = request.files.get("image")

        if not student_id or not image:
            return jsonify({"error": "Missing data"}), 400
        
        student_id = int(student_id)

        conn = connect_db()
        cursor = conn.cursor()

        cursor.execute("SELECT image_path FROM students WHERE id=?", (student_id,))
        student = cursor.fetchone()

        if not student:
            conn.close()
            return jsonify({"error": "Student not found"}), 404

        stored_image_path = student["image_path"]

        if not stored_image_path or not os.path.exists(stored_image_path):
            conn.close()
            return jsonify({"error": "Stored image not found"}), 404

        import uuid
        temp_path = f"temp_{uuid.uuid4().hex}.jpg"
        image.save(temp_path)

        try:
            result = DeepFace.verify(
                img1_path=temp_path,
                img2_path=stored_image_path,
                enforce_detection=False
            )
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        if result["verified"]:
            today = datetime.now().strftime("%Y-%m-%d")

            cursor.execute(
                "SELECT * FROM attendance WHERE student_id=? AND date=?",
                (student_id, today)
            )
            if cursor.fetchone():
                conn.close()
                return jsonify({"message": "Attendance already marked today"})

            cursor.execute(
                "INSERT INTO attendance (student_id, date, status) VALUES (?, ?, ?)",
                (student_id, today, "Present")
            )

            conn.commit()
            conn.close()

            return jsonify({"message": "Face verified. Attendance marked."})
        else:
            conn.close()
            return jsonify({"message": "Face not matched"})

    except Exception as e:
        return jsonify({"error": str(e)})
    
# -----------------------------
# Get All Attendance
# -----------------------------
@app.route("/attendance", methods=["GET"])
@jwt_required()
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
@jwt_required()
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
@jwt_required()
def sync():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM attendance WHERE sync_status=0")
    unsynced = cursor.fetchall()

    cursor.execute("UPDATE attendance SET sync_status=1 WHERE sync_status=0")

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
@jwt_required()
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
    
@app.route("/register_admin", methods=["POST"])
def register_admin():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400

    hashed_password = generate_password_hash(password)

    conn = connect_db()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO admins (username, password) VALUES (?, ?)",
            (username, hashed_password)
        )
        conn.commit()
        return jsonify({"message": "Admin registered successfully"})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username already exists"}), 400
    finally:
        conn.close()
        
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400

    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM admins WHERE username=?",
        (username,)
    )
    admin = cursor.fetchone()
    conn.close()

    if not admin:
        return jsonify({"error": "Invalid credentials"}), 401

    if not check_password_hash(admin["password"], password):
        return jsonify({"error": "Invalid credentials"}), 401

    access_token = create_access_token(identity=username)
    return jsonify(access_token=access_token)
    
# -----------------------------
# Run Server
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
