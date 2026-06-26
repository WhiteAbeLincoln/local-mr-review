# tests/fakes.py
from dataclasses import replace

from mr_review.domain import Note
from mr_review.git import GitRunner


class FakeForge:
    def __init__(self, mr, discussions):
        self._mr = mr
        self._discussions = list(discussions)
        self.calls = []

    def fetch_mr(self, mr):
        return self._mr

    def list_discussions(self, mr):
        return list(self._discussions)

    def reply(self, mr, discussion_id, body):
        self.calls.append(("reply", discussion_id, body))
        for i, disc in enumerate(self._discussions):
            if disc.native_id == discussion_id:
                new_note = Note(
                    native_id=f"{discussion_id}-r{len(disc.notes)}",
                    author=self._mr.current_user,
                    mine=True,
                    system=False,
                    created_at="t",
                    updated_at="t",
                    body=body,
                    resolvable=True,
                    resolved=False,
                )
                self._discussions[i] = replace(disc, notes=disc.notes + (new_note,))
                break

    def edit_note(self, mr, discussion_id, note_id, body):
        self.calls.append(("edit", discussion_id, note_id, body))
        for i, disc in enumerate(self._discussions):
            if disc.native_id == discussion_id:
                new_notes = tuple(
                    replace(n, body=body) if n.native_id == note_id else n for n in disc.notes
                )
                self._discussions[i] = replace(disc, notes=new_notes)
                break

    def set_resolved(self, mr, discussion_id, resolved):
        self.calls.append(("resolve", discussion_id, resolved))
        for i, disc in enumerate(self._discussions):
            if disc.native_id == discussion_id:
                self._discussions[i] = replace(disc, resolved=resolved)
                break


def fake_git(text=""):
    def exec_runner(args, input):
        return (0, text, "")

    return GitRunner(exec_runner=exec_runner)
