import logging
import os
from logging.handlers import RotatingFileHandler

try:
    from pythonjsonlogger.json import JsonFormatter
except ImportError:  # python-json-logger < 3.1
    from pythonjsonlogger.jsonlogger import JsonFormatter

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, 'alyx_system.log')

# Handlers partagés : un seul descripteur sur le fichier, sinon la rotation échoue sous Windows
_file_handler = None
_console_handler = None

def _get_handlers():
    global _file_handler, _console_handler
    if _file_handler is None:
        # File handler (JSON format, rotation 5 Mo x 3)
        _file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
        _file_handler.setLevel(logging.DEBUG)
        _file_handler.setFormatter(JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s'))

        # Console handler (Readable format)
        _console_handler = logging.StreamHandler()
        _console_handler.setLevel(logging.INFO)
        _console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    return _file_handler, _console_handler

def get_logger(name):
    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        for handler in _get_handlers():
            logger.addHandler(handler)

    return logger
