from flask import Flask, render_template, request, session, send_file
import os
import uuid

import pandas as pd

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    PageBreak
)
from reportlab.lib.enums import TA_CENTER


app = Flask(__name__)

app.secret_key = "seating-project-secret-key"

UPLOAD_FOLDER = "uploads"
PDF_FOLDER = "generated_pdfs"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PDF_FOLDER, exist_ok=True)


# ============================================================
# CONSTANTS
# ============================================================

REQUIRED_COLUMNS = [
    "Register Number",
    "Name",
    "Department",
    "Year"
]


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():
    return render_template("index.html")


# ============================================================
# READ STUDENT FILE
# Supports CSV and XLSX
# ============================================================

def read_student_file(file):

    filename = file.filename.lower()

    try:

        if filename.endswith(".csv"):
            students = pd.read_csv(file)

        elif filename.endswith(".xlsx"):
            students = pd.read_excel(file)

        else:
            return None, "Invalid file type."

    except Exception as e:

        return None, f"Unable to read file: {e}"

    return students, None


# ============================================================
# VALIDATE STUDENT DATA
# ============================================================

def validate_student_data(students):

    missing_columns = [
        column
        for column in REQUIRED_COLUMNS
        if column not in students.columns
    ]

    if missing_columns:

        return (
            False,
            "Missing required field(s): "
            + ", ".join(missing_columns)
        )

    empty_fields = []

    for column in REQUIRED_COLUMNS:

        if students[column].isna().any():

            empty_fields.append(column)
            continue

        if (
            students[column]
            .astype(str)
            .str.strip()
            .eq("")
            .any()
        ):

            empty_fields.append(column)

    if empty_fields:

        return (
            False,
            "Some student details are missing: "
            + ", ".join(empty_fields)
        )

    return True, None


# ============================================================
# UPLOAD MULTIPLE STUDENT FILES
# ============================================================

@app.route("/upload", methods=["POST"])
def upload():

    files = request.files.getlist("student_files")

    files = [
        file
        for file in files
        if file and file.filename.strip()
    ]

    if not files:

        return "⚠️ No student files selected."

    all_students = []
    uploaded_files = []

    # --------------------------------------------------------
    # Read every uploaded file
    # --------------------------------------------------------

    for file in files:

        filename = file.filename

        if not filename.lower().endswith(
            (".csv", ".xlsx")
        ):

            return (
                f"⚠️ Invalid file: {filename}<br><br>"
                "Only CSV and XLSX files are supported."
            )

        students, error = read_student_file(file)

        if error:

            return (
                f"⚠️ Error in {filename}<br><br>"
                f"{error}"
            )

        valid, validation_error = validate_student_data(
            students
        )

        if not valid:

            return (
                f"⚠️ Invalid student file: {filename}"
                f"<br><br>"
                f"{validation_error}"
            )

        # ----------------------------------------------------
        # Clean text values
        # ----------------------------------------------------

        students = students.copy()

        students["Register Number"] = (
            students["Register Number"]
            .astype(str)
            .str.strip()
        )

        students["Name"] = (
            students["Name"]
            .astype(str)
            .str.strip()
        )

        students["Department"] = (
            students["Department"]
            .astype(str)
            .str.strip()
        )

        students["Year"] = (
            students["Year"]
            .astype(str)
            .str.strip()
        )

        # Internal source file information
        students["_source_file"] = filename

        all_students.append(students)
        uploaded_files.append(filename)

        # ----------------------------------------------------
        # Save uploaded file
        # ----------------------------------------------------

        unique_name = (
            f"{uuid.uuid4().hex}_{filename}"
        )

        filepath = os.path.join(
            UPLOAD_FOLDER,
            unique_name
        )

        file.seek(0)
        file.save(filepath)

    # --------------------------------------------------------
    # Combine all files
    # --------------------------------------------------------

    combined_students = pd.concat(
        all_students,
        ignore_index=True
    )

    # --------------------------------------------------------
    # Check duplicate register numbers
    # --------------------------------------------------------

    duplicate_registers = (
        combined_students[
            combined_students["Register Number"]
            .duplicated(keep=False)
        ]["Register Number"]
        .unique()
        .tolist()
    )

    if duplicate_registers:

        return (
            "⚠️ Duplicate Register Number(s) found:"
            "<br><br>"
            + "<br>".join(
                str(number)
                for number in duplicate_registers
            )
            + "<br><br>"
            "Please correct the student files "
            "before continuing."
        )

    # --------------------------------------------------------
    # Store combined data in session
    # --------------------------------------------------------

    session["students"] = (
        combined_students[
            REQUIRED_COLUMNS
        ].to_dict(orient="records")
    )

    session["uploaded_files"] = uploaded_files

    # Reset old seating data
    session.pop("seating", None)
    session.pop("halls", None)

    # --------------------------------------------------------
    # Department summary
    # --------------------------------------------------------

    department_counts = (
        combined_students["Department"]
        .value_counts()
        .to_dict()
    )

    # --------------------------------------------------------
    # Year summary
    # --------------------------------------------------------

    year_counts = (
        combined_students["Year"]
        .value_counts()
        .to_dict()
    )

    return render_template(
        "students.html",

        students=combined_students[
            REQUIRED_COLUMNS
        ].to_dict(orient="records"),

        uploaded_files=uploaded_files,

        total_students=len(combined_students),

        department_counts=department_counts,

        year_counts=year_counts
    )


