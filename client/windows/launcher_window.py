"""Mode selection launcher – choose Tutor Host or Student Client."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

import uvicorn
from PySide6.QtCore import Qt, Signal, QObject, Slot
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from client.api_client import APIClient
from client.windows.auth_dialog import AuthDialog
from server.app import create_app
from server.udp_broadcaster import UDPBroadcaster, listen_for_server
from shared.config import SERVER_HOST, SERVER_PORT
from shared.schemas import UserRole


# ── Helper signal bridge (thread → Qt main thread) ──────────────────────────

class _DiscoverySignals(QObject):
    """Bridges a background thread result into Qt's event loop."""

    finished = Signal(object)  # dict | None


# ── Launcher Window ─────────────────────────────────────────────────────────

class LauncherWindow(QWidget):
    """Initial mode-selection window for the LAN Quiz Platform."""

    STYLESHEET_PATH = Path(__file__).resolve().parent.parent / "styles" / "theme.qss"

    def __init__(self) -> None:
        super().__init__()
        self._api_client: Optional[APIClient] = None
        self._broadcaster: Optional[UDPBroadcaster] = None

        self._init_ui()
        self._load_stylesheet()

    # ── UI setup ─────────────────────────────────────────────────────────

    def _init_ui(self) -> None:
        self.setWindowTitle("LAN Quiz Platform")
        self.setFixedSize(520, 420)

        root_layout = QVBoxLayout(self)
        root_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root_layout.setContentsMargins(40, 30, 40, 30)
        root_layout.setSpacing(12)

        # Title
        title = QLabel("🎓  LAN Quiz Platform")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root_layout.addWidget(title)

        # Subtitle
        subtitle = QLabel("Select your role to get started")
        subtitle.setObjectName("subtitleLabel")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root_layout.addWidget(subtitle)

        root_layout.addSpacing(20)

        # Tutor Host button
        self.btn_tutor = QPushButton("🖥  Tutor Host")
        self.btn_tutor.setObjectName("primaryButton")
        self.btn_tutor.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tutor.setMinimumHeight(60)
        self.btn_tutor.setToolTip(
            "Start the quiz server on this machine and log in as a Tutor."
        )
        self.btn_tutor.clicked.connect(self._on_tutor_host)
        root_layout.addWidget(self.btn_tutor)

        # Student Client button
        self.btn_student = QPushButton("📝  Student Client")
        self.btn_student.setObjectName("successButton")
        self.btn_student.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_student.setMinimumHeight(60)
        self.btn_student.setToolTip(
            "Connect to a running quiz server on the LAN."
        )
        self.btn_student.clicked.connect(self._on_student_client)
        root_layout.addWidget(self.btn_student)

        root_layout.addSpacing(10)

        # Discovery area (hidden by default)
        self._build_discovery_area(root_layout)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.hide()
        root_layout.addWidget(self.status_label)

        root_layout.addStretch()

    def _build_discovery_area(self, parent_layout: QVBoxLayout) -> None:
        """Create the server-discovery UI (progress + manual entry)."""
        self.discovery_widget = QWidget()
        disc_layout = QVBoxLayout(self.discovery_widget)
        disc_layout.setContentsMargins(0, 0, 0, 0)
        disc_layout.setSpacing(8)

        # Progress bar (indeterminate)
        self.discovery_progress = QProgressBar()
        self.discovery_progress.setRange(0, 0)  # indeterminate
        self.discovery_progress.setTextVisible(False)
        self.discovery_progress.setFixedHeight(6)
        disc_layout.addWidget(self.discovery_progress)

        self.discovery_label = QLabel("Discovering server on LAN…")
        self.discovery_label.setObjectName("subtitleLabel")
        self.discovery_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        disc_layout.addWidget(self.discovery_label)

        # Manual entry row (hidden until discovery fails)
        self.manual_widget = QWidget()
        manual_layout = QHBoxLayout(self.manual_widget)
        manual_layout.setContentsMargins(0, 0, 0, 0)

        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("Host IP:Port  (e.g. 192.168.1.5:8000)")
        manual_layout.addWidget(self.ip_input)

        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setObjectName("primaryButton")
        self.btn_connect.clicked.connect(self._on_manual_connect)
        manual_layout.addWidget(self.btn_connect)

        self.manual_widget.hide()
        disc_layout.addWidget(self.manual_widget)

        self.discovery_widget.hide()
        parent_layout.addWidget(self.discovery_widget)

    def _load_stylesheet(self) -> None:
        if self.STYLESHEET_PATH.exists():
            self.setStyleSheet(self.STYLESHEET_PATH.read_text(encoding="utf-8"))

    # ── Tutor Host flow ──────────────────────────────────────────────────

    @Slot()
    def _on_tutor_host(self) -> None:
        self._set_buttons_enabled(False)
        self.status_label.setText("Starting server…")
        self.status_label.show()

        # 1. Start uvicorn in a daemon thread
        app = create_app()
        server_thread = threading.Thread(
            target=uvicorn.run,
            args=(app,),
            kwargs={"host": SERVER_HOST, "port": SERVER_PORT, "log_level": "warning"},
            daemon=True,
        )
        server_thread.start()

        # 2. Start UDP broadcaster
        self._broadcaster = UDPBroadcaster(port=SERVER_PORT)
        self._broadcaster.start()

        # 3. Build APIClient pointing to localhost
        self._api_client = APIClient(base_url=f"http://127.0.0.1:{SERVER_PORT}")

        # Give the server a moment to initialise, then open auth
        from PySide6.QtCore import QTimer

        QTimer.singleShot(800, lambda: self._open_auth(UserRole.TUTOR))

    # ── Student Client flow ──────────────────────────────────────────────

    @Slot()
    def _on_student_client(self) -> None:
        self._set_buttons_enabled(False)

        # Show discovery area
        self.discovery_widget.show()
        self.discovery_progress.show()
        self.discovery_label.setText("Discovering server on LAN…")
        self.manual_widget.hide()

        # Run discovery in background thread
        self._disc_signals = _DiscoverySignals()
        self._disc_signals.finished.connect(self._on_discovery_result)

        threading.Thread(target=self._discover_worker, daemon=True).start()

    def _discover_worker(self) -> None:
        """Runs in background thread – calls listen_for_server."""
        result = listen_for_server()
        self._disc_signals.finished.emit(result)

    @Slot(object)
    def _on_discovery_result(self, result: dict | None) -> None:
        self.discovery_progress.hide()

        if result:
            ip = result["ip"]
            port = result["port"]
            course = result.get("course_title", "")
            self.discovery_label.setText(
                f"✅  Found server at {ip}:{port}"
                + (f"  —  {course}" if course else "")
            )
            self._api_client = APIClient(base_url=f"http://{ip}:{port}")
            self._open_auth(UserRole.STUDENT)
        else:
            self.discovery_label.setText(
                "Server not found. Enter the host address manually:"
            )
            self.manual_widget.show()
            self._set_buttons_enabled(True)

    @Slot()
    def _on_manual_connect(self) -> None:
        raw = self.ip_input.text().strip()
        if not raw:
            QMessageBox.warning(self, "Input required", "Please enter the server IP:Port.")
            return

        # Normalise into a URL
        if not raw.startswith("http"):
            raw = f"http://{raw}"

        self._api_client = APIClient(base_url=raw)

        # Quick health-check
        if not self._api_client.health_check():
            QMessageBox.critical(
                self,
                "Connection failed",
                f"Could not reach the server at {raw}.\n"
                "Make sure the tutor has started the server and you are on the same network.",
            )
            return

        self._open_auth(UserRole.STUDENT)

    # ── Auth dialog ──────────────────────────────────────────────────────

    def _open_auth(self, role: UserRole) -> None:
        self.status_label.setText("Authenticating…")
        dialog = AuthDialog(api_client=self._api_client, role=role, parent=self)
        result = dialog.exec()

        if result == QDialog.DialogCode.Accepted:
            user_info = dialog.user_info
            self._launch_main_window(user_info, role)
        else:
            # User cancelled – reset launcher
            self._reset()

    def _launch_main_window(self, user_info: dict, role: UserRole) -> None:
        """Open the appropriate main window and close the launcher."""
        self.hide()
        self.status_label.setText("Launching…")

        if role == UserRole.TUTOR:
            from client.windows.tutor_window import TutorWindow  # type: ignore[import-not-found]

            self._main_window = TutorWindow(
                api_client=self._api_client,
                user_info=user_info,
            )
        else:
            from client.windows.student_window import StudentWindow  # type: ignore[import-not-found]

            self._main_window = StudentWindow(
                api_client=self._api_client,
                user_info=user_info,
            )

        self._main_window.show()

    # ── Helpers ──────────────────────────────────────────────────────────

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self.btn_tutor.setEnabled(enabled)
        self.btn_student.setEnabled(enabled)

    def _reset(self) -> None:
        self._set_buttons_enabled(True)
        self.discovery_widget.hide()
        self.status_label.hide()
