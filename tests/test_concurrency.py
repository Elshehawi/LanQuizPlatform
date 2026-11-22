"""
Simulated 30-student concurrent submission stress test under SQLite WAL mode.
"""

import sys
import json
import threading
import time
from pathlib import Path
from datetime import datetime, timezone

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from server.models import Base, User, Course, Quiz, Question, Attempt, Answer
from server.auth import hash_password
from shared.config import DEFAULT_COURSE_ID, DEFAULT_COURSE_CODE, DEFAULT_COURSE_TITLE


def _set_wal_pragmas(dbapi_connection, _connection_record):
    """Set SQLite WAL mode pragmas."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    cursor.close()


@pytest.fixture
def wal_db(tmp_path):
    """Create a WAL-mode SQLite database on disk (not in-memory)."""
    db_path = tmp_path / "test_concurrent.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
    event.listen(engine, "connect", _set_wal_pragmas)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    # Seed default course
    with Session() as session:
        course = Course(id=DEFAULT_COURSE_ID, code=DEFAULT_COURSE_CODE, title=DEFAULT_COURSE_TITLE)
        session.add(course)
        session.commit()

    return engine, Session


class TestConcurrentSubmissions:
    """Test that 30 concurrent students can submit without database lock errors."""

    def test_30_concurrent_submissions(self, wal_db):
        """30 students submitting the same quiz concurrently should all succeed."""
        engine, Session = wal_db

        # Setup: create 30 students and a quiz
        with Session() as session:
            students = []
            for i in range(1, 31):
                student = User(
                    student_id=f"{100000 + i}",
                    full_name=f"Student {i}",
                    email=f"student{100000 + i}@nmu.edu.eg",
                    password_hash=hash_password("testpass"),
                    role="STUDENT",
                )
                session.add(student)
                students.append(student)

            session.commit()
            for s in students:
                session.refresh(s)
            student_ids = [s.id for s in students]

            # Create quiz with mixed questions
            quiz = Quiz(
                course_id=DEFAULT_COURSE_ID,
                quiz_number=1,
                title="Concurrent Test Quiz",
                duration_mins=30,
                is_active=True,
            )
            session.add(quiz)
            session.flush()

            q1 = Question(quiz_id=quiz.id, q_type="MCQ", prompt="Q1",
                          options_json=json.dumps(["A", "B", "C", "D"]),
                          correct_answer="A", points=1.0)
            q2 = Question(quiz_id=quiz.id, q_type="TF", prompt="Q2",
                          options_json=json.dumps(["True", "False"]),
                          correct_answer="True", points=1.0)
            q3 = Question(quiz_id=quiz.id, q_type="MCQ", prompt="Q3",
                          options_json=json.dumps(["X", "Y", "Z"]),
                          correct_answer="Y", points=2.0)
            session.add_all([q1, q2, q3])
            session.commit()

            quiz_id = quiz.id
            question_ids = [q1.id, q2.id, q3.id]

        # Concurrent submission
        errors = []
        results = []
        lock = threading.Lock()

        def submit_as_student(student_user_id: int, s_idx: int):
            """Simulate a student starting and submitting a quiz."""
            try:
                with Session() as session:
                    # Start attempt
                    attempt = Attempt(
                        quiz_id=quiz_id,
                        student_user_id=student_user_id,
                        status="IN_PROGRESS",
                    )
                    session.add(attempt)
                    session.flush()

                    # Create answers
                    responses = {
                        question_ids[0]: "A",        # Correct
                        question_ids[1]: "True",     # Correct
                        question_ids[2]: "Y" if s_idx % 2 == 0 else "X",  # Half correct
                    }

                    total_score = 0.0
                    for qid in question_ids:
                        question = session.get(Question, qid)
                        resp = responses.get(qid, "")
                        answer = Answer(
                            attempt_id=attempt.id,
                            question_id=qid,
                            student_response=resp,
                        )

                        student_resp = (resp or "").strip().lower()
                        correct = question.correct_answer.strip().lower()
                        if student_resp == correct:
                            answer.points_awarded = question.points
                        else:
                            answer.points_awarded = 0.0
                        answer.is_graded = True
                        total_score += answer.points_awarded

                        session.add(answer)

                    attempt.submitted_at = datetime.now(timezone.utc)
                    attempt.status = "GRADED"
                    attempt.total_score = total_score
                    session.commit()

                    with lock:
                        results.append({
                            "student_id": student_user_id,
                            "attempt_id": attempt.id,
                            "total_score": total_score,
                        })

            except Exception as e:
                with lock:
                    errors.append({
                        "student_id": student_user_id,
                        "error": str(e),
                        "type": type(e).__name__,
                    })

        # Launch all 30 threads simultaneously
        threads = []
        for idx, sid in enumerate(student_ids):
            t = threading.Thread(target=submit_as_student, args=(sid, idx))
            threads.append(t)

        # Start all threads at roughly the same time
        for t in threads:
            t.start()

        # Wait for all to complete
        for t in threads:
            t.join(timeout=30)

        # Assertions
        assert len(errors) == 0, f"Database errors occurred: {errors}"
        assert len(results) == 30, f"Only {len(results)} of 30 submissions completed"

        # Verify all attempts are in database
        with Session() as session:
            attempts = session.query(Attempt).filter(Attempt.quiz_id == quiz_id).all()
            assert len(attempts) == 30

            graded_count = sum(1 for a in attempts if a.status == "GRADED")
            assert graded_count == 30

    def test_concurrent_draft_saves(self, wal_db):
        """Multiple students saving drafts concurrently should not conflict."""
        engine, Session = wal_db

        with Session() as session:
            # Create 10 students
            students = []
            for i in range(1, 11):
                student = User(
                    student_id=f"{200000 + i}",
                    full_name=f"Draft Student {i}",
                    email=f"draft{200000 + i}@nmu.edu.eg",
                    password_hash=hash_password("testpass"),
                    role="STUDENT",
                )
                session.add(student)
                students.append(student)

            # Create quiz
            quiz = Quiz(
                course_id=DEFAULT_COURSE_ID,
                quiz_number=99,
                title="Draft Test Quiz",
                duration_mins=30,
                is_active=True,
            )
            session.add(quiz)
            session.flush()

            q1 = Question(quiz_id=quiz.id, q_type="MCQ", prompt="DQ1",
                          options_json=json.dumps(["A", "B"]),
                          correct_answer="A", points=1.0)
            session.add(q1)
            session.commit()

            quiz_id = quiz.id
            q1_id = q1.id

            # Create attempts with empty answers
            attempt_ids = []
            for student in students:
                session.refresh(student)
                attempt = Attempt(
                    quiz_id=quiz_id,
                    student_user_id=student.id,
                    status="IN_PROGRESS",
                )
                session.add(attempt)
                session.flush()
                answer = Answer(
                    attempt_id=attempt.id,
                    question_id=q1_id,
                    student_response=None,
                )
                session.add(answer)
                attempt_ids.append((attempt.id, student.id))

            session.commit()

        # Concurrent draft saves (simulate auto-save every 10s)
        errors = []
        lock = threading.Lock()

        def save_drafts(attempt_id: int, student_user_id: int):
            try:
                for iteration in range(5):  # Simulate 5 auto-saves
                    with Session() as session:
                        answer = session.query(Answer).filter(
                            Answer.attempt_id == attempt_id,
                            Answer.question_id == q1_id,
                        ).first()
                        if answer:
                            answer.student_response = f"Draft-{iteration}-by-{student_user_id}"
                            session.commit()
                    time.sleep(0.01)  # Small delay to increase contention
            except Exception as e:
                with lock:
                    errors.append({"attempt_id": attempt_id, "error": str(e)})

        threads = []
        for aid, sid in attempt_ids:
            t = threading.Thread(target=save_drafts, args=(aid, sid))
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Draft save errors: {errors}"

        # Verify all drafts were saved
        with Session() as session:
            for aid, sid in attempt_ids:
                answer = session.query(Answer).filter(
                    Answer.attempt_id == aid,
                    Answer.question_id == q1_id,
                ).first()
                assert answer is not None
                assert answer.student_response is not None
                assert answer.student_response.startswith("Draft-")
