"""Tutor administration window — dashboard, quiz builder, review queue, gradebook."""

from __future__ import annotations

import socket
import traceback
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from client.api_client import APIClient
from shared.config import GRADEBOOK_PATH, SERVER_PORT, TUTOR_CODE_PATH


# ═══════════════════════════════════════════════════════════════════════════════
#  Background worker thread
# ═══════════════════════════════════════════════════════════════════════════════

class _Worker(QThread):
    """Run a callable on a background thread and emit the result / error."""

    finished = Signal(object)  # emits the return value
    errored = Signal(str)      # emits an error description

    def __init__(self, fn, *args, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._args = args

    def run(self):  # noqa: D401 (Qt override)
        try:
            result = self._fn(*self._args)
            self.finished.emit(result)
        except Exception as exc:
            self.errored.emit(str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
#  Helper: get the LAN IP of this machine
# ═══════════════════════════════════════════════════════════════════════════════

def _get_lan_ip() -> str:
    """Return the best-guess LAN IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ═══════════════════════════════════════════════════════════════════════════════
#  Question Editor Widget (used inside Quiz Builder)
# ═══════════════════════════════════════════════════════════════════════════════

class _QuestionEditor(QFrame):
    """Editor for a single question inside the Quiz Builder."""

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.setObjectName("cardFrame")
        self._index = index
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Header
        header = QHBoxLayout()
        self._title_label = QLabel(f"Question {self._index + 1}")
        self._title_label.setObjectName("subtitleLabel")
        self._title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        header.addWidget(self._title_label)
        header.addStretch()

        self._type_combo = QComboBox()
        self._type_combo.addItems(["MCQ", "TF", "SHORT"])
        self._type_combo.currentTextChanged.connect(self._on_type_changed)
        header.addWidget(QLabel("Type:"))
        header.addWidget(self._type_combo)

        self._points_spin = QDoubleSpinBox()
        self._points_spin.setRange(0.0, 100.0)
        self._points_spin.setValue(1.0)
        self._points_spin.setSingleStep(0.5)
        header.addWidget(QLabel("Points:"))
        header.addWidget(self._points_spin)
        layout.addLayout(header)

        # Prompt
        self._prompt_edit = QTextEdit()
        self._prompt_edit.setPlaceholderText("Enter the question prompt …")
        self._prompt_edit.setMaximumHeight(80)
        layout.addWidget(self._prompt_edit)

        # --- MCQ options area ---
        self._mcq_group = QGroupBox("MCQ Options")
        mcq_layout = QVBoxLayout(self._mcq_group)
        self._option_edits: list[QLineEdit] = []
        self._mcq_btn_group = QButtonGroup(self)
        for i in range(4):
            row = QHBoxLayout()
            radio = QRadioButton()
            self._mcq_btn_group.addButton(radio, i)
            row.addWidget(radio)
            opt_edit = QLineEdit()
            opt_edit.setPlaceholderText(f"Option {chr(65 + i)}")
            row.addWidget(opt_edit)
            mcq_layout.addLayout(row)
            self._option_edits.append(opt_edit)
        # Pre-select first radio
        self._mcq_btn_group.button(0).setChecked(True)
        layout.addWidget(self._mcq_group)

        # --- TF area ---
        self._tf_group = QGroupBox("True / False")
        tf_layout = QHBoxLayout(self._tf_group)
        self._tf_btn_group = QButtonGroup(self)
        self._tf_true = QRadioButton("True")
        self._tf_false = QRadioButton("False")
        self._tf_btn_group.addButton(self._tf_true, 0)
        self._tf_btn_group.addButton(self._tf_false, 1)
        self._tf_true.setChecked(True)
        tf_layout.addWidget(self._tf_true)
        tf_layout.addWidget(self._tf_false)
        tf_layout.addStretch()
        layout.addWidget(self._tf_group)

        # --- SHORT area ---
        self._short_group = QGroupBox("Reference Answer / Rubric")
        short_layout = QVBoxLayout(self._short_group)
        self._short_edit = QTextEdit()
        self._short_edit.setPlaceholderText("Reference answer or rubric for grading …")
        self._short_edit.setMaximumHeight(70)
        short_layout.addWidget(self._short_edit)
        layout.addWidget(self._short_group)

        # Initialize visibility
        self._on_type_changed(self._type_combo.currentText())

    # ── Slots ─────────────────────────────────────────────────────────────

    def _on_type_changed(self, q_type: str):
        self._mcq_group.setVisible(q_type == "MCQ")
        self._tf_group.setVisible(q_type == "TF")
        self._short_group.setVisible(q_type == "SHORT")

    # ── Data helpers ──────────────────────────────────────────────────────

    def set_index(self, idx: int):
        self._index = idx
        self._title_label.setText(f"Question {idx + 1}")

    def to_dict(self) -> dict:
        """Convert the editor state to a QuestionCreate-compatible dict."""
        q_type = self._type_combo.currentText()
        prompt = self._prompt_edit.toPlainText().strip()
        points = self._points_spin.value()

        data: dict = {
            "q_type": q_type,
            "prompt": prompt,
            "points": points,
        }

        if q_type == "MCQ":
            options = [e.text().strip() for e in self._option_edits]
            checked_id = self._mcq_btn_group.checkedId()
            data["options_json"] = options
            data["correct_answer"] = options[checked_id] if 0 <= checked_id < len(options) else ""
        elif q_type == "TF":
            data["correct_answer"] = "True" if self._tf_true.isChecked() else "False"
        else:  # SHORT
            data["correct_answer"] = self._short_edit.toPlainText().strip()

        return data


# ═══════════════════════════════════════════════════════════════════════════════
#  Main Tutor Window
# ═══════════════════════════════════════════════════════════════════════════════

class TutorWindow(QMainWindow):
    """Main window for the Tutor role."""

    def __init__(self, api_client: APIClient, user_info: dict, parent=None):
        super().__init__(parent)
        self._api = api_client
        self._user_info = user_info
        self._workers: list[_Worker] = []  # prevent GC
        self._question_editors: list[_QuestionEditor] = []

        self.setWindowTitle(f"LAN Quiz Platform — Tutor ({user_info.get('full_name', '')})")
        self.setMinimumSize(1050, 700)

        self._build_ui()
        self._refresh_dashboard()
        self._refresh_quiz_table()
        self._refresh_review_table()

    # ══════════════════════════════════════════════════════════════════════
    #  UI Construction
    # ══════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)

        # Title
        title = QLabel("Tutor Dashboard")
        title.setObjectName("titleLabel")
        root.addWidget(title)

        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_dashboard_tab(), "📊 Dashboard")
        self._tabs.addTab(self._build_quiz_builder_tab(), "📝 Quiz Builder")
        self._tabs.addTab(self._build_review_tab(), "✏️ Review Queue")
        self._tabs.addTab(self._build_gradebook_tab(), "📗 Gradebook")
        root.addWidget(self._tabs)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        lan_ip = _get_lan_ip()
        self._status_bar.showMessage(
            f"Connected to {self._api.base_url}  |  LAN IP: {lan_ip}:{SERVER_PORT}"
            f"  |  Logged in as {self._user_info.get('full_name', 'Tutor')}"
        )

    # ── Tab 1: Dashboard ─────────────────────────────────────────────────

    def _build_dashboard_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(14)

        # Access code card
        code_card = QFrame()
        code_card.setObjectName("cardFrame")
        cc_layout = QVBoxLayout(code_card)
        cc_layout.addWidget(QLabel("Tutor Access Code"))
        self._access_code_label = QLabel(self._read_tutor_code())
        self._access_code_label.setObjectName("accessCodeLabel")
        self._access_code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cc_layout.addWidget(self._access_code_label)
        layout.addWidget(code_card)

        # Server info card
        info_card = QFrame()
        info_card.setObjectName("cardFrame")
        ic_layout = QVBoxLayout(info_card)
        lan_ip = _get_lan_ip()
        self._server_info_label = QLabel(
            f"Server: {self._api.base_url}  •  LAN IP: {lan_ip}  •  Port: {SERVER_PORT}"
        )
        self._server_info_label.setObjectName("subtitleLabel")
        ic_layout.addWidget(self._server_info_label)
        layout.addWidget(info_card)

        # Stats cards row
        stats_row = QHBoxLayout()
        self._students_label = self._stat_card("Registered Students", "—", stats_row)
        self._quizzes_label = self._stat_card("Active Quizzes", "—", stats_row)
        self._pending_label = self._stat_card("Pending Reviews", "—", stats_row)
        layout.addLayout(stats_row)

        # Refresh
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        refresh_btn = QPushButton("🔄  Refresh Dashboard")
        refresh_btn.setObjectName("secondaryButton")
        refresh_btn.clicked.connect(self._refresh_dashboard)
        btn_row.addWidget(refresh_btn)
        layout.addLayout(btn_row)

        layout.addStretch()
        return tab

    @staticmethod
    def _stat_card(title: str, value: str, parent_layout: QHBoxLayout) -> QLabel:
        """Create a small statistics card and return the value label."""
        card = QFrame()
        card.setObjectName("cardFrame")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        cl = QVBoxLayout(card)
        t = QLabel(title)
        t.setObjectName("subtitleLabel")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(t)
        v = QLabel(value)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.setStyleSheet("font-size: 28px; font-weight: bold; color: #1e40af;")
        cl.addWidget(v)
        parent_layout.addWidget(card)
        return v

    # ── Tab 2: Quiz Builder ──────────────────────────────────────────────

    def _build_quiz_builder_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setSpacing(10)

        # ---- Quiz metadata form ----
        meta_card = QFrame()
        meta_card.setObjectName("cardFrame")
        meta_layout = QVBoxLayout(meta_card)
        meta_layout.addWidget(QLabel("Create New Quiz"))

        form_row1 = QHBoxLayout()
        form_row1.addWidget(QLabel("Title:"))
        self._quiz_title_edit = QLineEdit()
        self._quiz_title_edit.setPlaceholderText("Quiz title …")
        form_row1.addWidget(self._quiz_title_edit, 3)

        form_row1.addWidget(QLabel("Quiz #:"))
        self._quiz_number_spin = QSpinBox()
        self._quiz_number_spin.setRange(1, 999)
        form_row1.addWidget(self._quiz_number_spin, 1)

        form_row1.addWidget(QLabel("Duration (min):"))
        self._quiz_duration_spin = QSpinBox()
        self._quiz_duration_spin.setRange(1, 300)
        self._quiz_duration_spin.setValue(15)
        form_row1.addWidget(self._quiz_duration_spin, 1)
        meta_layout.addLayout(form_row1)

        outer.addWidget(meta_card)

        # ---- Questions scroll area ----
        self._questions_scroll = QScrollArea()
        self._questions_scroll.setWidgetResizable(True)
        self._questions_container = QWidget()
        self._questions_layout = QVBoxLayout(self._questions_container)
        self._questions_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._questions_scroll.setWidget(self._questions_container)
        outer.addWidget(self._questions_scroll, 1)

        # Buttons
        q_btns = QHBoxLayout()
        add_q_btn = QPushButton("➕  Add Question")
        add_q_btn.setObjectName("successButton")
        add_q_btn.clicked.connect(self._add_question_editor)
        q_btns.addWidget(add_q_btn)

        rm_q_btn = QPushButton("➖  Remove Last")
        rm_q_btn.setObjectName("dangerButton")
        rm_q_btn.clicked.connect(self._remove_last_question)
        q_btns.addWidget(rm_q_btn)

        q_btns.addStretch()

        create_btn = QPushButton("🚀  Create Quiz")
        create_btn.setObjectName("primaryButton")
        create_btn.clicked.connect(self._create_quiz)
        q_btns.addWidget(create_btn)
        outer.addLayout(q_btns)

        # ---- Existing quizzes table ----
        outer.addWidget(QLabel("Existing Quizzes"))
        self._quiz_table = QTableWidget(0, 7)
        self._quiz_table.setHorizontalHeaderLabels(
            ["ID", "Quiz #", "Title", "Duration", "Questions", "Active", "Actions"]
        )
        self._quiz_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self._quiz_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._quiz_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        outer.addWidget(self._quiz_table)

        # Add one default question
        self._add_question_editor()

        return tab

    # ── Tab 3: Review Queue ──────────────────────────────────────────────

    def _build_review_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Controls
        ctrl = QHBoxLayout()
        refresh_btn = QPushButton("🔄  Refresh")
        refresh_btn.setObjectName("secondaryButton")
        refresh_btn.clicked.connect(self._refresh_review_table)
        ctrl.addWidget(refresh_btn)
        ctrl.addStretch()

        grade_btn = QPushButton("✅  Grade Selected")
        grade_btn.setObjectName("successButton")
        grade_btn.clicked.connect(self._grade_selected)
        ctrl.addWidget(grade_btn)
        layout.addLayout(ctrl)

        # Table
        self._review_table = QTableWidget(0, 8)
        self._review_table.setHorizontalHeaderLabels([
            "Answer ID", "Student Name", "Student ID",
            "Question", "Reference Answer", "Student Response",
            "Points", "Grade",
        ])
        self._review_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self._review_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        self._review_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch
        )
        self._review_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._review_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._review_table)

        return tab

    # ── Tab 4: Gradebook ─────────────────────────────────────────────────

    def _build_gradebook_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(14)

        # Export controls
        ctrl = QHBoxLayout()
        export_btn = QPushButton("📥  Sync & Export to Excel")
        export_btn.setObjectName("primaryButton")
        export_btn.clicked.connect(self._export_gradebook)
        ctrl.addWidget(export_btn)

        refresh_btn = QPushButton("🔄  Refresh")
        refresh_btn.setObjectName("secondaryButton")
        refresh_btn.clicked.connect(self._refresh_gradebook)
        ctrl.addWidget(refresh_btn)

        ctrl.addStretch()
        layout.addLayout(ctrl)

        # Status card
        status_card = QFrame()
        status_card.setObjectName("cardFrame")
        sc_layout = QVBoxLayout(status_card)
        self._export_status_label = QLabel("No export performed yet.")
        self._export_status_label.setObjectName("subtitleLabel")
        sc_layout.addWidget(self._export_status_label)
        self._gradebook_path_label = QLabel(f"Gradebook path: {GRADEBOOK_PATH}")
        self._gradebook_path_label.setObjectName("subtitleLabel")
        sc_layout.addWidget(self._gradebook_path_label)
        layout.addWidget(status_card)

        # Preview table
        layout.addWidget(QLabel("Attempts Preview"))
        self._gradebook_table = QTableWidget(0, 5)
        self._gradebook_table.setHorizontalHeaderLabels([
            "Attempt ID", "Quiz", "Status", "Score", "Submitted At",
        ])
        self._gradebook_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._gradebook_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._gradebook_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._gradebook_table)

        return tab

    # ══════════════════════════════════════════════════════════════════════
    #  Data helpers
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _read_tutor_code() -> str:
        """Read the tutor access code from the data file."""
        try:
            return TUTOR_CODE_PATH.read_text().strip()
        except Exception:
            return "(unavailable)"

    # ── Async worker launcher ────────────────────────────────────────────

    def _run_async(self, fn, on_done, on_error=None):
        """Run *fn* on a background thread; call *on_done* / *on_error* on the main thread."""
        worker = _Worker(fn)
        worker.finished.connect(on_done)
        worker.errored.connect(on_error or self._show_error)
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.errored.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    # ══════════════════════════════════════════════════════════════════════
    #  Dashboard logic
    # ══════════════════════════════════════════════════════════════════════

    def _refresh_dashboard(self):
        self._status_bar.showMessage("Refreshing dashboard …")

        def _fetch():
            quizzes = self._api.list_quizzes()
            pending = self._api.get_pending_reviews()
            attempts = self._api.list_all_attempts()
            # Approximate student count from unique student_user_ids in attempts,
            # but there is no direct endpoint – we can count distinct students
            # that have at least attempted. For registered students we just
            # use the info we have (there is no /users endpoint).
            student_names: set[str] = set()
            for p in pending:
                student_names.add(p.get("student_name", ""))
            for a in attempts:
                # attempt doesn't carry student name; counted separately below
                pass
            active = sum(1 for q in quizzes if q.get("is_active"))
            return {
                "quizzes": len(quizzes),
                "active": active,
                "pending": len(pending),
                "attempts": len(attempts),
            }

        def _done(stats):
            self._quizzes_label.setText(str(stats["active"]))
            self._pending_label.setText(str(stats["pending"]))
            self._students_label.setText(str(stats["attempts"]))  # best proxy
            self._access_code_label.setText(self._read_tutor_code())
            self._status_bar.showMessage("Dashboard refreshed.", 3000)

        self._run_async(_fetch, _done)

    # ══════════════════════════════════════════════════════════════════════
    #  Quiz Builder logic
    # ══════════════════════════════════════════════════════════════════════

    def _add_question_editor(self):
        editor = _QuestionEditor(len(self._question_editors))
        self._question_editors.append(editor)
        self._questions_layout.addWidget(editor)

    def _remove_last_question(self):
        if not self._question_editors:
            return
        editor = self._question_editors.pop()
        self._questions_layout.removeWidget(editor)
        editor.deleteLater()

    def _create_quiz(self):
        title = self._quiz_title_edit.text().strip()
        if not title:
            self._show_warning("Please enter a quiz title.")
            return

        if not self._question_editors:
            self._show_warning("Add at least one question.")
            return

        questions: list[dict] = []
        for i, editor in enumerate(self._question_editors):
            qd = editor.to_dict()
            if not qd.get("prompt"):
                self._show_warning(f"Question {i + 1} has no prompt text.")
                return
            if not qd.get("correct_answer"):
                self._show_warning(f"Question {i + 1} has no correct answer.")
                return
            questions.append(qd)

        payload = {
            "title": title,
            "quiz_number": self._quiz_number_spin.value(),
            "duration_mins": self._quiz_duration_spin.value(),
            "questions": questions,
        }

        self._status_bar.showMessage("Creating quiz …")

        def _done(result):
            self._status_bar.showMessage("Quiz created!", 3000)
            QMessageBox.information(self, "Success", f"Quiz '{title}' created successfully.")
            # Reset form
            self._quiz_title_edit.clear()
            self._quiz_number_spin.setValue(self._quiz_number_spin.value() + 1)
            # Clear question editors
            while self._question_editors:
                self._remove_last_question()
            self._add_question_editor()
            self._refresh_quiz_table()

        self._run_async(lambda: self._api.create_quiz(payload), _done)

    def _refresh_quiz_table(self):
        def _fetch():
            return self._api.list_quizzes()

        def _done(quizzes: list[dict]):
            self._quiz_table.setRowCount(0)
            for row_idx, q in enumerate(quizzes):
                self._quiz_table.insertRow(row_idx)
                quiz_id = q.get("id", "")
                self._quiz_table.setItem(row_idx, 0, QTableWidgetItem(str(quiz_id)))
                self._quiz_table.setItem(row_idx, 1, QTableWidgetItem(str(q.get("quiz_number", ""))))
                self._quiz_table.setItem(row_idx, 2, QTableWidgetItem(q.get("title", "")))
                self._quiz_table.setItem(row_idx, 3, QTableWidgetItem(f"{q.get('duration_mins', '')} min"))
                self._quiz_table.setItem(row_idx, 4, QTableWidgetItem(str(q.get("question_count", 0))))

                is_active = q.get("is_active", False)
                status_item = QTableWidgetItem("✅ Active" if is_active else "⛔ Inactive")
                self._quiz_table.setItem(row_idx, 5, status_item)

                # Action buttons
                action_widget = QWidget()
                action_layout = QHBoxLayout(action_widget)
                action_layout.setContentsMargins(4, 2, 4, 2)
                action_layout.setSpacing(4)

                toggle_btn = QPushButton("Deactivate" if is_active else "Activate")
                toggle_btn.setObjectName("successButton" if not is_active else "secondaryButton")
                toggle_btn.setFixedHeight(28)
                toggle_btn.clicked.connect(
                    lambda checked=False, qid=quiz_id, active=is_active: self._toggle_quiz(qid, not active)
                )
                action_layout.addWidget(toggle_btn)

                del_btn = QPushButton("Delete")
                del_btn.setObjectName("dangerButton")
                del_btn.setFixedHeight(28)
                del_btn.clicked.connect(
                    lambda checked=False, qid=quiz_id, name=q.get("title", ""): self._delete_quiz(qid, name)
                )
                action_layout.addWidget(del_btn)
                self._quiz_table.setCellWidget(row_idx, 6, action_widget)

        self._run_async(_fetch, _done)

    def _toggle_quiz(self, quiz_id: int, new_state: bool):
        def _done(_):
            self._refresh_quiz_table()
            self._status_bar.showMessage(
                f"Quiz {'activated' if new_state else 'deactivated'}.", 3000
            )

        self._run_async(lambda: self._api.toggle_quiz(quiz_id, new_state), _done)

    def _delete_quiz(self, quiz_id: int, title: str):
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete quiz '{title}'?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def _done(_):
            self._refresh_quiz_table()
            self._status_bar.showMessage(f"Quiz '{title}' deleted.", 3000)

        self._run_async(lambda: self._api.delete_quiz(quiz_id), _done)

    # ══════════════════════════════════════════════════════════════════════
    #  Review Queue logic
    # ══════════════════════════════════════════════════════════════════════

    def _refresh_review_table(self):
        def _fetch():
            return self._api.get_pending_reviews()

        def _done(pending: list[dict]):
            self._review_table.setRowCount(0)
            self._review_point_spins: list[tuple[int, QDoubleSpinBox]] = []
            for row_idx, p in enumerate(pending):
                self._review_table.insertRow(row_idx)
                answer_id = p.get("answer_id", 0)
                max_pts = p.get("max_points", 1.0)

                self._review_table.setItem(row_idx, 0, QTableWidgetItem(str(answer_id)))
                self._review_table.setItem(row_idx, 1, QTableWidgetItem(p.get("student_name", "")))
                self._review_table.setItem(row_idx, 2, QTableWidgetItem(p.get("student_id_str", "") or ""))
                self._review_table.setItem(row_idx, 3, QTableWidgetItem(p.get("question_prompt", "")))
                self._review_table.setItem(row_idx, 4, QTableWidgetItem(p.get("correct_answer", "")))
                self._review_table.setItem(row_idx, 5, QTableWidgetItem(p.get("student_response", "") or ""))

                # Editable points spin
                pts_spin = QDoubleSpinBox()
                pts_spin.setRange(0.0, max_pts)
                pts_spin.setValue(0.0)
                pts_spin.setSingleStep(0.5)
                self._review_table.setCellWidget(row_idx, 6, pts_spin)
                self._review_point_spins.append((answer_id, pts_spin))

                # Individual grade button
                grade_btn = QPushButton("Grade")
                grade_btn.setObjectName("successButton")
                grade_btn.setFixedHeight(28)
                grade_btn.clicked.connect(
                    lambda checked=False, aid=answer_id, spin=pts_spin: self._grade_single(aid, spin)
                )
                self._review_table.setCellWidget(row_idx, 7, grade_btn)

            self._status_bar.showMessage(f"Review queue: {len(pending)} pending answer(s).", 3000)

        self._run_async(_fetch, _done)

    def _grade_single(self, answer_id: int, spin: QDoubleSpinBox):
        grades = [{"answer_id": answer_id, "points_awarded": spin.value()}]

        def _done(_):
            self._refresh_review_table()
            self._status_bar.showMessage("Answer graded.", 3000)

        self._run_async(lambda: self._api.grade_answers(grades), _done)

    def _grade_selected(self):
        selected_rows = set()
        for item in self._review_table.selectedItems():
            selected_rows.add(item.row())

        if not selected_rows:
            self._show_warning("Select at least one row to grade.")
            return

        grades: list[dict] = []
        for row in selected_rows:
            if row < len(self._review_point_spins):
                answer_id, spin = self._review_point_spins[row]
                grades.append({"answer_id": answer_id, "points_awarded": spin.value()})

        if not grades:
            return

        def _done(result):
            self._refresh_review_table()
            self._refresh_dashboard()
            QMessageBox.information(
                self, "Graded", result.get("message", f"Graded {len(grades)} answer(s).")
            )

        self._run_async(lambda: self._api.grade_answers(grades), _done)

    # ══════════════════════════════════════════════════════════════════════
    #  Gradebook logic
    # ══════════════════════════════════════════════════════════════════════

    def _export_gradebook(self):
        self._export_status_label.setText("⏳ Exporting …")
        self._status_bar.showMessage("Exporting gradebook …")

        def _done(result):
            msg = result.get("message", "Export completed.")
            detail = result.get("detail", str(GRADEBOOK_PATH))
            self._export_status_label.setText(f"✅ {msg}")
            self._export_status_label.setObjectName("statusLabel")
            self._gradebook_path_label.setText(f"Gradebook path: {detail}")
            self._status_bar.showMessage("Gradebook exported.", 3000)
            self._refresh_gradebook()
            QMessageBox.information(self, "Export Complete", f"{msg}\n\nSaved to:\n{detail}")

        def _err(msg):
            self._export_status_label.setText(f"❌ Export failed: {msg}")
            self._export_status_label.setObjectName("errorLabel")
            self._show_error(msg)

        self._run_async(lambda: self._api.export_gradebook(), _done, _err)

    def _refresh_gradebook(self):
        def _fetch():
            return self._api.list_all_attempts()

        def _done(attempts: list[dict]):
            self._gradebook_table.setRowCount(0)
            for row_idx, a in enumerate(attempts):
                self._gradebook_table.insertRow(row_idx)
                self._gradebook_table.setItem(row_idx, 0, QTableWidgetItem(str(a.get("attempt_id", ""))))
                self._gradebook_table.setItem(row_idx, 1, QTableWidgetItem(a.get("quiz_title", "")))
                self._gradebook_table.setItem(row_idx, 2, QTableWidgetItem(a.get("status", "")))
                score = a.get("total_score", 0)
                max_score = a.get("max_score", 0)
                self._gradebook_table.setItem(row_idx, 3, QTableWidgetItem(f"{score}/{max_score}"))
                submitted = a.get("submitted_at", "") or "—"
                self._gradebook_table.setItem(row_idx, 4, QTableWidgetItem(str(submitted)))
            self._status_bar.showMessage(f"Gradebook: {len(attempts)} attempt(s) loaded.", 3000)

        self._run_async(_fetch, _done)

    # ══════════════════════════════════════════════════════════════════════
    #  Error / warning helpers
    # ══════════════════════════════════════════════════════════════════════

    def _show_error(self, msg: str):
        self._status_bar.showMessage(f"Error: {msg}", 5000)
        QMessageBox.critical(self, "Error", str(msg))

    def _show_warning(self, msg: str):
        QMessageBox.warning(self, "Warning", msg)
