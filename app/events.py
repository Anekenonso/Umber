"""Event logging system implementing Phase 13 of the project worksheet.

Logs all conversation and webhook lifecycle events to both standard logging
and persistent evidence logs in evidence/logs/events.log.
"""
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

# Set up standard logger
logger = logging.getLogger("umber.events")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

LOGS_DIR = Path(__file__).resolve().parent.parent / "evidence" / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
EVENTS_LOG_FILE = LOGS_DIR / "events.log"


def log_event(event_type: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Emit an event in structured format.
    
    Appends to evidence/logs/events.log and logs to console.
    """
    payload = details or {}
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "payload": payload,
    }
    
    # Console output
    logger.info(f"{event_type}: {json.dumps(payload, default=str)}")
    
    # Append to file
    try:
        with open(EVENTS_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as e:
        logger.error(f"Failed to write event to {EVENTS_LOG_FILE}: {e}")
        
    return record
