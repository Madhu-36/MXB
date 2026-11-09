"""
Auto-update from GitHub Releases, with SHA-256 verification.

Release layout (produced by .github/workflows/release.yml):
  MXB-Setup-<version>.exe     the installer
  SHA256SUMS.txt              "<sha256>  MXB-Setup-<version>.exe"

Flow: check() -> download() verifies the hash while streaming and deletes the file on any
mismatch -> install() runs the installer silently; it closes MXB, upgrades in place and
relaunches it. User data in %APPDATA%\\MXB is untouched.

What the checksum does and doesn't protect against: it catches corrupted or tampered
downloads, but if someone controlled the GitHub release itself they could publish a matching
checksum. Code-signing the installer (Authenticode) is the stronger fix for that.
"""
import hashlib
import json
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
import requests
from utils.paths import data_file, data_dir, is_frozen
from utils.version import __version__, is_newer

API = "https://api.github.com/repos/{repo}/releases/latest"
INSTALLER_RE = re.compile(r"^MXB-Setup-[\w.\-]+\.exe$", re.I)


class UpdateError(Exception):
    pass


@dataclass
class UpdateInfo:
    version: str
    installer_name: str
    installer_url: str
    sums_url: str
    notes: str = ""
    size: int = 0


def update_message(info: "UpdateInfo", current: str, frozen: bool) -> str:
    how = ("Say 'install the update' when you're ready." if frozen
           else "You're running from source, so run 'git pull' to update.")
    return f"MXB {info.version} is available (you have {current}). {how}"


def parse_sums(text: str) -> dict[str, str]:
    """'<hash>  <file>' or '<hash> *<file>' lines -> {file: hash}."""
    out = {}
    for line in (text or "").splitlines():
        m = re.match(r"^\s*([A-Fa-f0-9]{64})\s+\*?(.+?)\s*$", line)
        if m:
            out[m.group(2)] = m.group(1).lower()
    return out


