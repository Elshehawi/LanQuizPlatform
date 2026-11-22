"""Shared Pydantic request/response DTOs used by server and client."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    STUDENT = "STUDENT"
    TUTOR = "TUTOR"


class QuestionType(str, Enum):
    MCQ = "MCQ"
    TF = "TF"
    SHORT = "SHORT"


class AttemptStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_REVIEW = "PENDING_REVIEW"
    GRADED = "GRADED"


# ── Auth Schemas ─────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=200)
    email: str = Field(..., min_length=5, max_length=200)
    password: str = Field(..., min_length=4, max_length=200)
    role: UserRole = UserRole.STUDENT
    student_id: Optional[str] = None
    tutor_access_code: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    role: UserRole
    full_name: str


# ── Quiz Schemas ─────────────────────────────────────────────────────────────

class QuestionCreate(BaseModel):
    q_type: QuestionType
    prompt: str = Field(..., min_length=1)
    options_json: Optional[List[str]] = None
    correct_answer: str = Field(..., min_length=1)
    points: float = Field(default=1.0, ge=0.0)


class QuizCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    quiz_number: int = Field(..., ge=1)
    duration_mins: int = Field(..., ge=1, le=300)
    questions: List[QuestionCreate] = Field(..., min_length=1)


class QuestionOut(BaseModel):
    id: int
    q_type: QuestionType
    prompt: str
    options_json: Optional[List[str]] = None
    points: float

    model_config = {"from_attributes": True}


class QuizOut(BaseModel):
    id: int
    title: str
    quiz_number: int
    duration_mins: int
    is_active: bool
    created_at: Optional[datetime] = None
    question_count: Optional[int] = None

    model_config = {"from_attributes": True}


class QuizDetailOut(BaseModel):
    id: int
    title: str
    quiz_number: int
    duration_mins: int
    is_active: bool
    questions: List[QuestionOut] = []

    model_config = {"from_attributes": True}


# ── Attempt Schemas ──────────────────────────────────────────────────────────

class StartAttemptResponse(BaseModel):
    attempt_id: int
    started_at: datetime
    duration_mins: int
    questions: List[QuestionOut]


class AnswerSubmission(BaseModel):
    question_id: int
    student_response: Optional[str] = None


class SubmitAttemptRequest(BaseModel):
    answers: List[AnswerSubmission]


class DraftSaveRequest(BaseModel):
    answers: List[AnswerSubmission]


class AttemptResultOut(BaseModel):
    attempt_id: int
    quiz_title: str
    status: AttemptStatus
    total_score: float
    max_score: float
    submitted_at: Optional[datetime] = None


# ── Grading Schemas ──────────────────────────────────────────────────────────

class PendingAnswerOut(BaseModel):
    answer_id: int
    attempt_id: int
    student_name: str
    student_id_str: Optional[str] = None
    question_prompt: str
    correct_answer: str  # rubric/reference
    student_response: Optional[str] = None
    max_points: float

    model_config = {"from_attributes": True}


class GradeAnswerRequest(BaseModel):
    answer_id: int
    points_awarded: float


class GradeBatchRequest(BaseModel):
    grades: List[GradeAnswerRequest]


# ── General ──────────────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    message: str
    detail: Optional[str] = None


class QuizToggleRequest(BaseModel):
    is_active: bool
