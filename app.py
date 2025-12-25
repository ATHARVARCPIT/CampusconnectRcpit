from flask import Flask, request, jsonify, send_from_directory, Response
import os
import sqlite3
import json
import io
import csv
from datetime import datetime

app = Flask(__name__, static_folder='')

# --- Database Configuration ---
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
DB_PATH = os.path.join(DATA_DIR, 'app_data.db')
LOG_FILE = os.path.join(DATA_DIR, 'logs.json')

# Dummy data for initialization (Now stored in DB)
INITIAL_COURSES = [
    (1, 'Data Structures', 'Learn fundamental data structures and algorithms', 'Prof. Kaminee Patil'),
    (2, 'Open Electives', 'Explore various elective subjects', 'Dr. Pradip Patil'),
    (3, 'Economic and Finance Management', 'Understanding economics and financial management', 'Dr. Pankaj Bavisker'),
    (4, 'Operating System', 'Core concepts of operating systems', 'Prof. Priyanka Lanjewar')
]
INITIAL_USERS = [
    # Students
    ('student@rc.edu', '123', 'student', 'Kanchan Patil'),
    
    # Faculties
    ('kaminee@rc.edu', '12345', 'faculty', 'Prof. Kaminee Patil', [1]), # Assigned Course IDs
    ('pradip@rc.edu', '12345', 'faculty', 'Dr. Pradip Patil', [2]),
    ('pankajb@rc.edu', '12345', 'faculty', 'Dr. Pankaj Bavisker', [3]),
    ('priyanka@rc.edu', '12345', 'faculty', 'Prof. Priyanka Lanjewar', [4])
]

# --- Database Functions ---

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row # Allows accessing columns by name
    return conn

def init_db():
    ensure_dirs()
    conn = get_db()
    cursor = conn.cursor()

    # 1. Users Table (Stores Faculty and Students)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            name TEXT,
            subjects TEXT -- JSON string of course IDs for faculty
        );
    """)

    # 2. Courses Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            faculty TEXT
        );
    """)

    # 3. Content Table (FIX: ADDED 'url TEXT' COLUMN)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            courseId INTEGER,
            facultyEmail TEXT,
            title TEXT,
            type TEXT,
            description TEXT,
            file_path TEXT,
            url TEXT,
            created_at TEXT
        );
    """)

    # 4. Quizzes Table (Stores Quiz structure)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            courseId INTEGER,
            title TEXT NOT NULL,
            questions TEXT, -- JSON string of questions
            createdBy TEXT,
            createdDate TEXT
        );
    """)

    # 5. Quiz Results Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS quiz_results (
            quizId INTEGER,
            studentEmail TEXT,
            score INTEGER,
            completedDate TEXT,
            answers TEXT,
            PRIMARY KEY (quizId, studentEmail) -- Prevents duplicate submissions
        );
    """)

    # 6. Course Enrollments Table (Explicitly links students to all courses)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS course_enrollments (
            studentEmail TEXT,
            courseId INTEGER,
            PRIMARY KEY (studentEmail, courseId)
        );
    """)

    # Populate Initial Data if tables are empty

    # Users
    if cursor.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0:
        for email, password, role, name, *subjects in INITIAL_USERS:
            # Normalize and store emails in lowercase without surrounding whitespace
            email_clean = email.strip().lower()
            subjects_json = json.dumps(subjects[0]) if subjects else '[]'
            cursor.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                (email_clean, password, role, name, subjects_json)
            )
        
        # Enroll the demo student in all initial courses (use normalized student email)
        student_email = 'student@rc.edu'.strip().lower()
        for course_id, _, _, _ in INITIAL_COURSES:
            cursor.execute(
                "INSERT INTO course_enrollments VALUES (?, ?)",
                (student_email, course_id)
            )
        
    # Courses
    if cursor.execute('SELECT COUNT(*) FROM courses').fetchone()[0] == 0:
        for id, name, desc, faculty in INITIAL_COURSES:
            cursor.execute(
                "INSERT INTO courses (id, name, description, faculty) VALUES (?, ?, ?, ?)",
                (id, name, desc, faculty)
            )

    conn.commit()
    conn.close()

def ensure_dirs():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def log_event(event_type, details):
    ensure_dirs()
    entry = {
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'event': event_type,
        'details': details
    }
    # Simplified logging (only appends new log)
    logs = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                logs = json.load(f)
        except Exception:
            logs = []
    logs.append(entry)
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(logs, f, indent=2)

def faculty_dir(faculty_email):
    # sanitize faculty folder name
    safe = faculty_email.replace('@', '_at_').replace('.', '_')
    path = os.path.join(DATA_DIR, safe)
    if not os.path.exists(path):
        os.makedirs(path)
    return path

