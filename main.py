"""
LAN Quiz Platform — Unified Entry Point
Launch as Tutor Host or Student Client.
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.config import DATA_DIR, RECOVERY_DIR


def main():
    """Launch the application."""
    # Ensure data directories exist
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RECOVERY_DIR.mkdir(parents=True, exist_ok=True)

    # Import PySide6 and launch GUI
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    app = QApplication(sys.argv)

    # Load stylesheet
    style_path = PROJECT_ROOT / "client" / "styles" / "theme.qss"
    if style_path.exists():
        app.setStyleSheet(style_path.read_text())

    # Launch the launcher window
    from client.windows.launcher_window import LauncherWindow
    launcher = LauncherWindow()
    launcher.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
