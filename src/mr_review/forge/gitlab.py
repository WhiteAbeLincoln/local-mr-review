import re

from mr_review.domain import (
    DiffPosition,
    Discussion,
    MergeRef,
    MergeRequest,
    Note,
    derive_resolution,
)
from mr_review.forge.glab import ForgeError, GlabRunner

_MR_PATH = re.compile(r"^(.*?)/-/merge_requests/")


def _project_from_url(web_url: str) -> str:
    m = _MR_PATH.search(web_url)
    path = m.group(1) if m else web_url
    return path.split("gitlab.com/", 1)[-1].strip("/")


def _populated(pos: dict | None) -> bool:
    if not pos:
        return False
    return any(pos.get(k) is not None for k in ("new_path", "old_path", "new_line", "old_line"))


def _line_range(pos: dict) -> tuple[int, int] | None:
    lr = pos.get("line_range")
    if not lr:
        return None
    start = (lr.get("start") or {}).get("new_line")
    end = (lr.get("end") or {}).get("new_line")
    if start is None or end is None or start == end:
        return None
    return (start, end)


def _to_position(pos: dict) -> DiffPosition:
    return DiffPosition(
        new_path=pos.get("new_path"),
        old_path=pos.get("old_path"),
        new_line=pos.get("new_line"),
        old_line=pos.get("old_line"),
        base_sha=pos.get("base_sha") or "",
        start_sha=pos.get("start_sha") or "",
        head_sha=pos.get("head_sha") or "",
        line_range=_line_range(pos),
        position_type=pos.get("position_type") or "text",
    )


class GitLabForge:
    def __init__(self, glab: GlabRunner) -> None:
        self._glab = glab
        self._user: str | None = None

    def _mr_args(self, mr: MergeRef) -> list[str]:
        args: list[str] = [mr.ref] if mr.ref else []
        if mr.repo:
            args += ["-R", mr.repo]
        return args

    def _current_user(self) -> str:
        if self._user is None:
            data = self._glab.json(["api", "user"])
            try:
                self._user = data["username"]
            except (KeyError, TypeError) as e:
                raise ForgeError(
                    f"unexpected glab response for 'api user': missing/invalid field {e}"
                ) from e
        return self._user

    def fetch_mr(self, mr: MergeRef) -> MergeRequest:
        v = self._glab.json(["mr", "view", *self._mr_args(mr), "-F", "json"])
        try:
            refs = v.get("diff_refs") or {}
            return MergeRequest(
                iid=str(v["iid"]),
                title=v.get("title", ""),
                web_url=v.get("web_url", ""),
                project=_project_from_url(v.get("web_url", "")),
                base_sha=refs.get("base_sha", ""),
                start_sha=refs.get("start_sha", ""),
                head_sha=refs.get("head_sha", ""),
                current_user=self._current_user(),
            )
        except (KeyError, TypeError) as e:
            raise ForgeError(
                f"unexpected glab response for 'mr view': missing/invalid field {e}"
            ) from e

    def list_discussions(self, mr: MergeRef) -> list[Discussion]:
        raw = self._glab.json(["mr", "note", "list", *self._mr_args(mr), "-F", "json"])
        user = self._current_user()
        out: list[Discussion] = []
        try:
            for d in raw:
                notes: list[Note] = []
                position: DiffPosition | None = None
                for n in d["notes"]:
                    if n.get("system"):
                        continue
                    if position is None and _populated(n.get("position")):
                        position = _to_position(n["position"])
                    notes.append(
                        Note(
                            native_id=str(n["id"]),
                            author=n["author"]["username"],
                            mine=n["author"]["username"] == user,
                            system=False,
                            created_at=n.get("created_at", ""),
                            updated_at=n.get("updated_at", ""),
                            body=n.get("body", ""),
                            resolvable=bool(n.get("resolvable")),
                            resolved=bool(n.get("resolved")),
                        )
                    )
                if not notes:
                    continue
                resolvable, resolved = derive_resolution(notes)
                out.append(
                    Discussion(
                        native_id=str(d["id"]),
                        resolvable=resolvable,
                        resolved=resolved,
                        position=position,
                        notes=tuple(notes),
                    )
                )
        except (KeyError, TypeError) as e:
            raise ForgeError(
                f"unexpected glab response for 'mr note list': missing/invalid field {e}"
            ) from e
        return out

    def reply(self, mr: MergeRef, discussion_id: str, body: str) -> None:
        ref = [mr.ref] if mr.ref else []
        repo = ["-R", mr.repo] if mr.repo else []
        self._glab.run(["mr", "note", "create", *ref, "--reply", discussion_id, *repo], stdin=body)

    def edit_note(self, mr: MergeRef, discussion_id: str, note_id: str, body: str) -> None:
        # glab wants the MR ref BEFORE the note id: `glab mr note update <mr> <note-id>`
        # (verified against a live MR — passing the note id first makes glab read it
        # as the MR identifier and 404). When mr.ref is None, the note id alone is
        # used against the current branch's MR.
        ref = [mr.ref] if mr.ref else []
        repo = ["-R", mr.repo] if mr.repo else []
        self._glab.run(["mr", "note", "update", *ref, note_id, *repo], stdin=body)

    def set_resolved(self, mr: MergeRef, discussion_id: str, resolved: bool) -> None:
        # MR ref before the discussion id: `glab mr note resolve|reopen <mr> <discussion-id>`
        # (same arg-order requirement as update, verified against a live MR).
        verb = "resolve" if resolved else "reopen"
        ref = [mr.ref] if mr.ref else []
        repo = ["-R", mr.repo] if mr.repo else []
        self._glab.run(["mr", "note", verb, *ref, discussion_id, *repo])
