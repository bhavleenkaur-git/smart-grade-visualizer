"""
smart_grade_visualizer - simple Flask app using CSV storage.

Features:
- Two-step data entry: number of students -> number of subjects -> subject names + marks
- Stores rows in CSV: columns = Name,Subject,Marks
- Display grouped table (student name merged)
- Subject-wise stats (average, highest, lowest)
- Interactive charts using Chart.js (hover tooltips)
- Server-side PNG/PDF export using matplotlib (uses Agg backend to avoid Tkinter)
- Edit and Delete (delete removes all rows for a student name; edit edits name+subject entry)
"""

from flask import Flask, render_template, request, redirect, url_for, flash, send_file
import csv
import os
import matplotlib
matplotlib.use('Agg')   # Use non-GUI backend (very important on servers / without display)
import matplotlib.pyplot as plt

# ---------- App config ----------
app = Flask(__name__)
app.secret_key = "smartgrade_demo_secret"   # required for flash messages

# CSV file and plots folder
DATA_FILE = "grades.csv"
PLOTS_DIR = os.path.join("static", "plots")
os.makedirs(PLOTS_DIR, exist_ok=True)  # create plots dir if missing


# ---------- Helper functions for CSV ----------
def ensure_csv():
    """
    Ensure that the CSV exists and has the correct header.
    If missing, create it with header: Name,Subject,Marks
    """
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Name", "Subject", "Marks"])


