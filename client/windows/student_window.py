"""Student window — quiz browsing, taking, and results."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from shared import config
from client.api_client import APIClient

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
#  Main Student Window
# ═══════════════════════════════════════════════════════════════════════════════


class StudentWindow(QMainWindow):
    """Main window shown to authenticated students."""

    def __init__(self, api_client: APIClient, user_info: dict, parent=None):
        super().__init__(parent)
        self.api = api_client
        self.user_info = user_info

        self.setWindowTitle(f"Quiz Platform — {user_info.get('full_name', 'Student')}")
        self.setMinimumSize(900, 620)

        # ── Central stacked widget (tabs view ↔ quiz‑taking view) ────────
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        # Page 0: Tab view
        self._tabs_page = QWidget()
        tabs_layout = QVBoxLayout(self._tabs_page)

        # Header
        header = QLabel(f"Welcome, {user_info.get('full_name', 'Student')}")
        header.setObjectName("titleLabel")
        tabs_layout.addWidget(header)

        self._tabs = QTabWidget()
        tabs_layout.addWidget(self._tabs)

        # Build tabs
        self._build_quizzes_tab()
        self._build_results_tab()

        self._stack.addWidget(self._tabs_page)

        # Page 1: Quiz‑taking widget (created lazily)
        self._quiz_view: Optional[_QuizTakingView] = None

        # ── Status bar ───────────────────────────────────────────────────
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        self._status_conn = QLabel(f"Server: {self.api.base_url}")
        self._status_conn.setObjectName("statusLabel")
        self._status_save = QLabel("")
        status_bar.addPermanentWidget(self._status_conn)
        status_bar.addPermanentWidget(self._status_save)

        # Initial data load
        self._refresh_quizzes()
        self._refresh_results()

    # ── Tab 1: Available Quizzes ─────────────────────────────────────────

    def _build_quizzes_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        refresh_btn = QPushButton("⟳  Refresh")
        refresh_btn.setObjectName("secondaryButton")
        refresh_btn.setFixedWidth(130)
        refresh_btn.clicked.connect(self._refresh_quizzes)

        layout.addWidget(refresh_btn, alignment=Qt.AlignRight)

        self._quiz_table = QTableWidget(0, 6)
        self._quiz_table.setHorizontalHeaderLabels(
            ["Quiz #", "Title", "Duration", "Questions", "Status", "Action"]
        )
        self._quiz_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._quiz_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._quiz_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._quiz_table.verticalHeader().setVisible(False)
        layout.addWidget(self._quiz_table)

        self._tabs.addTab(page, "📝  Available Quizzes")

    def _build_results_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        refresh_btn = QPushButton("⟳  Refresh")
        refresh_btn.setObjectName("secondaryButton")
        refresh_btn.setFixedWidth(130)
        refresh_btn.clicked.connect(self._refresh_results)

        layout.addWidget(refresh_btn, alignment=Qt.AlignRight)

        self._results_table = QTableWidget(0, 5)
        self._results_table.setHorizontalHeaderLabels(
            ["Quiz Title", "Status", "Score", "Max Score", "Submitted At"]
        )
        self._results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._results_table.verticalHeader().setVisible(False)
        layout.addWidget(self._results_table)

        self._tabs.addTab(page, "📊  My Results")

    # ── Data fetching ────────────────────────────────────────────────────

    @Slot()
    def _refresh_quizzes(self):
        try:
            quizzes = self.api.list_quizzes(active_only=True)
            attempts = self.api.my_attempts()
        except Exception as exc:
            self._show_error("Failed to load quizzes", exc)
            return

        # Build a lookup: quiz_id → latest attempt info
        attempt_map: dict[int, dict] = {}
        for att in attempts:
            qid = att.get("quiz_id") or att.get("quiz_title")  # fallback
            # Attempts endpoint returns quiz_title; map attempt_id-based lookup
            # We'll match by quiz_title below if quiz_id absent
            attempt_map.setdefault(att.get("quiz_title", ""), []).append(att)

        self._quiz_table.setRowCount(len(quizzes))
        for row, q in enumerate(quizzes):
            quiz_id = q["id"]
            title = q.get("title", "")
            dur = q.get("duration_mins", "?")
            qcount = q.get("question_count", "?")
            quiz_num = q.get("quiz_number", row + 1)

            # Determine status from attempts list
            matched = attempt_map.get(title, [])
            status_text = "Not Started"
            has_in_progress = False
            has_submitted = False
            has_graded = False
            best_score: Optional[float] = None
            max_score: Optional[float] = None
            for a in matched:
                s = a.get("status", "")
                if s == "IN_PROGRESS":
                    has_in_progress = True
                elif s == "PENDING_REVIEW":
                    has_submitted = True
                elif s == "GRADED":
                    has_graded = True
                    best_score = a.get("total_score")
                    max_score = a.get("max_score")

            if has_graded:
                status_text = f"Graded ({best_score}/{max_score})"
            elif has_submitted:
                status_text = "Submitted"
            elif has_in_progress:
                status_text = "In Progress"

            # Populate row
            self._quiz_table.setItem(row, 0, QTableWidgetItem(str(quiz_num)))
            self._quiz_table.setItem(row, 1, QTableWidgetItem(title))
            self._quiz_table.setItem(row, 2, QTableWidgetItem(f"{dur} min"))
            self._quiz_table.setItem(row, 3, QTableWidgetItem(str(qcount)))
            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignCenter)
            self._quiz_table.setItem(row, 4, status_item)

            # Action button
            if has_in_progress:
                btn = QPushButton("Resume")
                btn.setObjectName("primaryButton")
                btn.clicked.connect(lambda _=False, qid=quiz_id: self._start_quiz(qid))
            elif has_graded:
                btn = QPushButton("View Score")
                btn.setObjectName("successButton")
                btn.clicked.connect(lambda _=False: self._tabs.setCurrentIndex(1))
            elif has_submitted:
                btn = QPushButton("Submitted")
                btn.setObjectName("secondaryButton")
                btn.setEnabled(False)
            else:
                btn = QPushButton("Start")
                btn.setObjectName("primaryButton")
                btn.clicked.connect(lambda _=False, qid=quiz_id: self._start_quiz(qid))
            self._quiz_table.setCellWidget(row, 5, btn)

        self.statusBar().showMessage("Quizzes refreshed", 3000)

    @Slot()
    def _refresh_results(self):
        try:
            attempts = self.api.my_attempts()
        except Exception as exc:
            self._show_error("Failed to load results", exc)
            return

        self._results_table.setRowCount(len(attempts))
        for row, a in enumerate(attempts):
            self._results_table.setItem(row, 0, QTableWidgetItem(a.get("quiz_title", "")))
            self._results_table.setItem(row, 1, QTableWidgetItem(a.get("status", "")))
            self._results_table.setItem(row, 2, QTableWidgetItem(str(a.get("total_score", ""))))
            self._results_table.setItem(row, 3, QTableWidgetItem(str(a.get("max_score", ""))))
            submitted = a.get("submitted_at", "")
            if submitted:
                try:
                    dt = datetime.fromisoformat(str(submitted))
                    submitted = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    pass
            self._results_table.setItem(row, 4, QTableWidgetItem(str(submitted)))

        self.statusBar().showMessage("Results refreshed", 3000)

    # ── Quiz start / resume ──────────────────────────────────────────────

    def _start_quiz(self, quiz_id: int):
        try:
            data = self.api.start_attempt(quiz_id)
        except Exception as exc:
            self._show_error("Failed to start quiz attempt", exc)
            return

        self._enter_quiz_view(data)

    def _enter_quiz_view(self, attempt_data: dict):
        """Switch the stacked widget to the quiz‑taking view."""
        # Remove old quiz view if present
        if self._quiz_view is not None:
            self._stack.removeWidget(self._quiz_view)
            self._quiz_view.cleanup()
            self._quiz_view.deleteLater()

        self._quiz_view = _QuizTakingView(
            api_client=self.api,
            attempt_data=attempt_data,
            status_label=self._status_save,
            on_finished=self._on_quiz_finished,
        )
        self._stack.addWidget(self._quiz_view)
        self._stack.setCurrentWidget(self._quiz_view)

    def _on_quiz_finished(self):
        """Return to the tabs view after quiz submission."""
        if self._quiz_view is not None:
            self._stack.removeWidget(self._quiz_view)
            self._quiz_view.cleanup()
            self._quiz_view.deleteLater()
            self._quiz_view = None

        self._stack.setCurrentIndex(0)
        self._refresh_quizzes()
        self._refresh_results()

    # ── Helpers ──────────────────────────────────────────────────────────

    def _show_error(self, title: str, exc: Exception):
        logger.exception(title)
        QMessageBox.warning(self, title, f"{title}:\n{exc}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Quiz‑Taking View  (replaces main content while in a quiz)
# ═══════════════════════════════════════════════════════════════════════════════


class _QuizTakingView(QWidget):
    """Full quiz‑taking interface shown while a student is answering."""

    def __init__(
        self,
        api_client: APIClient,
        attempt_data: dict,
        status_label: QLabel,
        on_finished,
        parent=None,
    ):
        super().__init__(parent)
        self.api = api_client
        self.attempt_id: int = attempt_data["attempt_id"]
        self.started_at = datetime.fromisoformat(str(attempt_data["started_at"]))
        # Ensure timezone‑aware
        if self.started_at.tzinfo is None:
            self.started_at = self.started_at.replace(tzinfo=timezone.utc)
        self.duration_mins: int = attempt_data["duration_mins"]
        self.questions: list[dict] = attempt_data["questions"]
        self._status_label = status_label
        self._on_finished = on_finished

        # answers: question_id → student_response string
        self.answers: dict[int, str] = {}
        self._current_idx = 0
        self._submitted = False

        # Try to restore answers from local recovery
        self._recovery_path = config.RECOVERY_DIR / f"attempt_{self.attempt_id}.json"
        self._load_recovery()

        self._build_ui()
        self._show_question(0)

        # ── Timers ───────────────────────────────────────────────────────
        # Countdown timer — tick every second
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._tick)
        self._countdown_timer.start()

        # Auto‑save timer
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.setInterval(config.AUTO_SAVE_INTERVAL_SECONDS * 1000)
        self._auto_save_timer.timeout.connect(self._auto_save)
        self._auto_save_timer.start()

        # Initial tick to set the timer display
        self._tick()

    # ── UI construction ──────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)

        # ── Top bar: timer + submit ──────────────────────────────────────
        top_bar = QHBoxLayout()

        self._timer_label = QLabel("⏱  --:--")
        self._timer_label.setObjectName("timerLabel")
        top_bar.addWidget(self._timer_label)

        top_bar.addStretch()

        submit_btn = QPushButton("✓  Submit Quiz")
        submit_btn.setObjectName("dangerButton")
        submit_btn.clicked.connect(self._confirm_submit)
        top_bar.addWidget(submit_btn)

        root.addLayout(top_bar)

        # ── Question navigation bar ──────────────────────────────────────
        nav_bar = QHBoxLayout()
        self._nav_buttons: list[QPushButton] = []
        for i, q in enumerate(self.questions):
            btn = QPushButton(str(i + 1))
            btn.setFixedSize(36, 36)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, idx=i: self._show_question(idx))
            self._nav_buttons.append(btn)
            nav_bar.addWidget(btn)
        nav_bar.addStretch()
        root.addLayout(nav_bar)

        # ── Question display area (stacked) ──────────────────────────────
        self._question_stack = QStackedWidget()
        self._question_pages: list[_QuestionPage] = []

        for i, q in enumerate(self.questions):
            page = _QuestionPage(q, self.answers)
            self._question_pages.append(page)
            self._question_stack.addWidget(page)

        root.addWidget(self._question_stack, stretch=1)

        # ── Prev / Next buttons ──────────────────────────────────────────
        bottom = QHBoxLayout()
        self._prev_btn = QPushButton("←  Previous")
        self._prev_btn.setObjectName("secondaryButton")
        self._prev_btn.clicked.connect(self._prev_question)
        bottom.addWidget(self._prev_btn)

        bottom.addStretch()

        self._next_btn = QPushButton("Next  →")
        self._next_btn.setObjectName("primaryButton")
        self._next_btn.clicked.connect(self._next_question)
        bottom.addWidget(self._next_btn)

        root.addLayout(bottom)

    # ── Question navigation ──────────────────────────────────────────────

    def _show_question(self, idx: int):
        # Save current answer before switching
        if 0 <= self._current_idx < len(self._question_pages):
            self._question_pages[self._current_idx].save_answer()

        self._current_idx = idx
        self._question_stack.setCurrentIndex(idx)

        # Update nav‑button highlights
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == idx)
            # Colour answered questions
            q_id = self.questions[i]["id"]
            if q_id in self.answers and self.answers[q_id]:
                btn.setStyleSheet("background-color: #059669; color: white; border-radius: 18px;")
            elif i == idx:
                btn.setStyleSheet("background-color: #2563eb; color: white; border-radius: 18px;")
            else:
                btn.setStyleSheet("")

        # Enable / disable prev/next
        self._prev_btn.setEnabled(idx > 0)
        self._next_btn.setEnabled(idx < len(self.questions) - 1)

    @Slot()
    def _prev_question(self):
        if self._current_idx > 0:
            self._show_question(self._current_idx - 1)

    @Slot()
    def _next_question(self):
        if self._current_idx < len(self.questions) - 1:
            self._show_question(self._current_idx + 1)

    # ── Timer ────────────────────────────────────────────────────────────

    @Slot()
    def _tick(self):
        if self._submitted:
            return

        now = datetime.now(timezone.utc)
        end_time = self.started_at + __import__("datetime").timedelta(minutes=self.duration_mins)
        remaining = (end_time - now).total_seconds()

        if remaining <= 0:
            self._timer_label.setText("⏱  00:00  — Time's up!")
            self._do_submit(auto=True)
            return

        mins, secs = divmod(int(remaining), 60)
        self._timer_label.setText(f"⏱  {mins:02d}:{secs:02d}")

        # Visual urgency when < 60 s
        if remaining < 60:
            self._timer_label.setStyleSheet(
                "font-size:18px; font-weight:bold; color:#fff; "
                "background-color:#dc2626; border-radius:6px; padding:8px 16px;"
            )

    # ── Auto‑save ────────────────────────────────────────────────────────

    @Slot()
    def _auto_save(self):
        if self._submitted:
            return

        # Save current page answer first
        if 0 <= self._current_idx < len(self._question_pages):
            self._question_pages[self._current_idx].save_answer()

        # 1. Local recovery file
        self._save_recovery()

        # 2. POST draft to server
        try:
            self.api.save_draft(self.attempt_id, self._answers_payload())
            self._status_label.setText("Auto‑saved ✓")
        except Exception as exc:
            logger.warning("Draft save failed (will retry): %s", exc)
            self._status_label.setText("Auto‑save pending…")

    def _answers_payload(self) -> list[dict]:
        return [
            {"question_id": qid, "student_response": resp}
            for qid, resp in self.answers.items()
        ]

    # ── Recovery file I/O ────────────────────────────────────────────────

    def _save_recovery(self):
        try:
            config.RECOVERY_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "attempt_id": self.attempt_id,
                "answers": {str(k): v for k, v in self.answers.items()},
            }
            self._recovery_path.write_text(json.dumps(payload), encoding="utf-8")
        except Exception as exc:
            logger.warning("Recovery file write failed: %s", exc)

    def _load_recovery(self):
        try:
            if self._recovery_path.exists():
                data = json.loads(self._recovery_path.read_text(encoding="utf-8"))
                for k, v in data.get("answers", {}).items():
                    self.answers[int(k)] = v
        except Exception as exc:
            logger.warning("Recovery file load failed: %s", exc)

    def _delete_recovery(self):
        try:
            if self._recovery_path.exists():
                self._recovery_path.unlink()
        except Exception:
            pass

    # ── Submit ───────────────────────────────────────────────────────────

    @Slot()
    def _confirm_submit(self):
        reply = QMessageBox.question(
            self,
            "Submit Quiz",
            "Are you sure you want to submit? You cannot change your answers after submission.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._do_submit(auto=False)

    def _do_submit(self, auto: bool = False):
        if self._submitted:
            return
        self._submitted = True

        # Gather all answers from every page
        for page in self._question_pages:
            page.save_answer()

        payload = self._answers_payload()

        try:
            self.api.submit_attempt(self.attempt_id, payload)
            self._delete_recovery()
            msg = "Quiz auto‑submitted (time ran out)." if auto else "Quiz submitted successfully!"
            QMessageBox.information(self, "Submitted", msg)
        except Exception as exc:
            # Save locally so nothing is lost
            self._save_recovery()
            logger.exception("Submit failed")
            QMessageBox.warning(
                self,
                "Submission Error",
                f"Could not reach server. Your answers are saved locally and will be retried.\n\n{exc}",
            )
            self._submitted = False
            return

        self._on_finished()

    # ── Cleanup ──────────────────────────────────────────────────────────

    def cleanup(self):
        """Stop timers before widget is destroyed."""
        self._countdown_timer.stop()
        self._auto_save_timer.stop()


# ═══════════════════════════════════════════════════════════════════════════════
#  Individual Question Page
# ═══════════════════════════════════════════════════════════════════════════════


class _QuestionPage(QWidget):
    """Displays a single question and captures the student's answer."""

    def __init__(self, question: dict, answers: dict[int, str], parent=None):
        super().__init__(parent)
        self.q = question
        self.q_id: int = question["id"]
        self.q_type: str = question["q_type"]
        self.answers = answers  # shared mutable dict

        layout = QVBoxLayout(self)

        # Prompt
        prompt_label = QLabel(question["prompt"])
        prompt_label.setWordWrap(True)
        prompt_label.setStyleSheet("font-size: 15px; padding: 8px 0;")
        layout.addWidget(prompt_label)

        # Points
        pts = question.get("points", 1)
        pts_label = QLabel(f"({pts} point{'s' if pts != 1 else ''})")
        pts_label.setObjectName("subtitleLabel")
        layout.addWidget(pts_label)

        self._btn_group: Optional[QButtonGroup] = None
        self._text_edit: Optional[QTextEdit] = None
        self._radio_buttons: list[QRadioButton] = []

        if self.q_type in ("MCQ", "TF"):
            self._btn_group = QButtonGroup(self)
            options = question.get("options_json") or []
            if self.q_type == "TF" and not options:
                options = ["True", "False"]
            for opt in options:
                rb = QRadioButton(opt)
                rb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                self._radio_buttons.append(rb)
                self._btn_group.addButton(rb)
                layout.addWidget(rb)

            # Restore saved answer
            saved = self.answers.get(self.q_id, "")
            if saved:
                for rb in self._radio_buttons:
                    if rb.text() == saved:
                        rb.setChecked(True)
                        break
        else:
            # SHORT answer
            self._text_edit = QTextEdit()
            self._text_edit.setPlaceholderText("Type your answer here…")
            self._text_edit.setMaximumHeight(180)
            layout.addWidget(self._text_edit)

            saved = self.answers.get(self.q_id, "")
            if saved:
                self._text_edit.setPlainText(saved)

        layout.addStretch()

    def save_answer(self):
        """Persist the current answer into the shared answers dict."""
        if self._btn_group is not None:
            checked = self._btn_group.checkedButton()
            if checked:
                self.answers[self.q_id] = checked.text()
        elif self._text_edit is not None:
            text = self._text_edit.toPlainText().strip()
            if text:
                self.answers[self.q_id] = text
