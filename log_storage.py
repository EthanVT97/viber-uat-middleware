log_store = []

def add_log(entry: dict):
    log_store.insert(0, entry)  # latest first
    if len(log_store) > 100:
        log_store.pop()
