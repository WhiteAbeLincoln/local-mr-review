import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mr_review.domain import DiffPosition


@dataclass
class StoredNote:
    local_id: int
    native_id: str
    author: str
    mine: bool
    created_at: str
    updated_at: str
    body: str
    resolvable: bool
    resolved: bool


@dataclass
class StoredThread:
    local_id: int
    native_id: str
    resolvable: bool
    resolved: bool
    position: dict | None
    notes: list[StoredNote]
    retired_note_handles: list[int] = field(default_factory=list)


@dataclass
class StateDoc:
    forge: str
    project: str
    mr: str
    base_sha: str
    start_sha: str
    head_sha: str
    current_user: str
    synced_at: str
    retired_thread_handles: list[int] = field(default_factory=list)
    threads: list[StoredThread] = field(default_factory=list)


def position_to_dict(p: DiffPosition | None) -> dict | None:
    return None if p is None else asdict(p)


def position_is_outdated(position: dict | None, current_head_sha: str) -> bool:
    if not position:
        return False
    head = position.get("head_sha")
    return bool(head) and bool(current_head_sha) and head != current_head_sha


def dict_to_position(d: dict | None) -> DiffPosition | None:
    if d is None:
        return None
    lr = d.get("line_range")
    return DiffPosition(
        new_path=d.get("new_path"),
        old_path=d.get("old_path"),
        new_line=d.get("new_line"),
        old_line=d.get("old_line"),
        base_sha=d.get("base_sha", ""),
        start_sha=d.get("start_sha", ""),
        head_sha=d.get("head_sha", ""),
        line_range=tuple(lr) if lr else None,
        position_type=d.get("position_type", "text"),
    )


def _next_handle(used: set[int], retired: list[int]) -> int:
    pool = used | set(retired)
    return (max(pool) + 1) if pool else 1


def assign_handles(
    prev,
    discussions,
    *,
    forge,
    project,
    mr,
    base_sha,
    start_sha,
    head_sha,
    current_user,
    synced_at,
):
    prev_threads = {t.native_id: t for t in prev.threads} if prev else {}
    prev_thread_ids = set(prev_threads)
    retired_threads = list(prev.retired_thread_handles) if prev else []
    used_thread_handles = {t.local_id for t in prev.threads} if prev else set()

    new_threads: list[StoredThread] = []
    seen_thread_ids: set[str] = set()
    for d in discussions:
        seen_thread_ids.add(d.native_id)
        prior = prev_threads.get(d.native_id)
        if prior:
            t_local = prior.local_id
            prev_notes = {n.native_id: n for n in prior.notes}
            retired_notes = list(prior.retired_note_handles)
            used_note_handles = {n.local_id for n in prior.notes}
        else:
            t_local = _next_handle(used_thread_handles, retired_threads)
            used_thread_handles.add(t_local)
            prev_notes, retired_notes, used_note_handles = {}, [], set()

        seen_note_ids: set[str] = set()
        stored_notes: list[StoredNote] = []
        for n in d.notes:
            seen_note_ids.add(n.native_id)
            pn = prev_notes.get(n.native_id)
            if pn:
                n_local = pn.local_id
            else:
                n_local = _next_handle(used_note_handles, retired_notes)
                used_note_handles.add(n_local)
            stored_notes.append(
                StoredNote(
                    local_id=n_local,
                    native_id=n.native_id,
                    author=n.author,
                    mine=n.mine,
                    created_at=n.created_at,
                    updated_at=n.updated_at,
                    body=n.body,
                    resolvable=n.resolvable,
                    resolved=n.resolved,
                )
            )
        # retire note handles whose native id vanished
        for native_id, pn in prev_notes.items():
            if native_id not in seen_note_ids and pn.local_id not in retired_notes:
                retired_notes.append(pn.local_id)

        new_threads.append(
            StoredThread(
                local_id=t_local,
                native_id=d.native_id,
                resolvable=d.resolvable,
                resolved=d.resolved,
                position=position_to_dict(d.position),
                notes=stored_notes,
                retired_note_handles=sorted(retired_notes),
            )
        )

    for native_id in prev_thread_ids - seen_thread_ids:
        h = prev_threads[native_id].local_id
        if h not in retired_threads:
            retired_threads.append(h)

    return StateDoc(
        forge=forge,
        project=project,
        mr=mr,
        base_sha=base_sha,
        start_sha=start_sha,
        head_sha=head_sha,
        current_user=current_user,
        synced_at=synced_at,
        retired_thread_handles=sorted(retired_threads),
        threads=new_threads,
    )


def save_state(path: Path, doc: StateDoc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(doc), indent=2))


def load_state(path: Path) -> StateDoc | None:
    if not path.exists():
        return None
    raw = json.loads(path.read_text())
    threads = [
        StoredThread(
            local_id=t["local_id"],
            native_id=t["native_id"],
            resolvable=t["resolvable"],
            resolved=t["resolved"],
            position=t["position"],
            notes=[StoredNote(**n) for n in t["notes"]],
            retired_note_handles=t.get("retired_note_handles", []),
        )
        for t in raw["threads"]
    ]
    return StateDoc(
        forge=raw["forge"],
        project=raw["project"],
        mr=raw["mr"],
        base_sha=raw["base_sha"],
        start_sha=raw["start_sha"],
        head_sha=raw["head_sha"],
        current_user=raw["current_user"],
        synced_at=raw["synced_at"],
        retired_thread_handles=raw.get("retired_thread_handles", []),
        threads=threads,
    )