class Updater:
    def __init__(self, repo: str = "Madhu-36/MXB", current: str = __version__, http=requests,
                 download_dir: Path | None = None, state_path: Path | None = None):
        self.repo = repo
        self.current = current
        self.http = http
        self.download_dir = Path(download_dir) if download_dir else data_dir() / "updates"
        self.state_path = Path(state_path) if state_path else data_file("update_state.json")

    # ------------------------------------------------------------------ state
    def _state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def should_check(self, interval_hours: float = 24.0) -> bool:
        return time.time() - float(self._state().get("last_check", 0)) >= interval_hours * 3600

    def _remember_check(self, latest: str | None):
        try:
            self.state_path.write_text(json.dumps({"last_check": time.time(), "latest": latest}), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------------ check
    def check(self, timeout: float = 8.0) -> UpdateInfo | None:
        try:
            resp = self.http.get(API.format(repo=self.repo), timeout=timeout,
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "MXB-Updater"})
        except Exception as e:
            raise UpdateError(f"Couldn't reach GitHub: {e}")
        if resp.status_code == 404:
            self._remember_check(None)
            return None  # no releases published yet
        if resp.status_code != 200:
            raise UpdateError(f"GitHub returned {resp.status_code}.")
        data = resp.json()
        tag = str(data.get("tag_name", ""))
        self._remember_check(tag)
        if not tag or not is_newer(tag, self.current):
            return None
        assets = {a.get("name", ""): a for a in data.get("assets", [])}
        installer = next((a for n, a in assets.items() if INSTALLER_RE.match(n)), None)
        sums = assets.get("SHA256SUMS.txt")
        if installer is None or sums is None:
            raise UpdateError(f"Release {tag} is missing its installer or SHA256SUMS.txt, so I won't install it.")
        return UpdateInfo(version=tag.lstrip("vV"), installer_name=installer["name"],
                          installer_url=installer["browser_download_url"], sums_url=sums["browser_download_url"],
                          notes=(data.get("body") or "")[:600], size=int(installer.get("size") or 0))

    # ------------------------------------------------------------------ download + verify
    def download(self, info: UpdateInfo, progress=None, timeout: float = 30.0) -> Path:
        sums_resp = self.http.get(info.sums_url, timeout=timeout, headers={"User-Agent": "MXB-Updater"})
        if sums_resp.status_code != 200:
            raise UpdateError("Couldn't download the checksum file.")
        expected = parse_sums(sums_resp.text).get(info.installer_name)
        if not expected:
            raise UpdateError(f"SHA256SUMS.txt has no entry for {info.installer_name}.")

        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._remove_old_downloads()
        final = self.download_dir / info.installer_name
        part = final.with_suffix(final.suffix + ".part")
        digest = hashlib.sha256()
        done = 0
        with self.http.get(info.installer_url, timeout=timeout, stream=True, headers={"User-Agent": "MXB-Updater"}) as resp:
            if resp.status_code != 200:
                raise UpdateError(f"Download failed ({resp.status_code}).")
            with open(part, "wb") as f:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress and info.size:
                        progress(done, info.size)
        actual = digest.hexdigest()
        if actual != expected:
            part.unlink(missing_ok=True)
            raise UpdateError(f"Checksum mismatch for {info.installer_name} (expected {expected[:12]}…, got {actual[:12]}…). "
                              "The download was deleted and nothing was installed.")
        part.replace(final)
        return final

    def _remove_old_downloads(self):
        """Installers are ~150 MB each: keep only the one being downloaded now."""
        for old in self.download_dir.glob("MXB-Setup-*"):
            try:
                old.unlink()
            except OSError:
                pass  # e.g. an installer that is still running

    # ------------------------------------------------------------------ install
    INSTALLER_ARGS = ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]

    @classmethod
    def install(cls, installer: Path, wait_pid: int | None = None, popen=None):
        """
        Runs the verified installer silently, after MXB has exited.

        A hidden PowerShell waits for wait_pid (MXB itself) to quit, so the installer never
        fights MXB for locked files; Inno Setup then upgrades in place and relaunches MXB.
        /CLOSEAPPLICATIONS is the backstop if MXB hasn't exited within 60 s.
        """
        popen = popen or subprocess.Popen
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        installer = str(installer)
        if wait_pid:
            quoted = installer.replace("'", "''")
            args = ",".join(f"'{a}'" for a in cls.INSTALLER_ARGS)
            script = (f"try {{ Wait-Process -Id {int(wait_pid)} -Timeout 60 -ErrorAction Stop }} catch {{}}; "
                      f"Start-Process -FilePath '{quoted}' -ArgumentList {args}")
            try:
                return popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                              "-Command", script], creationflags=flags, close_fds=True)
            except FileNotFoundError:
                pass  # no PowerShell: fall through and rely on /CLOSEAPPLICATIONS
        return popen([installer, *cls.INSTALLER_ARGS], creationflags=flags, close_fds=True)


def check_in_background(announce, repo: str = "Madhu-36/MXB", interval_hours: float = 24.0,
                        updater: "Updater | None" = None, frozen: bool | None = None):
    """
    The quiet daily check. Runs on a daemon thread, at most once per interval, and calls
    announce(text) only when a newer release exists. Network errors are logged, never shown.
    Returns the thread (or None when it's not time to check yet).
    """
    from utils.logger import log
    upd = updater or Updater(repo=repo)
    if not upd.should_check(interval_hours):
        return None

    def worker():
        try:
            info = upd.check()
        except UpdateError as e:
            log.info(f"Update check skipped: {e}")
            return
        except Exception as e:
            log.warning(f"Update check failed: {e}")
            return
        if info is not None:
            announce(update_message(info, upd.current, is_frozen() if frozen is None else frozen))

    thread = threading.Thread(target=worker, name="mxb-update-check", daemon=True)
    thread.start()
    return thread
