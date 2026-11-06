import os
import psutil
from utils.logger import log

class ProcessManager:
    """
    Process Lifecycle Supervisor & Diagnostic Inspector for MXB.
    Inspects resource-heavy applications, maps local network listening ports to PIDs,
    and terminates hung or unresponsive processes with kernel protection guards.
    """

    CRITICAL_SYSTEM_PROCESSES = {
        "explorer.exe", "svchost.exe", "csrss.exe", "lsass.exe", "smss.exe",
        "wininit.exe", "services.exe", "spoolsv.exe", "dwm.exe", "conhost.exe"
    }

    @classmethod
    def get_top_processes(cls, limit: int = 5) -> list[dict]:
        """Returns top processes ranked by physical RAM consumption."""
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                mem_mb = (p.info['memory_info'].rss // (1024 * 1024)) if p.info.get('memory_info') else 0
                name = p.info.get('name') or "Unknown"
                if mem_mb > 1:
                    procs.append({
                        "pid": p.info['pid'],
                        "name": name,
                        "memory_mb": mem_mb
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        procs.sort(key=lambda x: x["memory_mb"], reverse=True)
        return procs[:limit]

    @classmethod
    def find_process_by_port(cls, port: int) -> dict | None:
        """Finds the local process listening on the specified TCP/UDP port."""
        try:
            port = int(port)
            for conn in psutil.net_connections(kind='inet'):
                if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                    pid = conn.pid
                    name = "Unknown"
                    if pid:
                        try:
                            name = psutil.Process(pid).name()
                        except Exception:
                            pass
                    return {
                        "port": port,
                        "pid": pid,
                        "name": name,
                        "status": conn.status
                    }
        except Exception as e:
            log.warning(f"ProcessManager: Port check error on {port}: {e}")
        return None

    @classmethod
    def terminate_process(cls, target: str | int, force: bool = True) -> dict:
        """
        Safely terminates a process by PID or process executable name.
        Guards critical Windows system processes from accidental termination.
        """
        target_str = str(target).strip()
        is_pid = target_str.isdigit()

        if not is_pid and not target_str.endswith(".exe"):
            target_name = f"{target_str}.exe".lower()
        else:
            target_name = target_str.lower()

        # Protection guard
        if target_name in cls.CRITICAL_SYSTEM_PROCESSES:
            return {
                "success": False,
                "error": f"Process '{target_name}' is a protected Windows core system process."
            }

        killed_pids = []
        try:
            if is_pid:
                pid = int(target_str)
                p = psutil.Process(pid)
                pname = p.name().lower()
                if pname in cls.CRITICAL_SYSTEM_PROCESSES:
                    return {"success": False, "error": f"PID {pid} ({pname}) is protected."}
                if force:
                    p.kill()
                else:
                    p.terminate()
                killed_pids.append(pid)
            else:
                for p in psutil.process_iter(['pid', 'name']):
                    try:
                        if p.info.get('name', '').lower() == target_name:
                            p_obj = psutil.Process(p.info['pid'])
                            if force:
                                p_obj.kill()
                            else:
                                p_obj.terminate()
                            killed_pids.append(p.info['pid'])
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

            if killed_pids:
                log.info(f"ProcessManager: Terminated {len(killed_pids)} instance(s) of '{target}' (PIDs: {killed_pids})")
                return {
                    "success": True,
                    "target": target,
                    "count": len(killed_pids),
                    "pids": killed_pids,
                    "summary": f"Terminated {len(killed_pids)} process instance(s) of {target}."
                }
            else:
                return {
                    "success": False,
                    "target": target,
                    "error": f"No running processes found matching '{target}'."
                }
        except Exception as e:
            log.error(f"ProcessManager: Failed to terminate '{target}': {e}")
            return {
                "success": False,
                "target": target,
                "error": str(e)
            }
