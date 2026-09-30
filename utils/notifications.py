from win11toast import toast
import threading

class Notifier:
    @staticmethod
    def show_notification(title: str, message: str):
        def _show():
            try:
                toast(title, message, icon="https://upload.wikimedia.org/wikipedia/commons/thumb/c/c2/GitHub_Invertocat_Logo.svg/1200px-GitHub_Invertocat_Logo.svg.png")
            except Exception as e:
                print(f"[Notifier] Failed to show toast: {e}")
        
        threading.Thread(target=_show, daemon=True).start()
