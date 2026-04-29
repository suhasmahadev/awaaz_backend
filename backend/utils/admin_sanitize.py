SENSITIVE_ADMIN_FIELDS = {
    "fingerprint",
    "anon_id",
    "actor_anon_id",
    "reporters",
    "reporter_hash",
}


def sanitize_for_admin(data):
    if isinstance(data, list):
        return [sanitize_for_admin(item) for item in data]
    if isinstance(data, tuple):
        return tuple(sanitize_for_admin(item) for item in data)
    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            if key in SENSITIVE_ADMIN_FIELDS:
                continue
            cleaned[key] = sanitize_for_admin(value)
        return cleaned
    return data