# --- Routes for Student Management ---

@app.route('/api/faculty/<faculty_email>/students', methods=['POST'])
def add_student(faculty_email):
    """Register a new student and enroll them in all current courses."""
    payload = request.get_json(force=True)
    name = payload.get('name')
    email = payload.get('email')
    password = payload.get('password', '123')
    
    if not name or not email or not password:
        return jsonify({'error': 'Missing name, email, or password'}), 400

    # Normalize email before inserting/enrolling
    email_clean = email.strip().lower()

    conn = get_db()
    try:
        # 1. Add student to users table (store normalized email)
        conn.execute(
            "INSERT INTO users VALUES (?, ?, 'student', ?, '[]')",
            (email_clean, password, name)
        )
        
        # 2. Enroll student in all existing courses
        courses_to_enroll = conn.execute("SELECT id FROM courses").fetchall()
        for course in courses_to_enroll:
            conn.execute(
                "INSERT INTO course_enrollments VALUES (?, ?)",
                (email_clean, course['id'])
            )

        conn.commit()
        log_event('add_student', {'faculty': faculty_email, 'student': email_clean})
        return jsonify({'status': 'ok'}), 201
    except sqlite3.IntegrityError:
        return jsonify({'error': 'User with this email already exists'}), 409
    finally:
        conn.close()

@app.route('/api/students', methods=['GET'])
def get_all_students():
    """Return all students for the faculty dashboard student count."""
    conn = get_db()
    students = conn.execute("SELECT email, name FROM users WHERE role = 'student'").fetchall()
    conn.close()
    return jsonify({'students': [dict(s) for s in students]})

# --- Enrollment/Course Management ---

@app.route('/api/course/<int:course_id>/enrollments', methods=['GET'])
def get_course_enrollments(course_id):
    """Return a list of students enrolled in a specific course."""
    conn = get_db()
    students = conn.execute("""
        SELECT u.name, u.email
        FROM users u
        JOIN course_enrollments ce ON u.email = ce.studentEmail
        WHERE ce.courseId = ?
        ORDER BY u.name
    """, (course_id,)).fetchall()
    conn.close()
    return jsonify({'courseId': course_id, 'enrollments': [dict(s) for s in students]})

# --- Authentication ---

@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    payload = request.get_json(force=True)
    email = payload.get('email')
    password = payload.get('password')
    # Basic validation
    if not email or not password:
        return jsonify({'error': 'missing credentials'}), 400

    # Normalize email so comparisons are consistent
    email_clean = email.strip().lower()
    password_clean = password.strip()

    conn = get_db()
    user_row = conn.execute("SELECT email, password, role, name, subjects FROM users WHERE email = ?", (email_clean,)).fetchone()
    conn.close()

    if user_row and user_row['password'] == password_clean:
        user = dict(user_row)
        # ensure subjects is a list
        try:
            user['subjects'] = json.loads(user['subjects']) if user['subjects'] else []
        except Exception:
            user['subjects'] = []
        del user['password'] # Don't send password back
        return jsonify({'status': 'ok', 'user': user})

    return jsonify({'error': 'invalid credentials'}), 401

# --- Content Management ---

