import logging
import sys
from typing import Any, Dict


class KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            base["exc_info"] = self.formatException(record.exc_info)
        if hasattr(record, "extra_fields"):
            base.update(getattr(record, "extra_fields") or {})
        return " ".join(f"{k}={v}" for k, v in base.items())


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(KeyValueFormatter())
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()
    root.addHandler(handler)


def log_extra(**kwargs: Any) -> Dict[str, Any]:
    return {"extra_fields": kwargs}
