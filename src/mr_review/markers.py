NS = "mr-review"
PUBLISHED_PREFIX = f"<!-- {NS}:published"
DRAFT_PREFIX = f"<!-- {NS}:draft"
_NOTE_TOKEN = f"<!-- {NS}:"
_NEUTRAL = f"<!-​- {NS}:"  # zero-width space breaks the literal marker


def note_open(handle: int) -> str:
    return f"<!-- {NS}:note {handle} -->"


def note_close(handle: int) -> str:
    return f"<!-- {NS}:/note {handle} -->"


def neutralize(body: str) -> str:
    return body.replace(_NOTE_TOKEN, _NEUTRAL)
