from mr_review.domain import Note, derive_resolution


def note(resolvable, resolved):
    return Note(
        native_id="n",
        author="a",
        mine=False,
        system=False,
        created_at="t",
        updated_at="t",
        body="b",
        resolvable=resolvable,
        resolved=resolved,
    )


def test_thread_resolvable_when_any_note_is_resolvable():
    assert derive_resolution([note(True, False), note(False, False)]) == (True, False)


def test_thread_resolved_only_when_all_resolvable_notes_resolved():
    assert derive_resolution([note(True, True), note(True, True)]) == (True, True)
    assert derive_resolution([note(True, True), note(True, False)]) == (True, False)


def test_non_resolvable_thread_is_unresolvable_and_not_resolved():
    assert derive_resolution([note(False, False)]) == (False, False)
    assert derive_resolution([]) == (False, False)
