"""
Configuração centralizada de logging para o Focus Bulletin Tracker.

Handlers:
  - Arquivo : logs/focus_tracker.log  |  nível DEBUG  |  rotação diária, 7 dias
  - Console  : stdout                 |  nível INFO
"""

import logging
import logging.handlers
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_FILE = LOG_DIR / "focus_tracker.log"
_FMT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str) -> logging.Logger:
    """
    Retorna um logger configurado com handlers de arquivo e console.
    Idempotente: handlers são adicionados apenas uma vez por nome.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # evita duplicação com o root logger

    formatter = logging.Formatter(_FMT, datefmt=_DATE_FMT)

    # ── Handler de arquivo (DEBUG, rotação à meia-noite, 7 dias) ─────────────
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.TimedRotatingFileHandler(
        str(LOG_FILE),
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # ── Handler de console (INFO) ─────────────────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger
