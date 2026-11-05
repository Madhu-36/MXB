from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import QStyle
from ui.settings import SettingsDashboard

class MXBTray(QSystemTrayIcon):
    def __init__(self, hud, engine, parent=None):
        super().__init__(parent)
        self.hud = hud
        self.engine = engine
        self.settings_window = None
        
        # Use a default system icon for the tray
        app = QApplication.instance()
        icon = app.style().standardIcon(QStyle.SP_ComputerIcon)
        self.setIcon(icon)
        self.setToolTip("Machine eXecutive Brain (MXB)")

        # Create Menu
        self.menu = QMenu()
        
        # Toggle HUD Action
        self.toggle_hud_action = QAction("Hide HUD")
        self.toggle_hud_action.triggered.connect(self.toggle_hud)
        self.menu.addAction(self.toggle_hud_action)

        # Pause/Resume Action
        self.pause_action = QAction("Pause Listening")
        self.pause_action.triggered.connect(self.toggle_listening)
        self.menu.addAction(self.pause_action)

        # Settings Action
        self.settings_action = QAction("Settings Dashboard")
        self.settings_action.triggered.connect(self.open_settings)
        self.menu.addAction(self.settings_action)

        # Health Diagnostics Action
        self.diagnostics_action = QAction("Run Health Diagnostics")
        self.diagnostics_action.triggered.connect(self.run_diagnostics)
        self.menu.addAction(self.diagnostics_action)

        # Clear History Action
        self.clear_history_action = QAction("Clear History")
        self.clear_history_action.triggered.connect(self.clear_history)
        self.menu.addAction(self.clear_history_action)

        self.menu.addSeparator()

        # Exit Action
        self.exit_action = QAction("Exit MXB")
        self.exit_action.triggered.connect(self.exit_app)
        self.menu.addAction(self.exit_action)

        self.setContextMenu(self.menu)

    def toggle_hud(self):
        if self.hud.isVisible():
            self.hud.hide()
            self.toggle_hud_action.setText("Show HUD")
        else:
            self.hud.show()
            self.toggle_hud_action.setText("Hide HUD")

    def toggle_listening(self):
        if self.engine.is_listening:
            self.engine.pause_listening()
            self.pause_action.setText("Resume Listening")
        else:
            self.engine.resume_listening()
            self.pause_action.setText("Pause Listening")

    def open_settings(self):
        if self.settings_window is None:
            self.settings_window = SettingsDashboard()
        self.settings_window.show()
        self.settings_window.activateWindow()

    def run_diagnostics(self):
        from utils.diagnostics import SystemDiagnostics
        health = SystemDiagnostics.get_health_report()
        status_text = f"Mic: {'OK' if health.get('microphone_active') else 'NO'} | Internet: {'OK' if health.get('internet') else 'NO'} | Ollama: {'OK' if health.get('ollama_running') else 'NO'}"
        self.hud.update_action(status_text)

    def clear_history(self):
        if hasattr(self.engine, 'router') and hasattr(self.engine.router, 'history'):
            self.engine.router.history.clear()
            self.hud.update_action("Command history cleared.")

    def exit_app(self):
        self.engine.stop()
        QApplication.quit()
