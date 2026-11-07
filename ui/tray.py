from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import QStyle
from ui.settings import SettingsDashboard

class MXBTray(QSystemTrayIcon):
    def __init__(self, hud, engine, parent=None, chat=None):
        super().__init__(parent)
        self.hud = hud
        self.engine = engine
        self.chat = chat
        self.settings_window = None
        
        # Use a default system icon for the tray
        app = QApplication.instance()
        icon = app.style().standardIcon(QStyle.SP_ComputerIcon)
        self.setIcon(icon)
        self.setToolTip("Machine eXecutive Brain (MXB)")

        # Create Menu
        self.menu = QMenu()
        self.menu.setStyleSheet("""
            QMenu {
                background-color: #12151E;
                color: #FFFFFF;
                border: 1px solid #00E5FF;
                border-radius: 6px;
                padding: 6px;
                font-family: 'Segoe UI';
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #00E5FF;
                color: #000000;
                font-weight: bold;
            }
            QMenu::separator {
                height: 1px;
                background: #333333;
                margin: 4px 8px;
            }
        """)
        
        # Chat window (text conversation)
        if self.chat is not None:
            self.chat_action = QAction("Open Chat")
            self.chat_action.triggered.connect(self.chat.show_and_focus)
            self.menu.addAction(self.chat_action)

            self.stop_action = QAction("Stop All Actions")
            self.stop_action.triggered.connect(lambda: self.chat.bus.submit("stop", "text"))
            self.menu.addAction(self.stop_action)
            self.menu.addSeparator()

        # Toggle HUD Action
        self.toggle_hud_action = QAction("Hide HUD")
        self.toggle_hud_action.triggered.connect(self.toggle_hud)
        self.menu.addAction(self.toggle_hud_action)

        # Toggle Compact Mode Action
        self.toggle_compact_action = QAction("Toggle Compact Badge")
        self.toggle_compact_action.triggered.connect(self.toggle_compact)
        self.menu.addAction(self.toggle_compact_action)

        # Pause/Resume Action
        self.pause_action = QAction("Pause Listening")
        self.pause_action.triggered.connect(self.toggle_listening)
        self.menu.addAction(self.pause_action)

        # Battery / Power Telemetry
        self.power_action = QAction("Power & Battery Status")
        self.power_action.triggered.connect(self.show_power_status)
        self.menu.addAction(self.power_action)

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
        if self.chat is not None:
            self.activated.connect(self._on_activated)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.chat.toggle_visible()

    def toggle_hud(self):
        if self.hud.isVisible():
            self.hud.hide()
            self.toggle_hud_action.setText("Show HUD")
        else:
            self.hud.show()
            self.toggle_hud_action.setText("Hide HUD")

    def toggle_compact(self):
        self.hud.toggle_compact_mode()
        badge_state = "Compact" if self.hud.is_compact else "Expanded"
        self.hud.update_action(f"Switched to {badge_state} HUD mode.")

    def show_power_status(self):
        from utils.power_manager import PowerManager
        p_status = PowerManager.get_battery_status()
        self.hud.update_action(p_status["summary"])

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