# ============================================================
# EXAM + HALL PAGE
# ============================================================

@app.route("/exam-hall")
def exam_hall():

    students = session.get("students")

    if not students:

        return (
            "⚠️ Student data not found. "
            "Please upload the student files first."
        )

    return render_template("exam_hall.html")


# ============================================================
# SAVE EXAM + MULTIPLE HALLS
# ============================================================

@app.route("/save-exam-hall", methods=["POST"])
def save_exam_hall():

    students = session.get("students")

    if not students:

        return (
            "⚠️ Student data not found. "
            "Please upload the student files again."
        )

    # --------------------------------------------------------
    # Exam details
    # --------------------------------------------------------

    exam_name = request.form.get(
        "exam_name",
        ""
    ).strip()

    exam_date = request.form.get(
        "exam_date",
        ""
    ).strip()

    exam_time = request.form.get(
        "exam_time",
        ""
    ).strip()

    if not exam_name or not exam_date or not exam_time:

        return (
            "⚠️ Please enter all examination details."
        )

    # --------------------------------------------------------
    # Multiple halls
    # --------------------------------------------------------

    hall_names = request.form.getlist(
        "hall_name"
    )

    rows_list = request.form.getlist(
        "rows"
    )

    columns_list = request.form.getlist(
        "columns"
    )

    seats_list = request.form.getlist(
        "seats_per_bench"
    )

    if not hall_names:

        return (
            "⚠️ Please add at least one examination hall."
        )

    if not (
        len(hall_names)
        == len(rows_list)
        == len(columns_list)
        == len(seats_list)
    ):

        return (
            "⚠️ Invalid hall information."
        )

    halls = []

    total_capacity = 0

    # --------------------------------------------------------
    # Validate every hall
    # --------------------------------------------------------

    for index in range(len(hall_names)):

        hall_name = hall_names[index].strip()

        try:

            rows = int(rows_list[index])
            columns = int(columns_list[index])
            seats_per_bench = int(
                seats_list[index]
            )

        except ValueError:

            return (
                "⚠️ Rows, columns and seats per bench "
                "must be valid numbers."
            )

        if not hall_name:

            return (
                "⚠️ Hall name cannot be empty."
            )

        if rows < 1 or columns < 1:

            return (
                f"⚠️ Invalid row/column value "
                f"for {hall_name}."
            )

        if seats_per_bench not in [1, 2]:

            return (
                f"⚠️ {hall_name}: "
                "Only 1 or 2 students per bench "
                "are allowed."
            )

        total_benches = rows * columns

        capacity = (
            total_benches * seats_per_bench
        )

        halls.append({
            "hall_name": hall_name,
            "rows": rows,
            "columns": columns,
            "seats_per_bench": seats_per_bench,
            "total_benches": total_benches,
            "capacity": capacity
        })

        total_capacity += capacity

    # --------------------------------------------------------
    # Check duplicate hall names
    # --------------------------------------------------------

    hall_names_clean = [
        hall["hall_name"].lower()
        for hall in halls
    ]

    if len(hall_names_clean) != len(
        set(hall_names_clean)
    ):

        return (
            "⚠️ Hall names must be unique."
        )

    # --------------------------------------------------------
    # Student count
    # --------------------------------------------------------

    total_students = len(students)

    # --------------------------------------------------------
    # Capacity check
    # --------------------------------------------------------

    if total_capacity < total_students:

        return (
            "⚠️ Total hall capacity is not enough."
            "<br><br>"
            f"Total students: {total_students}<br>"
            f"Total available seats: {total_capacity}<br><br>"
            "Please add another hall or increase "
            "the hall capacity."
        )

    # --------------------------------------------------------
    # Store in session
    # --------------------------------------------------------

    session["exam_name"] = exam_name
    session["exam_date"] = exam_date
    session["exam_time"] = exam_time
    session["halls"] = halls

    # --------------------------------------------------------
    # Department + year summary
    # --------------------------------------------------------

    students_df = pd.DataFrame(students)

    department_counts = (
        students_df["Department"]
        .value_counts()
        .to_dict()
    )

    year_counts = (
        students_df["Year"]
        .value_counts()
        .to_dict()
    )

    # --------------------------------------------------------
    # Show summary
    # --------------------------------------------------------

    return render_template(
        "exam_summary.html",

        exam_name=exam_name,
        exam_date=exam_date,
        exam_time=exam_time,

        halls=halls,

        total_students=total_students,

        total_capacity=total_capacity,

        department_counts=department_counts,

        year_counts=year_counts
    )


# ============================================================
# SEATING ALGORITHM
#
# RULE:
#
# Same Year      -> NEVER share a bench
# Different Year -> CAN share a bench
#
# Department does NOT affect bench sharing.
# ============================================================

def create_seating(students, halls):

    students = [
        dict(student)
        for student in students
    ]

    # --------------------------------------------------------
    # Create benches
    # --------------------------------------------------------

    benches = []

    for hall in halls:

        for row in range(
            1,
            hall["rows"] + 1
        ):

            for column in range(
                1,
                hall["columns"] + 1
            ):

                bench_number = (
                    (row - 1)
                    * hall["columns"]
                    + column
                )

                benches.append({
                    "Hall": hall["hall_name"],
                    "Row": row,
                    "Column": column,
                    "Bench": bench_number,
                    "Seats": hall["seats_per_bench"]
                })

    # --------------------------------------------------------
    # Verify physical capacity
    # --------------------------------------------------------

    total_capacity = sum(
        bench["Seats"]
        for bench in benches
    )

    if total_capacity < len(students):

        return None, (
            "Total seating capacity is insufficient."
        )

    # --------------------------------------------------------
    # Group students by year
    # --------------------------------------------------------

    year_groups = {}

    for student in students:

        year = str(
            student["Year"]
        ).strip()

        if year not in year_groups:

            year_groups[year] = []

        year_groups[year].append(student)

    # --------------------------------------------------------
    # IMPORTANT VALIDITY CHECK
    #
    # If a 2-seat bench is available, we need enough
    # students from different years to fill paired seats.
    #
    # The algorithm below dynamically chooses a different
    # year for the second seat.
    # --------------------------------------------------------

    seating = []

    # --------------------------------------------------------
    # For every bench
    # --------------------------------------------------------

    for bench in benches:

        available_years = [
            year
            for year, group in year_groups.items()
            if group
        ]

        if not available_years:
            break

        # ----------------------------------------------------
        # Pick the largest remaining year group first.
        # This prevents one year from getting stranded.
        # ----------------------------------------------------

        available_years.sort(
            key=lambda year: len(
                year_groups[year]
            ),
            reverse=True
        )

        first_year = available_years[0]

        first_student = year_groups[
            first_year
        ].pop(0)

        seating.append({
            "Register Number":
                first_student["Register Number"],

            "Name":
                first_student["Name"],

            "Department":
                first_student["Department"],

            "Year":
                first_student["Year"],

            "Hall":
                bench["Hall"],

            "Row":
                bench["Row"],

            "Column":
                bench["Column"],

            "Bench":
                bench["Bench"],

            "Seat Number":
                (
                    f"R{bench['Row']}-"
                    f"C{bench['Column']}-S1"
                )
        })

        # ----------------------------------------------------
        # Second seat
        # ----------------------------------------------------

        if bench["Seats"] == 2:

            different_years = [
                year
                for year, group in year_groups.items()
                if group and year != first_year
            ]

            if different_years:

                different_years.sort(
                    key=lambda year: len(
                        year_groups[year]
                    ),
                    reverse=True
                )

                second_year = different_years[0]

                second_student = year_groups[
                    second_year
                ].pop(0)

                seating.append({
                    "Register Number":
                        second_student[
                            "Register Number"
                        ],

                    "Name":
                        second_student["Name"],

                    "Department":
                        second_student["Department"],

                    "Year":
                        second_student["Year"],

                    "Hall":
                        bench["Hall"],

                    "Row":
                        bench["Row"],

                    "Column":
                        bench["Column"],

                    "Bench":
                        bench["Bench"],

                    "Seat Number":
                        (
                            f"R{bench['Row']}-"
                            f"C{bench['Column']}-S2"
                        )
                })

    # --------------------------------------------------------
    # Check whether every student was seated
    # --------------------------------------------------------

    remaining_students = sum(
        len(group)
        for group in year_groups.values()
    )

    if remaining_students > 0:

        return None, (
            "The available halls cannot satisfy the "
            "same-year seating restriction with the "
            "configured bench arrangement."
        )

    # --------------------------------------------------------
    # FINAL SAFETY CHECK
    #
    # Verify that no bench contains two students
    # from the same year.
    # --------------------------------------------------------

    bench_years = {}

    for student in seating:

        key = (
            student["Hall"],
            student["Bench"]
        )

        if key not in bench_years:

            bench_years[key] = []

        bench_years[key].append(
            str(student["Year"]).strip()
        )

    for key, years in bench_years.items():

        if len(years) == 2 and years[0] == years[1]:

            return None, (
                "Seating validation failed: "
                f"same-year students were assigned "
                f"to the same bench in {key[0]}, "
                f"Bench {key[1]}."
            )

    return seating, None


