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

    def exit_app(self):
        self.engine.stop()
        QApplication.quit()