def read_data():
    """
    Read CSV and return list of dict rows: [{'Name':..., 'Subject':..., 'Marks':...}, ...]
    """
    ensure_csv()
    with open(DATA_FILE, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return list(reader)


def write_data(rows):
    """
    Overwrite CSV with given list of dict rows.
    Each row must have keys: Name, Subject, Marks
    """
    with open(DATA_FILE, "w", newline='', encoding='utf-8') as f:
        fieldnames = ["Name", "Subject", "Marks"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def append_rows(rows):
    """
    Append rows (list of dicts) to CSV.
    """
    ensure_csv()
    with open(DATA_FILE, "a", newline='', encoding='utf-8') as f:
        fieldnames = ["Name", "Subject", "Marks"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerows(rows)


# ---------- Routes (views) ----------

@app.route('/', methods=['GET', 'POST'])
def add_students():
    """
    Step 1: ask number of students.
    On POST redirect to step2 with the number of students.
    """
    if request.method == 'POST':
        try:
            n = int(request.form.get('num_students', '0'))
            if n < 1:
                raise ValueError
        except ValueError:
            flash("Please enter a valid number of students (>=1).", "error")
            return redirect(url_for('add_students'))
        return redirect(url_for('step2', num_students=n))
    # GET -> render form
    return render_template('add_students.html')


@app.route('/step2/<int:num_students>', methods=['GET', 'POST'])
def step2(num_students):
    """
    Step 2: ask number of subjects. On POST show enter_marks template.
    """
    if request.method == 'POST':
        try:
            s = int(request.form.get('num_subjects', '0'))
            if s < 1:
                raise ValueError
        except ValueError:
            flash("Please enter a valid number of subjects (>=1).", "error")
            return redirect(url_for('step2', num_students=num_students))
        # render the page with dynamic fields to enter subjects and marks
        return render_template('enter_marks.html', num_students=num_students, num_subjects=s)
    return render_template('step2.html', num_students=num_students)


@app.route('/enter_marks', methods=['POST'])
def enter_marks():
    """
    Receive final form: subject names and marks for each student.
    Validate input and append to CSV.
    """
    # get counts
    try:
        num_students = int(request.form.get('num_students', '0'))
        num_subjects = int(request.form.get('num_subjects', '0'))
    except ValueError:
        flash("Invalid submission.", "error")
        return redirect(url_for('add_students'))

    # collect subject names
    subjects = []
    for j in range(num_subjects):
        key = f"subject_{j}_name"
        subj = request.form.get(key, "").strip()
        if not subj:
            flash("All subject names are required.", "error")
            return redirect(url_for('step2', num_students=num_students))
        subjects.append(subj)

    rows_to_append = []
    # collect each student's name and marks
    for i in range(num_students):
        student_name = request.form.get(f"student_{i}_name", "").strip()
        if not student_name:
            flash("All student names are required.", "error")
            return redirect(url_for('step2', num_students=num_students))
        for j, subj in enumerate(subjects):
            mkey = f"student_{i}_subject_{j}_marks"
            val = request.form.get(mkey, "").strip()
            if val == "":
                flash("All marks are required.", "error")
                return redirect(url_for('step2', num_students=num_students))
            try:
                m = int(val)
                if not (0 <= m <= 100):
                    raise ValueError
            except ValueError:
                flash("Marks must be integers between 0 and 100.", "error")
                return redirect(url_for('step2', num_students=num_students))
            rows_to_append.append({"Name": student_name, "Subject": subj, "Marks": str(m)})

    # append to CSV
    append_rows(rows_to_append)
    flash("Students and marks added successfully.", "success")
    return redirect(url_for('display'))


@app.route('/display')
def display():
    """
    Display grouped student table (name merged), subject stats, and optionally show chart.
    If query param 'subject' is provided, an interactive Chart.js chart will be shown for that subject.
    Query params:
      - subject=SUBJECT_NAME
      - type=chart_type (bar, line, pie, radar, doughnut)  (optional, default 'bar')
    """
    data = read_data()

    # 1) Group rows by student name -> for merged-cell table
    grouped = {}
    for r in data:
        name = r['Name']
        subj = r['Subject']
        marks = int(r['Marks'])
        grouped.setdefault(name, []).append((subj, marks))

    # 2) Build subject -> list of marks map to compute stats
    subj_map = {}
    for r in data:
        subj = r['Subject']
        marks = int(r['Marks'])
        subj_map.setdefault(subj, []).append(marks)

    stats = {}
    for subj, marks in subj_map.items():
        stats[subj] = {
            "avg": round(sum(marks) / len(marks), 2),
            "max": max(marks),
            "min": min(marks)
        }

    # 3) If user requested a subject chart, prepare chart data
    graph_subject = request.args.get('subject')   # e.g. ?subject=Math
    graph_type = request.args.get('type', 'bar')  # default 'bar'
    names = []
    marks = []
    if graph_subject:
        filtered = [r for r in data if r['Subject'] == graph_subject]
        # maintain the order in CSV (use names as labels)
        names = [r['Name'] for r in filtered]
        marks = [int(r['Marks']) for r in filtered]

    return render_template('display.html',
                           grouped=grouped,
                           stats=stats,
                           show_graph=bool(graph_subject),
                           graph_subject=graph_subject,
                           graph_type=graph_type,
                           names=names,
                           marks=marks)


@app.route('/delete/<name>')
def delete(name):
    """
    Delete all rows for a given student name.
    (Simpler behavior: deletes by exact name match.)
    """
    data = read_data()
    new = [r for r in data if r['Name'] != name]
    write_data(new)
    flash(f"Deleted all records for {name}.", "warning")
    return redirect(url_for('display'))


@app.route('/edit/<name>/<subject>', methods=['GET', 'POST'])
def edit(name, subject):
    """
    Edit marks for a particular student+subject. Finds first matching row.
    """
    data = read_data()
    entry = next((r for r in data if r['Name'] == name and r['Subject'] == subject), None)
    if not entry:
        flash("Record not found.", "error")
        return redirect(url_for('display'))

    if request.method == 'POST':
        new_marks = request.form.get('marks', '').strip()
        try:
            m = int(new_marks)
            if not (0 <= m <= 100):
                raise ValueError
        except ValueError:
            flash("Marks must be an integer between 0 and 100.", "error")
            return redirect(url_for('edit', name=name, subject=subject))

        # update first matching row
        for r in data:
            if r['Name'] == name and r['Subject'] == subject:
                r['Marks'] = str(m)
                break
        write_data(data)
        flash("Updated marks.", "success")
        return redirect(url_for('display'))

    # GET -> show edit form
    return render_template('edit.html', name=name, subject=subject, marks=entry['Marks'])


@app.route('/graph/<subject>')
def graph(subject):
    """
    Redirect convenience route to display with query params.
    E.g. /graph/Math?type=line => /display?subject=Math&type=line
    """
    ctype = request.args.get('type', 'bar')
    return redirect(url_for('display', subject=subject, type=ctype))


@app.route('/download/<subject>/<fmt>')
def download(subject, fmt):
    """
    Server-side export of subject chart as PNG or PDF using matplotlib.
    fmt: 'png' or 'pdf'
    """
    data = read_data()
    filtered = [r for r in data if r['Subject'] == subject]
    if not filtered:
        flash("No data for that subject.", "error")
        return redirect(url_for('display'))

    names = [r['Name'] for r in filtered]
    marks = [int(r['Marks']) for r in filtered]

    # prepare file paths
    safe_name = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in subject).replace(' ', '_')
    png_path = os.path.join(PLOTS_DIR, f"{safe_name}.png")
    pdf_path = os.path.join(PLOTS_DIR, f"{safe_name}.pdf")

    # build simple bar chart with value labels
    plt.figure(figsize=(8, 4.5))
    bars = plt.bar(names, marks, color='#4f46e5')
    plt.xlabel("Students")
    plt.ylabel("Marks")
    plt.title(f"Marks - {subject}")
    plt.ylim(0, 100)

    # label values above bars
    for bar in bars:
        y = bar.get_height()
        plt.text(bar.get_x() + bar.get_width() / 2, y + 1, str(y), ha='center', fontsize=9)

    plt.tight_layout()
    if fmt.lower() == 'pdf':
        plt.savefig(pdf_path)
        plt.close()
        return send_file(pdf_path, as_attachment=True)
    else:
        plt.savefig(png_path)
        plt.close()
        return send_file(png_path, as_attachment=True)


# ---------- Run server ----------
if __name__ == '__main__':
    # use_reloader=False avoids double-invocations of matplotlib on code edit during dev
    app.run(debug=True, use_reloader=False)
