"""Login / Registration dialog with role-aware fields."""

from __future__ import annotations

import re
from typing import Optional

import httpx
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from client.api_client import APIClient
from shared.config import EMAIL_DOMAIN_SUFFIX, STUDENT_ID_REGEX
from shared.schemas import UserRole


class AuthDialog(QDialog):
    """Modal login / register dialog.

    After a successful authentication the caller can read *user_info*
    (a dict with ``user_id``, ``role``, and ``full_name``) and the
    *api_client* will already contain the JWT token.
    """

    def __init__(
        self,
        api_client: APIClient,
        role: UserRole = UserRole.STUDENT,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._role = role
        self.user_info: dict = {}

        self._init_ui()

    # ── UI construction ──────────────────────────────────────────────────

    def _init_ui(self) -> None:
        self.setWindowTitle("Authentication")
        self.setMinimumWidth(420)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        # Header
        title = QLabel(
            "🖥  Tutor Login" if self._role == UserRole.TUTOR else "📝  Student Login"
        )
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        subtitle = QLabel(f"Server: {self._api.base_url}")
        subtitle.setObjectName("subtitleLabel")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(subtitle)

        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_login_tab(), "Login")
        self.tabs.addTab(self._build_register_tab(), "Register")
        root.addWidget(self.tabs)

    # ── Login tab ────────────────────────────────────────────────────────

    def _build_login_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(10)

        self.login_email = QLineEdit()
        self.login_email.setPlaceholderText(f"you{EMAIL_DOMAIN_SUFFIX}")
        form.addRow("Email:", self.login_email)

        self.login_password = QLineEdit()
        self.login_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.login_password.setPlaceholderText("Password")
        form.addRow("Password:", self.login_password)

        self.login_error = QLabel("")
        self.login_error.setObjectName("errorLabel")
        self.login_error.setWordWrap(True)
        self.login_error.hide()
        form.addRow(self.login_error)

        btn = QPushButton("Login")
        btn.setObjectName("primaryButton")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self._on_login)
        form.addRow(btn)

        # Allow Enter to submit
        self.login_password.returnPressed.connect(btn.click)

        return tab

    # ── Register tab ─────────────────────────────────────────────────────

    def _build_register_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(10)

        self.reg_name = QLineEdit()
        self.reg_name.setPlaceholderText("Full Name")
        form.addRow("Full Name:", self.reg_name)

        self.reg_email = QLineEdit()
        self.reg_email.setPlaceholderText(f"you{EMAIL_DOMAIN_SUFFIX}")
        self.reg_email.textChanged.connect(self._on_email_changed)
        form.addRow("Email:", self.reg_email)

        # Student ID – visible only for STUDENT role
        self.reg_student_id = QLineEdit()
        self.reg_student_id.setPlaceholderText("Auto-extracted from email")
        self._student_id_label = QLabel("Student ID:")
        if self._role == UserRole.STUDENT:
            form.addRow(self._student_id_label, self.reg_student_id)
        else:
            self.reg_student_id.hide()
            self._student_id_label.hide()

        self.reg_password = QLineEdit()
        self.reg_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.reg_password.setPlaceholderText("Password")
        form.addRow("Password:", self.reg_password)

        self.reg_confirm = QLineEdit()
        self.reg_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.reg_confirm.setPlaceholderText("Confirm Password")
        form.addRow("Confirm Password:", self.reg_confirm)

        # Tutor access code – visible only for TUTOR role
        self.reg_tutor_code = QLineEdit()
        self.reg_tutor_code.setPlaceholderText("Tutor Access Code")
        self._tutor_code_label = QLabel("Access Code:")
        if self._role == UserRole.TUTOR:
            form.addRow(self._tutor_code_label, self.reg_tutor_code)
        else:
            self.reg_tutor_code.hide()
            self._tutor_code_label.hide()

        self.reg_error = QLabel("")
        self.reg_error.setObjectName("errorLabel")
        self.reg_error.setWordWrap(True)
        self.reg_error.hide()
        form.addRow(self.reg_error)

        btn = QPushButton("Register")
        btn.setObjectName("successButton")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self._on_register)
        form.addRow(btn)

        self.reg_confirm.returnPressed.connect(btn.click)

        return tab

    # ── Slots ────────────────────────────────────────────────────────────

    @Slot(str)
    def _on_email_changed(self, text: str) -> None:
        """Auto-extract student ID from digits in the email prefix."""
        if self._role != UserRole.STUDENT:
            return
        prefix = text.split("@")[0] if "@" in text else text
        match = STUDENT_ID_REGEX.search(prefix)
        if match:
            self.reg_student_id.setText(match.group(1))

    @Slot()
    def _on_login(self) -> None:
        email = self.login_email.text().strip()
        password = self.login_password.text()

        if not email or not password:
            self._show_login_error("Please fill in all fields.")
            return

        if not email.endswith(EMAIL_DOMAIN_SUFFIX):
            self._show_login_error(
                f"Email must end with {EMAIL_DOMAIN_SUFFIX}"
            )
            return

        try:
            result = self._api.login(email, password)
            self._accept_with(result)
        except httpx.HTTPStatusError as exc:
            self._show_login_error(self._extract_detail(exc))
        except httpx.ConnectError:
            self._show_login_error(
                "Cannot reach the server. Check your network connection."
            )
        except Exception as exc:  # noqa: BLE001
            self._show_login_error(str(exc))

    @Slot()
    def _on_register(self) -> None:
        name = self.reg_name.text().strip()
        email = self.reg_email.text().strip()
        password = self.reg_password.text()
        confirm = self.reg_confirm.text()

        # Basic validation
        if not name or not email or not password or not confirm:
            self._show_reg_error("Please fill in all fields.")
            return

        if not email.endswith(EMAIL_DOMAIN_SUFFIX):
            self._show_reg_error(
                f"Email must end with {EMAIL_DOMAIN_SUFFIX}"
            )
            return

        if password != confirm:
            self._show_reg_error("Passwords do not match.")
            return

        if len(password) < 4:
            self._show_reg_error("Password must be at least 4 characters.")
            return

        payload: dict = {
            "full_name": name,
            "email": email,
            "password": password,
            "role": self._role.value,
        }

        if self._role == UserRole.STUDENT:
            sid = self.reg_student_id.text().strip()
            if sid:
                payload["student_id"] = sid
        elif self._role == UserRole.TUTOR:
            code = self.reg_tutor_code.text().strip()
            if not code:
                self._show_reg_error("Tutor access code is required.")
                return
            payload["tutor_access_code"] = code

        try:
            result = self._api.register(payload)
            self._accept_with(result)
        except httpx.HTTPStatusError as exc:
            self._show_reg_error(self._extract_detail(exc))
        except httpx.ConnectError:
            self._show_reg_error(
                "Cannot reach the server. Check your network connection."
            )
        except Exception as exc:  # noqa: BLE001
            self._show_reg_error(str(exc))

    # ── Helpers ──────────────────────────────────────────────────────────

    def _accept_with(self, token_response: dict) -> None:
        """Store result, set user_info, and accept the dialog."""
        self.user_info = {
            "user_id": token_response["user_id"],
            "role": token_response["role"],
            "full_name": token_response["full_name"],
        }
        self.accept()

    @staticmethod
    def _extract_detail(exc: httpx.HTTPStatusError) -> str:
        """Pull a human-readable message from an HTTP error response."""
        try:
            body = exc.response.json()
            return body.get("detail", str(exc))
        except Exception:
            return f"Server error ({exc.response.status_code})"

    def _show_login_error(self, msg: str) -> None:
        self.login_error.setText(msg)
        self.login_error.show()

    def _show_reg_error(self, msg: str) -> None:
        self.reg_error.setText(msg)
        self.reg_error.show()
