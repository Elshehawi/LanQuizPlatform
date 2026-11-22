"""SQLAlchemy ORM models for the quiz platform."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String(50), unique=True, nullable=True)  # Required for STUDENT, null for TUTOR
    full_name = Column(String(200), nullable=False)
    email = Column(String(200), unique=True, index=True, nullable=False)
    password_hash = Column(String(500), nullable=False)
    role = Column(SAEnum("STUDENT", "TUTOR", name="user_role"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    attempts = relationship("Attempt", back_populates="student", lazy="selectin")
    courses_created = relationship("Course", back_populates="creator", lazy="selectin")


class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False)
    title = Column(String(200), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    creator = relationship("User", back_populates="courses_created")
    quizzes = relationship("Quiz", back_populates="course", lazy="selectin")


class Quiz(Base):
    __tablename__ = "quizzes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    course_id = Column(Integer, ForeignKey("courses.id"), default=1, nullable=False)
    quiz_number = Column(Integer, nullable=False)
    title = Column(String(300), nullable=False)
    duration_mins = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    course = relationship("Course", back_populates="quizzes")
    questions = relationship("Question", back_populates="quiz", lazy="selectin",
                             cascade="all, delete-orphan")
    attempts = relationship("Attempt", back_populates="quiz", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("course_id", "quiz_number", name="uq_course_quiz_number"),
    )


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    quiz_id = Column(Integer, ForeignKey("quizzes.id"), nullable=False)
    q_type = Column(SAEnum("MCQ", "TF", "SHORT", name="question_type"), nullable=False)
    prompt = Column(Text, nullable=False)
    options_json = Column(Text, nullable=True)  # JSON string: list of options
    correct_answer = Column(Text, nullable=False)
    points = Column(Float, default=1.0)

    quiz = relationship("Quiz", back_populates="questions")
    answers = relationship("Answer", back_populates="question", lazy="selectin")


class Attempt(Base):
    __tablename__ = "attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    quiz_id = Column(Integer, ForeignKey("quizzes.id"), nullable=False)
    student_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    submitted_at = Column(DateTime, nullable=True)
    status = Column(
        SAEnum("IN_PROGRESS", "PENDING_REVIEW", "GRADED", name="attempt_status"),
        default="IN_PROGRESS",
        nullable=False,
    )
    total_score = Column(Float, default=0.0)

    quiz = relationship("Quiz", back_populates="attempts")
    student = relationship("User", back_populates="attempts")
    answers = relationship("Answer", back_populates="attempt", lazy="selectin",
                           cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("quiz_id", "student_user_id", name="uq_quiz_student"),
    )


class Answer(Base):
    __tablename__ = "answers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    attempt_id = Column(Integer, ForeignKey("attempts.id"), nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    student_response = Column(Text, nullable=True)
    points_awarded = Column(Float, default=0.0)
    is_graded = Column(Boolean, default=False)

    attempt = relationship("Attempt", back_populates="answers")
    question = relationship("Question", back_populates="answers")