@app.route('/api/faculty/<faculty_email>/content', methods=['POST'])
def add_content(faculty_email):
    d = faculty_dir(faculty_email)
    
    file_path_for_db = ''
    content_url = ''
    
    # 1. Check for file upload first (multipart/form-data)
    if request.files and 'file' in request.files:
        file = request.files['file']
        
        # Access data from request.form for fields sent with the file
        title = request.form.get('title', file.filename)
        content_type = request.form.get('type', '')
        description = request.form.get('description', '')
        courseId = request.form.get('courseId', '')
        content_url = request.form.get('url', '') # NEW: Get URL from form data
        
        if not title or not courseId:
             return jsonify({'error': 'Missing title or courseId in form data'}), 400

        # Save file
        safe_filename = f"{int(datetime.utcnow().timestamp())}_{file.filename}"
        save_path = os.path.join(d, safe_filename)
        file.save(save_path)
        
        # Store file path relative to the DATA_DIR in the DB
        file_path_for_db = os.path.join(os.path.basename(d), safe_filename)
        
    # 2. Handle JSON payload (for URL-only or text-only content)
    else:
        payload = request.get_json(force=True)
        if not payload or 'title' not in payload or 'courseId' not in payload:
            return jsonify({'error': 'missing title or courseId in JSON payload'}), 400
        
        title = payload.get('title')
        content_type = payload.get('type', '')
        description = payload.get('description', '')
        courseId = payload.get('courseId')
        content_url = payload.get('url', '') # NEW: Get URL from JSON payload

        if not title:
            return jsonify({'error': 'Missing content title'}), 400

    conn = get_db()
    try:
        # FIX: Added 'url' column to the INSERT statement
        conn.execute(
            "INSERT INTO content (courseId, facultyEmail, title, type, description, file_path, url, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (courseId, faculty_email, title, content_type, description, file_path_for_db, content_url, datetime.utcnow().isoformat() + 'Z')
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        log_event('add_content_error', {'faculty': faculty_email, 'error': str(e), 'payload_data': request.get_data().decode()})
        return jsonify({'error': f'Database error during insertion: {e}'}), 500
    finally:
        conn.close()

    log_event('add_content', {'faculty': faculty_email, 'title': title, 'file': file_path_for_db or content_url})
    return jsonify({'status': 'ok'}), 201

@app.route('/api/faculty/<faculty_email>/content', methods=['GET'])
def get_faculty_content(faculty_email):
    """Return content uploaded by a specific faculty member."""
    conn = get_db()
    # FIX: Select all columns including 'url'
    items = conn.execute("SELECT id, courseId, facultyEmail, title, type, description, file_path, url, created_at FROM content WHERE facultyEmail = ?", (faculty_email,)).fetchall()
    conn.close()
    
    formatted_items = []
    for r in items:
        item = dict(r)
        
        # Set file_url for uploaded files
        if item.get('file_path'):
            parts = item['file_path'].split(os.sep)
            faculty_folder = parts[0]
            filename = parts[1]
            item['file_url'] = f"/files/{faculty_folder}/{filename}"
        else:
            item['file_url'] = ''
        
        # Explicitly include the URL field
        item['url'] = item.get('url') if item.get('url') else ''

        formatted_items.append(item)
        
    return jsonify({'faculty': faculty_email, 'content': formatted_items})

@app.route('/api/content', methods=['GET'])
def all_content():
    """Return all content for students."""
    conn = get_db()
    # FIX: Select all columns including 'url'
    items = conn.execute("SELECT id, courseId, facultyEmail, title, type, description, file_path, url, created_at FROM content").fetchall()
    conn.close()

    formatted_items = []
    for r in items:
        item = dict(r)
        
        # Set file_url for uploaded files
        if item.get('file_path'):
            parts = item['file_path'].split(os.sep)
            faculty_folder = parts[0]
            filename = parts[1]
            item['file_url'] = f"/files/{faculty_folder}/{filename}"
            item['faculty_folder'] = faculty_folder
        else:
            item['file_url'] = ''
        
        # Explicitly include the URL field
        item['url'] = item.get('url') if item.get('url') else ''
        
        formatted_items.append(item)
        
    return jsonify({'content': formatted_items})


@app.route('/files/<faculty_folder>/<path:filename>', methods=['GET'])
def serve_uploaded_file(faculty_folder, filename):
    # serve files saved under data/<faculty_folder>/
    folder_path = os.path.join(DATA_DIR, faculty_folder)
    
    # Check if file exists in the database content table as well for security
    conn = get_db()
    db_path = os.path.join(faculty_folder, filename) 
    exists = conn.execute("SELECT 1 FROM content WHERE file_path = ?", (db_path,)).fetchone()
    conn.close()

    if exists and os.path.exists(os.path.join(folder_path, filename)):
        return send_from_directory(folder_path, filename)
    
    return jsonify({'error': 'file not found or unauthorized'}), 404

# --- Quizzes and Results ---

@app.route('/api/quizzes', methods=['GET'])
def get_quizzes():
    conn = get_db()
    quizzes = conn.execute("SELECT id, courseId, title, questions, createdBy, createdDate FROM quizzes").fetchall()
    conn.close()

    formatted_quizzes = []
    for q in quizzes:
        quiz = dict(q)
        # Questions are stored as JSON string, must be parsed
        quiz['questions'] = json.loads(quiz['questions']) if quiz['questions'] else []
        formatted_quizzes.append(quiz)

    return jsonify({'quizzes': formatted_quizzes})


@app.route('/api/quizzes', methods=['POST'])
def create_quiz():
    payload = request.get_json(force=True)
    if not payload or 'title' not in payload or 'questions' not in payload:
        return jsonify({'error': 'missing title or questions'}), 400
    
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO quizzes (courseId, title, questions, createdBy, createdDate) VALUES (?, ?, ?, ?, ?)",
            (payload.get('courseId'), payload.get('title'), json.dumps(payload.get('questions')), payload.get('createdBy'), datetime.utcnow().isoformat() + 'Z')
        )
        quiz_id = cursor.lastrowid
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'Failed to create quiz: {e}'}), 500
    finally:
        conn.close()

    log_event('create_quiz', {'createdBy': payload.get('createdBy'), 'quizId': quiz_id})
    return jsonify({'status': 'ok', 'quiz': {'id': quiz_id, **payload}}), 201

