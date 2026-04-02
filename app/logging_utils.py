import logging
import os
from logging.handlers import RotatingFileHandler

from app.config import Config


def init_logging() -> None:
    root_logger = logging.getLogger()
    if getattr(root_logger, "_autodoc_logging_initialized", False):
        return

    level = getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO)
    root_logger.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if Config.LOG_TO_FILE:
        log_path = Config.LOG_FILE_PATH
        log_dir = os.path.dirname(log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        if Config.LOG_RESET_EACH_RUN:
            with open(log_path, "w", encoding="utf-8"):
                pass
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=Config.LOG_MAX_BYTES,
            backupCount=Config.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    if Config.LOG_TO_CONSOLE:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    logging.getLogger("werkzeug").setLevel(level)
    root_logger._autodoc_logging_initialized = True
