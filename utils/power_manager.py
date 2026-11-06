import psutil
from utils.logger import log

class PowerManager:
    """
    Battery and Power Telemetry Monitor for MXB.
    Tracks charge level, AC adapter status, estimated runtime, and power health.
    """

    @staticmethod
    def get_battery_status() -> dict:
        """
        Retrieves current battery metrics and health status.
        Handles desktop machines without batteries gracefully.
        """
        try:
            battery = psutil.sensors_battery()
            if battery is None:
                return {
                    "has_battery": False,
                    "percent": 100,
                    "power_plugged": True,
                    "time_left": None,
                    "status_level": "desktop",
                    "summary": "Desktop workstation detected (running on AC power)."
                }

            percent = int(battery.percent)
            plugged = bool(battery.power_plugged)
            secs = battery.secsleft

            # Format remaining time
            if plugged:
                time_str = "Plugged in (Charging)"
            elif secs == psutil.POWER_TIME_UNLIMITED or secs < 0:
                time_str = "Calculating remaining runtime..."
            else:
                hours = secs // 3600
                mins = (secs % 3600) // 60
                time_str = f"{hours}h {mins}m remaining"

            # Determine health / status level
            if plugged:
                level = "full" if percent >= 95 else "charging"
            elif percent <= 15:
                level = "critical"
            elif percent <= 30:
                level = "low"
            else:
                level = "good"

            # Spoken summary for TTS
            if plugged:
                summary = f"Battery is at {percent} percent and plugged in."
            else:
                summary = f"Battery is at {percent} percent on battery power. Estimated {time_str}."

            log.info(f"PowerManager: Battery {percent}%, Plugged: {plugged}, Level: {level}")
            return {
                "has_battery": True,
                "percent": percent,
                "power_plugged": plugged,
                "time_left": time_str,
                "status_level": level,
                "summary": summary
            }
        except Exception as e:
            log.error(f"PowerManager: Failed to query power status: {e}")
            return {
                "has_battery": False,
                "percent": 0,
                "power_plugged": False,
                "time_left": None,
                "status_level": "error",
                "summary": f"Could not retrieve battery telemetry: {e}"
            }

    @classmethod
    def is_power_saving_needed(cls) -> bool:
        """Returns True if battery is discharging and below 20%."""
        status = cls.get_battery_status()
        return status["has_battery"] and not status["power_plugged"] and status["percent"] <= 20
