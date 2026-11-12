"""Local, bounded logs with credential and signed-URL redaction."""
import logging
from logging.handlers import RotatingFileHandler
import re
import sys
from pathlib import Path
from echo.backend import paths
from echo.version import VERSION


def redact(text):
    text = str(text)
    text = re.sub(r"(?i)(https?://)[^/@\s]+@", r"\1[redacted]@", text)
    text = re.sub(r"(?i)(https?://[^\s?'\"]+)\?[^\s'\"]+", r"\1?[redacted]", text)
    text = re.sub(r"(?i)(bearer\s+)[\w.\-]+", r"\1[redacted]", text)
    text = re.sub(r"\b(?:sk-|ghp_|hf_)[A-Za-z0-9_\-]{8,}", "[redacted-key]", text)
    text = re.sub(r"(?i)((?:api[_ -]?key|token|password)\s*[=:]\s*)[^\s,;]+", r"\1[redacted]", text)
    return text


def log_dir():
    folder = Path(paths.config_dir()) / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


class SafeFormatter(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))


def setup():
    logger = logging.getLogger("echo")
    if not any(getattr(handler, '_echo_file_log', False) for handler in logger.handlers):
        handler = RotatingFileHandler(log_dir()/"echo.log", maxBytes=2*1024*1024, backupCount=2, encoding="utf-8")
        handler._echo_file_log = True
        handler.setFormatter(SafeFormatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.info('Echo %s startup; Python %s', VERSION, sys.version.split()[0])
        previous = sys.excepthook
        def uncaught(kind, value, traceback):
            logger.error('Unhandled application exception', exc_info=(kind, value, traceback))
            previous(kind, value, traceback)
        sys.excepthook = uncaught


def report():
    from echo.backend import model_fetch
    current = log_dir()/"echo.log"
    tail = current.read_text(encoding="utf-8", errors="replace")[-150000:] if current.exists() else "暂无日志。"
    return redact(f"Echo {VERSION}\n语音包状态: {model_fetch.progress()}\n\n{tail}")
