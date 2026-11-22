"""Non-destructive openpyxl gradebook synchronization engine."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from server.models import User, Quiz, Attempt


def sync_gradebook_to_excel(db_session: Session, output_path: Path) -> Optional[str]:
    """
    Synchronize graded quiz scores into a structured Excel gradebook.

    Returns None on success, or an error message string on failure.
    """
    try:
        # ── 1. Load or create workbook ───────────────────────────────────
        if output_path.exists():
            try:
                wb = load_workbook(output_path)
            except PermissionError:
                return (
                    "Cannot write to gradebook.xlsx — it is currently open "
                    "in another application. Please close it and try again."
                )
            ws = wb.active
            if ws.title != "Grades":
                ws.title = "Grades"
        else:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            wb = Workbook()
            ws = wb.active
            ws.title = "Grades"
            ws["A1"] = "Student ID"
            ws["B1"] = "Student Name"
            ws["C1"] = "Total"

        # ── 2. Build header index from Row 1 ─────────────────────────────
        header_map: dict[str, int] = {}  # header_text -> column_index (1-based)
        total_col: int = 0
        for col_idx in range(1, ws.max_column + 1):
            val = ws.cell(row=1, column=col_idx).value
            if val is not None:
                header_map[str(val)] = col_idx
                if str(val) == "Total":
                    total_col = col_idx

        # Ensure "Total" column exists
        if total_col == 0:
            total_col = ws.max_column + 1
            ws.cell(row=1, column=total_col, value="Total")
            header_map["Total"] = total_col

        # ── 3. Index existing student rows by Student ID (Column A) ──────
        student_rows: dict[str, int] = {}  # student_id -> row_number
        for row_idx in range(2, ws.max_row + 1):
            sid = ws.cell(row=row_idx, column=1).value
            if sid is not None:
                student_rows[str(sid)] = row_idx

        # ── 4. Query students and ensure all are in the sheet ────────────
        students = (
            db_session.query(User)
            .filter(User.role == "STUDENT")
            .order_by(User.student_id)
            .all()
        )

        for student in students:
            sid = student.student_id or ""
            if sid not in student_rows:
                new_row = ws.max_row + 1
                ws.cell(row=new_row, column=1, value=sid)
                ws.cell(row=new_row, column=2, value=student.full_name)
                # Initialize Total to 0
                ws.cell(row=new_row, column=header_map["Total"], value=0)
                student_rows[sid] = new_row

        # ── 5. Query quizzes and ensure quiz columns exist ───────────────
        quizzes = (
            db_session.query(Quiz)
            .order_by(Quiz.quiz_number)
            .all()
        )

        for quiz in quizzes:
            quiz_header = f"Quiz {quiz.quiz_number}"
            if quiz_header not in header_map:
                # Re-find current Total column position
                for c in range(1, ws.max_column + 1):
                    if ws.cell(row=1, column=c).value == "Total":
                        total_col = c
                        break

                # Insert new column before Total
                ws.insert_cols(total_col)
                ws.cell(row=1, column=total_col, value=quiz_header)
                header_map[quiz_header] = total_col

                # Shift Total and other header indices
                new_total_col = total_col + 1
                header_map["Total"] = new_total_col
                total_col = new_total_col

                # Rebuild header_map fully after insert
                header_map.clear()
                for c in range(1, ws.max_column + 1):
                    val = ws.cell(row=1, column=c).value
                    if val is not None:
                        header_map[str(val)] = c
                total_col = header_map.get("Total", ws.max_column)

                # Re-index student rows (row numbers don't change on col insert)

        # ── 6. Fill in scores ────────────────────────────────────────────
        for student in students:
            sid = student.student_id or ""
            row = student_rows.get(sid)
            if row is None:
                continue

            for quiz in quizzes:
                quiz_header = f"Quiz {quiz.quiz_number}"
                col = header_map.get(quiz_header)
                if col is None:
                    continue

                attempt = (
                    db_session.query(Attempt)
                    .filter(
                        Attempt.quiz_id == quiz.id,
                        Attempt.student_user_id == student.id,
                        Attempt.status == "GRADED",
                    )
                    .first()
                )

                if attempt:
                    ws.cell(row=row, column=col, value=attempt.total_score)
                else:
                    # Leave blank for non-graded / not taken
                    ws.cell(row=row, column=col, value=None)

        # ── 7. Update Total column with SUM formula ──────────────────────
        total_col = header_map.get("Total", 0)
        if total_col > 0:
            # Find first and last quiz columns
            quiz_cols = []
            for key, col in header_map.items():
                if key.startswith("Quiz "):
                    quiz_cols.append(col)

            if quiz_cols:
                first_quiz_col = min(quiz_cols)
                last_quiz_col = max(quiz_cols)
                first_letter = get_column_letter(first_quiz_col)
                last_letter = get_column_letter(last_quiz_col)

                for row_idx in range(2, ws.max_row + 1):
                    sid = ws.cell(row=row_idx, column=1).value
                    if sid is not None:
                        formula = f"=SUM({first_letter}{row_idx}:{last_letter}{row_idx})"
                        ws.cell(row=row_idx, column=total_col, value=formula)

        # ── 8. Style header row and auto-fit widths ──────────────────────
        header_font = Font(bold=True, color="FFFFFF", size=11)
        header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
        header_alignment = Alignment(horizontal="center", vertical="center")
        thin_border = Border(
            left=Side(style="thin"),
            right=Side(style="thin"),
            top=Side(style="thin"),
            bottom=Side(style="thin"),
        )

        for col_idx in range(1, ws.max_column + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border

        # Auto-fit column widths
        for col_idx in range(1, ws.max_column + 1):
            max_width = 10
            for row_idx in range(1, ws.max_row + 1):
                val = ws.cell(row=row_idx, column=col_idx).value
                if val is not None:
                    max_width = max(max_width, len(str(val)) + 2)
            ws.column_dimensions[get_column_letter(col_idx)].width = min(max_width, 30)

        # ── 9. Save ──────────────────────────────────────────────────────
        try:
            wb.save(output_path)
        except PermissionError:
            return (
                "Cannot write to gradebook.xlsx — it is currently open "
                "in another application. Please close it and try again."
            )

        return None

    except PermissionError:
        return (
            "Cannot access gradebook.xlsx — permission denied. "
            "Please close the file if it is open in another application."
        )
    except Exception as e:
        return f"Error syncing gradebook: {str(e)}"
