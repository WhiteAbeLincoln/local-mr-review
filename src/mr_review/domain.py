from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class MergeRef:
    ref: str | None
    repo: str | None = None


@dataclass(frozen=True)
class DiffPosition:
    new_path: str | None
    old_path: str | None
    new_line: int | None
    old_line: int | None
    base_sha: str
    start_sha: str
    head_sha: str
    line_range: tuple[int, int] | None
    position_type: str


@dataclass(frozen=True)
class Note:
    native_id: str
    author: str
    mine: bool
    system: bool
    created_at: str
    updated_at: str
    body: str
    resolvable: bool
    resolved: bool


@dataclass(frozen=True)
class Discussion:
    native_id: str
    resolvable: bool
    resolved: bool
    position: DiffPosition | None
    notes: tuple[Note, ...]


@dataclass(frozen=True)
class MergeRequest:
    iid: str
    title: str
    web_url: str
    project: str
    base_sha: str
    start_sha: str
    head_sha: str
    current_user: str


def derive_resolution(notes: Iterable[Note]) -> tuple[bool, bool]:
    resolvable_notes = [n for n in notes if n.resolvable]
    if not resolvable_notes:
        return (False, False)
    return (True, all(n.resolved for n in resolvable_notes))
