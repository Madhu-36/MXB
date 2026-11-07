import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

def setup_logger():
    try:
        from utils.paths import logs_dir
        log_dir = logs_dir()
    except Exception:
        log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("MXB")
    logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers
    if not logger.handlers:
        file_handler = RotatingFileHandler(
            str(log_dir / "mxb_core.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)s] [%(module)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        if not getattr(sys, "frozen", False):
            # The windowed build has no console; its stderr is logs/console.log, which would
            # otherwise duplicate this rotating log forever. Source runs keep console output.
            logger.addHandler(console_handler)

    return logger

log = setup_logger()
