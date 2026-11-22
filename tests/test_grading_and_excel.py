"""
Automated tests for hybrid grading workflow and non-destructive Excel sync.
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.models import Base, User, Course, Quiz, Question, Attempt, Answer
from server.auth import hash_password
from server.excel_sync import sync_gradebook_to_excel
from shared.config import DEFAULT_COURSE_ID, DEFAULT_COURSE_CODE, DEFAULT_COURSE_TITLE


@pytest.fixture
def db_session(tmp_path):
    """Create a fresh in-memory database session for each test."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()

    # Seed default course
    course = Course(id=DEFAULT_COURSE_ID, code=DEFAULT_COURSE_CODE, title=DEFAULT_COURSE_TITLE)
    session.add(course)
    session.commit()

    yield session
    session.close()


@pytest.fixture
def gradebook_path(tmp_path):
    """Return a temporary path for the gradebook."""
    return tmp_path / "gradebook.xlsx"


def _create_student(session, student_id: str, name: str, email: str) -> User:
    """Helper: create and return a student user."""
    user = User(
        student_id=student_id,
        full_name=name,
        email=email,
        password_hash=hash_password("testpass"),
        role="STUDENT",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _create_quiz_with_questions(session, quiz_number: int, title: str, questions_data: list) -> Quiz:
    """Helper: create a quiz with given questions."""
    quiz = Quiz(
        course_id=DEFAULT_COURSE_ID,
        quiz_number=quiz_number,
        title=title,
        duration_mins=30,
        is_active=True,
    )
    session.add(quiz)
    session.flush()

    for qd in questions_data:
        q = Question(
            quiz_id=quiz.id,
            q_type=qd["q_type"],
            prompt=qd["prompt"],
            options_json=json.dumps(qd.get("options")) if qd.get("options") else None,
            correct_answer=qd["correct_answer"],
            points=qd.get("points", 1.0),
        )
        session.add(q)

    session.commit()
    session.refresh(quiz)
    return quiz


def _submit_attempt(session, student: User, quiz: Quiz, responses: dict, grade_short: dict | None = None) -> Attempt:
    """Helper: create an attempt, fill answers, and auto-grade MCQ/TF."""
    attempt = Attempt(
        quiz_id=quiz.id,
        student_user_id=student.id,
        status="IN_PROGRESS",
    )
    session.add(attempt)
    session.flush()

    has_short = False
    total_score = 0.0

    for question in quiz.questions:
        response = responses.get(question.id, "")
        answer = Answer(
            attempt_id=attempt.id,
            question_id=question.id,
            student_response=response,
        )

        if question.q_type in ("MCQ", "TF"):
            student_resp = (response or "").strip().lower()
            correct = question.correct_answer.strip().lower()
            if student_resp == correct:
                answer.points_awarded = question.points
            else:
                answer.points_awarded = 0.0
            answer.is_graded = True
            total_score += answer.points_awarded
        elif question.q_type == "SHORT":
            has_short = True
            answer.is_graded = False
            answer.points_awarded = 0.0

        session.add(answer)

    attempt.submitted_at = datetime.now(timezone.utc)

    if has_short:
        attempt.status = "PENDING_REVIEW"
    else:
        attempt.status = "GRADED"

    attempt.total_score = total_score
    session.commit()

    # Optionally grade short answers
    if grade_short and has_short:
        for question in quiz.questions:
            if question.q_type == "SHORT" and question.id in grade_short:
                ans = session.query(Answer).filter(
                    Answer.attempt_id == attempt.id,
                    Answer.question_id == question.id,
                ).first()
                if ans:
                    ans.points_awarded = grade_short[question.id]
                    ans.is_graded = True
                    total_score += ans.points_awarded

        # Check if all graded
        all_answers = session.query(Answer).filter(Answer.attempt_id == attempt.id).all()
        if all(a.is_graded for a in all_answers):
            attempt.status = "GRADED"
            attempt.total_score = sum(a.points_awarded for a in all_answers)

        session.commit()

    session.refresh(attempt)
    return attempt


# ═══════════════════════════════════════════════════════════════════════════
# TEST: Mixed grading transitions
# ═══════════════════════════════════════════════════════════════════════════

class TestHybridGrading:
    """Test MCQ + TF + SHORT grading workflow."""

    def test_all_mcq_tf_auto_graded(self, db_session):
        """Quiz with only MCQ/TF should auto-grade to GRADED status."""
        student = _create_student(db_session, "123456", "Alice", "alice123456@nmu.edu.eg")
        quiz = _create_quiz_with_questions(db_session, 1, "MCQ Quiz", [
            {"q_type": "MCQ", "prompt": "What is 2+2?", "options": ["3", "4", "5", "6"], "correct_answer": "4"},
            {"q_type": "TF", "prompt": "Sky is blue?", "options": ["True", "False"], "correct_answer": "True"},
        ])

        q_ids = [q.id for q in quiz.questions]
        attempt = _submit_attempt(db_session, student, quiz, {
            q_ids[0]: "4",   # Correct
            q_ids[1]: "True",  # Correct
        })

        assert attempt.status == "GRADED"
        assert attempt.total_score == 2.0

    def test_mixed_pending_review(self, db_session):
        """Quiz with SHORT questions should go to PENDING_REVIEW."""
        student = _create_student(db_session, "234567", "Bob", "bob234567@nmu.edu.eg")
        quiz = _create_quiz_with_questions(db_session, 2, "Mixed Quiz", [
            {"q_type": "MCQ", "prompt": "Capital of France?", "options": ["London", "Paris", "Berlin", "Rome"], "correct_answer": "Paris"},
            {"q_type": "SHORT", "prompt": "Explain gravity", "correct_answer": "Force of attraction", "points": 3.0},
        ])

        q_ids = [q.id for q in quiz.questions]
        attempt = _submit_attempt(db_session, student, quiz, {
            q_ids[0]: "Paris",
            q_ids[1]: "Gravity pulls objects toward each other",
        })

        assert attempt.status == "PENDING_REVIEW"
        assert attempt.total_score == 1.0  # Only MCQ graded

    def test_pending_to_graded_after_manual_review(self, db_session):
        """PENDING_REVIEW transitions to GRADED after all SHORT answers are graded."""
        student = _create_student(db_session, "345678", "Charlie", "charlie345678@nmu.edu.eg")
        quiz = _create_quiz_with_questions(db_session, 3, "Full Quiz", [
            {"q_type": "MCQ", "prompt": "1+1?", "options": ["1", "2", "3"], "correct_answer": "2"},
            {"q_type": "SHORT", "prompt": "Define OOP", "correct_answer": "Object-oriented programming", "points": 5.0},
            {"q_type": "TF", "prompt": "Python is compiled?", "options": ["True", "False"], "correct_answer": "False"},
        ])

        q_ids = [q.id for q in quiz.questions]
        short_q_id = q_ids[1]

        attempt = _submit_attempt(db_session, student, quiz, {
            q_ids[0]: "2",
            q_ids[1]: "OOP is a paradigm based on objects",
            q_ids[2]: "False",
        }, grade_short={short_q_id: 4.0})

        assert attempt.status == "GRADED"
        assert attempt.total_score == 6.0  # 1 (MCQ) + 4 (SHORT) + 1 (TF)

    def test_wrong_answers(self, db_session):
        """Incorrect MCQ/TF answers get 0 points."""
        student = _create_student(db_session, "456789", "Diana", "diana456789@nmu.edu.eg")
        quiz = _create_quiz_with_questions(db_session, 4, "Wrong Quiz", [
            {"q_type": "MCQ", "prompt": "2+3?", "options": ["4", "5", "6"], "correct_answer": "5"},
            {"q_type": "TF", "prompt": "1>2?", "options": ["True", "False"], "correct_answer": "False"},
        ])

        q_ids = [q.id for q in quiz.questions]
        attempt = _submit_attempt(db_session, student, quiz, {
            q_ids[0]: "4",     # Wrong
            q_ids[1]: "True",  # Wrong
        })

        assert attempt.status == "GRADED"
        assert attempt.total_score == 0.0

    def test_case_insensitive_grading(self, db_session):
        """Grading should be case-insensitive."""
        student = _create_student(db_session, "567890", "Eve", "eve567890@nmu.edu.eg")
        quiz = _create_quiz_with_questions(db_session, 5, "Case Quiz", [
            {"q_type": "TF", "prompt": "Test?", "options": ["True", "False"], "correct_answer": "true"},
            {"q_type": "MCQ", "prompt": "Pick A", "options": ["A", "B"], "correct_answer": "A"},
        ])

        q_ids = [q.id for q in quiz.questions]
        attempt = _submit_attempt(db_session, student, quiz, {
            q_ids[0]: "TRUE",  # Different case
            q_ids[1]: "a",     # Different case
        })

        assert attempt.status == "GRADED"
        assert attempt.total_score == 2.0


# ═══════════════════════════════════════════════════════════════════════════
# TEST: Non-destructive Excel sync
# ═══════════════════════════════════════════════════════════════════════════

class TestExcelSync:
    """Test gradebook Excel synchronization."""

    def test_create_new_gradebook(self, db_session, gradebook_path):
        """First export creates a new gradebook with headers."""
        student = _create_student(db_session, "111111", "Student A", "a111111@nmu.edu.eg")
        result = sync_gradebook_to_excel(db_session, gradebook_path)

        assert result is None  # Success
        assert gradebook_path.exists()

        from openpyxl import load_workbook
        wb = load_workbook(gradebook_path)
        ws = wb.active
        assert ws["A1"].value == "Student ID"
        assert ws["B1"].value == "Student Name"
        assert ws.cell(row=2, column=1).value == "111111"
        assert ws.cell(row=2, column=2).value == "Student A"

    def test_add_quiz1_scores(self, db_session, gradebook_path):
        """Export with Quiz 1 scores."""
        student = _create_student(db_session, "111111", "Student A", "a111111@nmu.edu.eg")
        quiz1 = _create_quiz_with_questions(db_session, 1, "Quiz 1", [
            {"q_type": "MCQ", "prompt": "Q1", "options": ["A", "B"], "correct_answer": "A"},
        ])
        q_ids = [q.id for q in quiz1.questions]
        _submit_attempt(db_session, student, quiz1, {q_ids[0]: "A"})

        result = sync_gradebook_to_excel(db_session, gradebook_path)
        assert result is None

        from openpyxl import load_workbook
        wb = load_workbook(gradebook_path)
        ws = wb.active

        # Find Quiz 1 column
        quiz1_col = None
        for col in range(1, ws.max_column + 1):
            if ws.cell(row=1, column=col).value == "Quiz 1":
                quiz1_col = col
                break
        assert quiz1_col is not None
        assert ws.cell(row=2, column=quiz1_col).value == 1.0

    def test_add_quiz2_preserves_quiz1(self, db_session, gradebook_path):
        """Adding Quiz 2 and re-exporting preserves Quiz 1 scores."""
        student = _create_student(db_session, "111111", "Student A", "a111111@nmu.edu.eg")

        # Create and score Quiz 1
        quiz1 = _create_quiz_with_questions(db_session, 1, "Quiz 1", [
            {"q_type": "MCQ", "prompt": "Q1", "options": ["A", "B"], "correct_answer": "A"},
        ])
        q1_ids = [q.id for q in quiz1.questions]
        _submit_attempt(db_session, student, quiz1, {q1_ids[0]: "A"})

        # First export
        sync_gradebook_to_excel(db_session, gradebook_path)

        # Create Quiz 2 and add new student
        student2 = _create_student(db_session, "222222", "Student B", "b222222@nmu.edu.eg")
        quiz2 = _create_quiz_with_questions(db_session, 2, "Quiz 2", [
            {"q_type": "TF", "prompt": "Q2", "options": ["True", "False"], "correct_answer": "True", "points": 2.0},
        ])
        q2_ids = [q.id for q in quiz2.questions]
        _submit_attempt(db_session, student2, quiz2, {q2_ids[0]: "True"})

        # Second export
        result = sync_gradebook_to_excel(db_session, gradebook_path)
        assert result is None

        from openpyxl import load_workbook
        wb = load_workbook(gradebook_path)
        ws = wb.active

        # Find columns
        headers = {}
        for col in range(1, ws.max_column + 1):
            val = ws.cell(row=1, column=col).value
            if val:
                headers[val] = col

        assert "Quiz 1" in headers
        assert "Quiz 2" in headers
        assert "Total" in headers

        # Find student rows
        student_a_row = None
        student_b_row = None
        for row in range(2, ws.max_row + 1):
            sid = ws.cell(row=row, column=1).value
            if sid == "111111":
                student_a_row = row
            elif sid == "222222":
                student_b_row = row

        assert student_a_row is not None
        assert student_b_row is not None

        # Quiz 1 score preserved for Student A
        assert ws.cell(row=student_a_row, column=headers["Quiz 1"]).value == 1.0
        # Quiz 2 score for Student B
        assert ws.cell(row=student_b_row, column=headers["Quiz 2"]).value == 2.0

    def test_total_column_has_sum_formula(self, db_session, gradebook_path):
        """Total column should contain =SUM formula."""
        student = _create_student(db_session, "111111", "Student A", "a111111@nmu.edu.eg")
        quiz = _create_quiz_with_questions(db_session, 1, "Quiz 1", [
            {"q_type": "MCQ", "prompt": "Q1", "options": ["A", "B"], "correct_answer": "A"},
        ])
        q_ids = [q.id for q in quiz.questions]
        _submit_attempt(db_session, student, quiz, {q_ids[0]: "A"})

        sync_gradebook_to_excel(db_session, gradebook_path)

        from openpyxl import load_workbook
        wb = load_workbook(gradebook_path)
        ws = wb.active

        # Find Total column
        total_col = None
        for col in range(1, ws.max_column + 1):
            if ws.cell(row=1, column=col).value == "Total":
                total_col = col
                break

        assert total_col is not None
        total_cell = ws.cell(row=2, column=total_col).value
        assert isinstance(total_cell, str)
        assert total_cell.startswith("=SUM(")

    def test_pending_review_leaves_blank(self, db_session, gradebook_path):
        """PENDING_REVIEW attempts should leave cells blank."""
        student = _create_student(db_session, "111111", "Student A", "a111111@nmu.edu.eg")
        quiz = _create_quiz_with_questions(db_session, 1, "Quiz 1", [
            {"q_type": "SHORT", "prompt": "Explain X", "correct_answer": "Reference", "points": 5.0},
        ])
        q_ids = [q.id for q in quiz.questions]
        _submit_attempt(db_session, student, quiz, {q_ids[0]: "My answer"})

        sync_gradebook_to_excel(db_session, gradebook_path)

        from openpyxl import load_workbook
        wb = load_workbook(gradebook_path)
        ws = wb.active

        # Quiz 1 column should be blank for pending review
        quiz1_col = None
        for col in range(1, ws.max_column + 1):
            if ws.cell(row=1, column=col).value == "Quiz 1":
                quiz1_col = col
                break

        assert quiz1_col is not None
        assert ws.cell(row=2, column=quiz1_col).value is None
