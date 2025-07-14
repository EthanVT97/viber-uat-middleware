from datetime import datetime
from typing import List, Dict

log_store: List[Dict] = []

def add_log(entry: Dict):
    """Add a log entry (newest first)"""
    log_store.insert(0, {
        "time": datetime.utcnow().isoformat(),
        **entry
    })
    if len(log_store) > 100:  # Keep only 100 logs
        log_store.pop()
