import threading
from utils.logger import log

class Notifier:
    @staticmethod
    def show_notification(title: str, message: str):
        def _show():
            try:
                from win11toast import toast
                toast(title, message)
                log.info(f"Notifier: Toast displayed: '{title} - {message}'")
            except Exception as e:
                log.warning(f"Notifier: Toast display notice: {e}")

        threading.Thread(target=_show, daemon=True).start()