# ============================================================
# GENERATE SEATING
# ============================================================

@app.route("/generate-seating", methods=["POST"])
def generate_seating():

    students = session.get("students")
    halls = session.get("halls")

    if not students:

        return (
            "⚠️ Student data not found."
        )

    if not halls:

        return (
            "⚠️ Hall details not found."
        )

    seating, error = create_seating(
        students,
        halls
    )

    if error:

        return f"⚠️ {error}"

    # --------------------------------------------------------
    # Store seating
    # --------------------------------------------------------

    session["seating"] = seating

    # --------------------------------------------------------
    # Hall-wise counts
    # --------------------------------------------------------

    hall_counts = {}

    for hall in halls:

        hall_name = hall["hall_name"]

        hall_counts[hall_name] = len([
            student
            for student in seating
            if student["Hall"] == hall_name
        ])

    # --------------------------------------------------------
    # Create hall result data for template
    # --------------------------------------------------------

    result_halls = []

    for hall in halls:

        hall_name = hall["hall_name"]

        hall_students = [
            student
            for student in seating
            if student["Hall"] == hall_name
        ]

        # -----------------------------------------------
        # Create visual plan
        # -----------------------------------------------

        plan = []

        for row in range(
            1,
            hall["rows"] + 1
        ):

            row_data = []

            for column in range(
                1,
                hall["columns"] + 1
            ):

                bench_students = [
                    student
                    for student in hall_students
                    if (
                        student["Row"] == row
                        and student["Column"] == column
                    )
                ]

                row_data.append({
                    "students": bench_students
                })

            plan.append(row_data)

        result_halls.append({
            **hall,
            "students": hall_students,
            "assigned_students": len(hall_students),
            "plan": plan
        })

    return render_template(
        "seating_result.html",

        seating=seating,

        halls=result_halls,

        hall_counts=hall_counts,

        total_students=len(students),

        exam_name=session.get(
            "exam_name",
            ""
        ),

        exam_date=session.get(
            "exam_date",
            ""
        ),

        exam_time=session.get(
            "exam_time",
            ""
        )
    )


