from mr_review.domain import DiffPosition, Discussion, Note
from mr_review.store import (
    assign_handles,
    dict_to_position,
    load_state,
    position_to_dict,
    save_state,
)


def note(nid, body="b"):
    return Note(
        native_id=nid,
        author="me",
        mine=True,
        system=False,
        created_at="t",
        updated_at="t",
        body=body,
        resolvable=True,
        resolved=False,
    )


def disc(did, notes):
    return Discussion(
        native_id=did, resolvable=True, resolved=False, position=None, notes=tuple(notes)
    )


META = dict(
    forge="gitlab",
    project="g/r",
    mr="1",
    base_sha="B",
    start_sha="S",
    head_sha="H",
    current_user="me",
    synced_at="2026-06-25T00:00:00Z",
)


def test_first_sync_assigns_sequential_handles():
    doc = assign_handles(None, [disc("d1", [note("n1"), note("n2")])], **META)
    assert doc.threads[0].local_id == 1
    assert [n.local_id for n in doc.threads[0].notes] == [1, 2]


def test_existing_handles_are_reused_and_new_get_next():
    first = assign_handles(None, [disc("d1", [note("n1")])], **META)
    second = assign_handles(first, [disc("d1", [note("n1"), note("n2")])], **META)
    by_native = {n.native_id: n.local_id for n in second.threads[0].notes}
    assert by_native["n1"] == 1  # unchanged
    assert by_native["n2"] == 2  # next free


def test_deleted_note_handle_is_retired_not_reused():
    first = assign_handles(None, [disc("d1", [note("n1"), note("n2")])], **META)
    # n1 deleted upstream; a brand-new n3 arrives
    second = assign_handles(first, [disc("d1", [note("n2"), note("n3")])], **META)
    th = second.threads[0]
    by_native = {n.native_id: n.local_id for n in th.notes}
    assert by_native["n2"] == 2  # stable
    assert by_native["n3"] == 3  # NOT reusing retired 1
    assert 1 in th.retired_note_handles


def test_deleted_thread_handle_is_retired():
    first = assign_handles(None, [disc("d1", [note("n1")]), disc("d2", [note("n2")])], **META)
    second = assign_handles(first, [disc("d2", [note("n2")])], **META)
    assert [t.local_id for t in second.threads] == [2]
    assert 1 in second.retired_thread_handles


def test_round_trip_save_load(tmp_path):
    doc = assign_handles(None, [disc("d1", [note("n1")])], **META)
    p = tmp_path / "1.json"
    save_state(p, doc)
    loaded = load_state(p)
    assert loaded is not None
    assert loaded.threads[0].notes[0].native_id == "n1"
    assert load_state(tmp_path / "missing.json") is None


def test_position_line_range_round_trips_as_tuple():
    pos = DiffPosition(
        new_path="a.py",
        old_path=None,
        new_line=5,
        old_line=None,
        base_sha="B",
        start_sha="S",
        head_sha="H",
        line_range=(1, 5),
        position_type="text",
    )
    restored = dict_to_position(position_to_dict(pos))
    assert restored is not None
    assert restored.line_range == (1, 5)
    assert restored.new_line == 5 and restored.base_sha == "B"