@app.route('/api/quiz_results', methods=['POST'])
def add_quiz_result():
    payload = request.get_json(force=True)
    quiz_id = payload.get('quizId')
    student_email = payload.get('studentEmail')
    score = payload.get('score')
    answers = json.dumps(payload.get('answers', []))

    if not quiz_id or not student_email or score is None:
        return jsonify({'error': 'missing quizId, studentEmail, or score'}), 400

    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO quiz_results (quizId, studentEmail, score, completedDate, answers) 
            VALUES (?, ?, ?, ?, ?)
            """,
            (quiz_id, student_email, score, datetime.utcnow().isoformat() + 'Z', answers)
        )
        conn.commit()
        log_event('quiz_result', {'quizId': quiz_id, 'student': student_email, 'score': score})
        return jsonify({'status': 'ok'}), 201
    except sqlite3.IntegrityError:
        return jsonify({'error': 'quiz already submitted'}), 409
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'Database error: {e}'}), 500
    finally:
        conn.close()

@app.route('/api/quiz_results', methods=['GET'])
def get_quiz_results():
    student = request.args.get('studentEmail')
    quiz_param = request.args.get('quizId')
    conn = get_db()

    # Support filtering by studentEmail or by quizId (faculty view)
    if student:
        results = conn.execute("SELECT * FROM quiz_results WHERE studentEmail = ?", (student,)).fetchall()
    elif quiz_param:
        results = conn.execute("SELECT * FROM quiz_results WHERE quizId = ?", (quiz_param,)).fetchall()
    else:
        results = conn.execute("SELECT * FROM quiz_results").fetchall()

    conn.close()

    formatted_results = []
    for r in results:
        result = dict(r)
        result['answers'] = json.loads(result.get('answers', '[]'))
        formatted_results.append(result)

    return jsonify({'results': formatted_results})


@app.route('/api/quizzes/<int:quiz_id>/export', methods=['GET'])
def export_quiz_results(quiz_id):
    """Export results for a given quiz as CSV (downloadable)."""
    conn = get_db()
    results = conn.execute("SELECT quizId, studentEmail, score, completedDate, answers FROM quiz_results WHERE quizId = ?", (quiz_id,)).fetchall()
    conn.close()

    # Build CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['quizId', 'studentEmail', 'score', 'completedDate', 'answers'])
    for r in results:
        # answers are stored as JSON string in DB; leave as-is so it's easy to inspect in CSV
        writer.writerow([r['quizId'], r['studentEmail'], r['score'], r['completedDate'], r['answers']])

    csv_data = output.getvalue()
    output.close()

    headers = {
        "Content-Disposition": f"attachment; filename=quiz_{quiz_id}_results.csv"
    }
    return Response(csv_data, mimetype='text/csv', headers=headers)


# --- Static and Setup Routes ---

@app.route('/api/logs', methods=['GET'])
def get_logs():
    ensure_dirs()
    if not os.path.exists(LOG_FILE):
        return jsonify([])
    with open(LOG_FILE, 'r', encoding='utf-8') as f:
        try:
            logs = json.load(f)
        except Exception:
            logs = []
    return jsonify(logs)

@app.route('/<path:filename>', methods=['GET'])
def serve_file(filename):
    # simple static serving for index.html and related files
    root = os.path.dirname(__file__)
    return send_from_directory(root, filename)

@app.route('/', methods=['GET'])
def index():
    # Serve index.html but ensure footer is present
    root = os.path.dirname(__file__)
    index_path = os.path.join(root, 'index.html')
    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            html = f.read()
    except Exception:
        return send_from_directory(root, 'index.html')

    footer_html = '<footer class="text-center text-gray-500 text-sm py-4"> ©Team VedaNetra, 2025 All rights reserved</footer>'
    if '@Team VedaNetra' not in html:
        if '</body>' in html:
            html = html.replace('</body>', f'{footer_html}</body>')
        else:
            html = html + footer_html

    return Response(html, mimetype='text/html')

if __name__ == '__main__':
    # Initialize the database before running the app
    init_db()
    print(f"Database initialized at {DB_PATH}")
    app.run(debug=True, host='0.0.0.0', port=5000)