# ============================================================
# DOWNLOAD PDF
#
# NO STUDENT NAME IN PDF
# ============================================================

@app.route("/download-pdf")
def download_pdf():

    seating = session.get("seating")
    halls = session.get("halls")

    if not seating:

        return (
            "⚠️ Seating arrangement not found. "
            "Please generate the seating arrangement first."
        )

    exam_name = session.get(
        "exam_name",
        "Exam"
    )

    exam_date = session.get(
        "exam_date",
        ""
    )

    exam_time = session.get(
        "exam_time",
        ""
    )

    total_students = len(seating)

    # --------------------------------------------------------
    # Safe filename
    # --------------------------------------------------------

    safe_exam_name = (
        str(exam_name)
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )

    filename = (
        f"{safe_exam_name}_"
        "Seating_Arrangement.pdf"
    )

    pdf_path = os.path.join(
        PDF_FOLDER,
        filename
    )

    # --------------------------------------------------------
    # Landscape A4
    # --------------------------------------------------------

    document = SimpleDocTemplate(
        pdf_path,

        pagesize=landscape(A4),

        rightMargin=25,
        leftMargin=25,
        topMargin=25,
        bottomMargin=25
    )

    styles = getSampleStyleSheet()

    title_style = styles["Title"]
    title_style.alignment = TA_CENTER

    heading_style = styles["Heading2"]

    normal_style = styles["Normal"]

    elements = []

    # ========================================================
    # TITLE
    # ========================================================

    elements.append(
        Paragraph(
            "EXAM SEATING ARRANGEMENT",
            title_style
        )
    )

    elements.append(
        Spacer(1, 15)
    )

    # ========================================================
    # EXAM DETAILS
    # ========================================================

    details_data = [
        ["Exam Name", exam_name],
        ["Date", exam_date],
        ["Time", exam_time],
        ["Total Students", str(total_students)],
        ["Total Halls", str(len(halls))]
    ]

    details_table = Table(
        details_data,
        colWidths=[120, 300]
    )

    details_table.setStyle(
        TableStyle([
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.black
            ),
            (
                "BACKGROUND",
                (0, 0),
                (0, -1),
                colors.lightgrey
            ),
            (
                "FONTNAME",
                (0, 0),
                (0, -1),
                "Helvetica-Bold"
            ),
            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "MIDDLE"
            ),
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                6
            ),
            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                6
            )
        ])
    )

    elements.append(details_table)

    elements.append(
        Spacer(1, 20)
    )

    # ========================================================
    # EACH HALL
    # ========================================================

    for hall_index, hall in enumerate(halls):

        hall_name = hall["hall_name"]

        hall_students = [
            student
            for student in seating
            if student["Hall"] == hall_name
        ]

        elements.append(
            Paragraph(
                f"Hall: {hall_name}",
                heading_style
            )
        )

        elements.append(
            Spacer(1, 8)
        )

        # ----------------------------------------------------
        # Hall details
        # ----------------------------------------------------

        hall_details = [
            ["Hall Name", hall_name],
            ["Rows", str(hall["rows"])],
            ["Columns", str(hall["columns"])],
            [
                "Seats per Bench",
                str(hall["seats_per_bench"])
            ],
            [
                "Total Benches",
                str(hall["total_benches"])
            ],
            [
                "Capacity",
                str(hall["capacity"])
            ],
            [
                "Students Allotted",
                str(len(hall_students))
            ]
        ]

        hall_table = Table(
            hall_details,
            colWidths=[130, 180]
        )

        hall_table.setStyle(
            TableStyle([
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.black
                ),
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    colors.lightgrey
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (0, -1),
                    "Helvetica-Bold"
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE"
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    8
                )
            ])
        )

        elements.append(hall_table)

        elements.append(
            Spacer(1, 15)
        )

        # ----------------------------------------------------
        # ACTUAL HALL PLAN
        # ----------------------------------------------------

        elements.append(
            Paragraph(
                "Hall Seating Plan",
                heading_style
            )
        )

        elements.append(
            Spacer(1, 8)
        )

        # Build lookup
        seat_lookup = {}

        for student in hall_students:

            key = (
                student["Row"],
                student["Column"],
                student["Seat Number"]
            )

            seat_lookup[key] = student[
                "Register Number"
            ]

        plan_data = []

        # Header
        header_row = ["Row / Column"]

        for column in range(
            1,
            hall["columns"] + 1
        ):

            header_row.append(
                f"C{column}"
            )

        plan_data.append(header_row)

        # Rows
        for row in range(
            1,
            hall["rows"] + 1
        ):

            row_data = [
                f"R{row}"
            ]

            for column in range(
                1,
                hall["columns"] + 1
            ):

                seat_1 = seat_lookup.get(
                    (
                        row,
                        column,
                        f"R{row}-C{column}-S1"
                    ),
                    ""
                )

                seat_2 = ""

                if hall["seats_per_bench"] == 2:

                    seat_2 = seat_lookup.get(
                        (
                            row,
                            column,
                            f"R{row}-C{column}-S2"
                        ),
                        ""
                    )

                if seat_1 and seat_2:

                    cell = (
                        f"{seat_1}<br/>"
                        f"{seat_2}"
                    )

                elif seat_1:

                    cell = seat_1

                elif seat_2:

                    cell = seat_2

                else:

                    cell = "EMPTY"

                row_data.append(
                    Paragraph(
                        str(cell),
                        normal_style
                    )
                )

            plan_data.append(row_data)

        # ----------------------------------------------------
        # Dynamic column widths
        # ----------------------------------------------------

        page_width = 750

        first_column_width = 55

        remaining_width = (
            page_width
            - first_column_width
        )

        column_width = (
            remaining_width
            / hall["columns"]
        )

        plan_col_widths = [
            first_column_width
        ] + [
            column_width
            for _ in range(hall["columns"])
        ]

        plan_table = Table(
            plan_data,

            colWidths=plan_col_widths,

            repeatRows=1
        )

        plan_table.setStyle(
            TableStyle([
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.6,
                    colors.black
                ),
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.grey
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    "Helvetica-Bold"
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (0, -1),
                    "Helvetica-Bold"
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    7
                ),
                (
                    "ALIGN",
                    (0, 0),
                    (-1, -1),
                    "CENTER"
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE"
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    8
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    8
                )
            ])
        )

        elements.append(plan_table)

        elements.append(
            Spacer(1, 20)
        )

        # ----------------------------------------------------
        # Student details
        #
        # NAME IS INTENTIONALLY NOT INCLUDED
        # ----------------------------------------------------

        elements.append(
            Paragraph(
                "Student Seating Details",
                heading_style
            )
        )

        elements.append(
            Spacer(1, 8)
        )

        student_table_data = [
            [
                "Register Number",
                "Department",
                "Year",
                "Bench",
                "Seat"
            ]
        ]

        for student in hall_students:

            student_table_data.append([
                str(student["Register Number"]),
                str(student["Department"]),
                str(student["Year"]),
                str(student["Bench"]),
                str(student["Seat Number"])
            ])

        student_table = Table(
            student_table_data,

            repeatRows=1,

            colWidths=[
                130,
                100,
                60,
                60,
                110
            ]
        )

        student_table.setStyle(
            TableStyle([
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.black
                ),
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.grey
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    "Helvetica-Bold"
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    8
                ),
                (
                    "ALIGN",
                    (0, 0),
                    (-1, -1),
                    "CENTER"
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE"
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    5
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    5
                )
            ])
        )

        elements.append(student_table)

        # New page for next hall
        if hall_index < len(halls) - 1:

            elements.append(
                PageBreak()
            )

    # ========================================================
    # BUILD PDF
    # ========================================================

    document.build(elements)

    return send_file(
        pdf_path,
        as_attachment=True,
        download_name=filename
    )


# ============================================================
# RUN APPLICATION
# ============================================================

if __name__ == "__main__":

    app.run(
        debug=True
    )