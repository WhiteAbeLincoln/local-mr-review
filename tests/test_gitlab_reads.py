from pathlib import Path

import pytest

from mr_review.domain import MergeRef
from mr_review.forge.gitlab import GitLabForge
from mr_review.forge.glab import ForgeError, GlabRunner

FIX = Path(__file__).parent / "fixtures"


def fake_glab(responses):
    # responses: dict mapping a tuple-of-args-prefix -> stdout string
    def exec_runner(args, input):
        for prefix, out in responses.items():
            if tuple(args[: len(prefix)]) == prefix:
                return (0, out, "")
        raise AssertionError(f"unexpected glab args: {args}")

    return GlabRunner(exec_runner=exec_runner)


def make_forge():
    glab = fake_glab(
        {
            ("api", "user"): '{"username": "me"}',
            ("mr", "view"): (FIX / "mr_view.json").read_text(),
            ("mr", "note", "list"): (FIX / "mr_notes.json").read_text(),
        }
    )
    return GitLabForge(glab)


def test_fetch_mr_maps_metadata_and_project():
    mr = make_forge().fetch_mr(MergeRef(ref="1294"))
    assert mr.iid == "1294"
    assert mr.project == "grp/sub/repo"
    assert mr.head_sha == "HEAD"
    assert mr.current_user == "me"


def test_list_discussions_filters_system_and_skips_empty():
    discussions = make_forge().list_discussions(MergeRef(ref="1294"))
    ids = [d.native_id for d in discussions]
    assert "cccc3333" not in ids  # system-only discussion dropped
    assert ids == ["aaaa1111", "bbbb2222"]


def test_diff_position_taken_from_populated_note():
    d = make_forge().list_discussions(MergeRef(ref="1294"))[0]
    assert d.position is not None and d.position.new_line == 42
    assert d.position.new_path == "src/foo.py"


def test_note_ids_are_strings_and_mine_is_detected():
    d = make_forge().list_discussions(MergeRef(ref="1294"))[0]
    assert [n.native_id for n in d.notes] == ["501", "502"]
    assert [n.mine for n in d.notes] == [False, True]
    assert d.resolvable is True and d.resolved is False


def test_general_discussion_has_no_position():
    d = make_forge().list_discussions(MergeRef(ref="1294"))[1]
    assert d.position is None


def test_line_range_mapped_when_start_differs_from_end():
    # Test that a note with populated line_range (start != end) maps to tuple
    glab = fake_glab(
        {
            ("api", "user"): '{"username": "me"}',
            ("mr", "note", "list"): """[
  {
    "id": "range_diff",
    "individual_note": false,
    "notes": [
      {
        "id": 1001,
        "author": {"username": "reviewer"},
        "body": "Multi-line comment",
        "created_at": "2026-06-24T10:00:00Z",
        "updated_at": "2026-06-24T10:00:00Z",
        "system": false,
        "resolvable": true,
        "resolved": false,
        "type": "DiffNote",
        "position": {
          "new_path": "src/foo.py",
          "new_line": 10,
          "old_path": "src/foo.py",
          "old_line": null,
          "base_sha": "BASE",
          "start_sha": "START",
          "head_sha": "HEAD",
          "position_type": "text",
          "line_range": {
            "start": {"new_line": 10},
            "end": {"new_line": 15}
          }
        }
      }
    ]
  }
]""",
        }
    )
    forge = GitLabForge(glab)
    discussions = forge.list_discussions(MergeRef(ref="1294"))
    assert len(discussions) == 1
    assert discussions[0].position is not None
    assert discussions[0].position.line_range == (10, 15)


def test_line_range_is_none_when_start_equals_end():
    # Test that a note with line_range where start.new_line == end.new_line maps to None
    glab = fake_glab(
        {
            ("api", "user"): '{"username": "me"}',
            ("mr", "note", "list"): """[
  {
    "id": "range_equal",
    "individual_note": false,
    "notes": [
      {
        "id": 1002,
        "author": {"username": "reviewer"},
        "body": "Single-line note",
        "created_at": "2026-06-24T10:00:00Z",
        "updated_at": "2026-06-24T10:00:00Z",
        "system": false,
        "resolvable": true,
        "resolved": false,
        "type": "DiffNote",
        "position": {
          "new_path": "src/foo.py",
          "new_line": 5,
          "old_path": "src/foo.py",
          "old_line": null,
          "base_sha": "BASE",
          "start_sha": "START",
          "head_sha": "HEAD",
          "position_type": "text",
          "line_range": {
            "start": {"new_line": 5},
            "end": {"new_line": 5}
          }
        }
      }
    ]
  }
]""",
        }
    )
    forge = GitLabForge(glab)
    discussions = forge.list_discussions(MergeRef(ref="1294"))
    assert len(discussions) == 1
    assert discussions[0].position is not None
    assert discussions[0].position.line_range is None


def test_list_discussions_malformed_json_raises_forgeerror():
    # Fake glab returning a discussions list with a note missing the required 'author' field
    glab = fake_glab(
        {
            ("api", "user"): '{"username": "me"}',
            ("mr", "note", "list"): """[
  {
    "id": "d",
    "individual_note": true,
    "notes": [
      {
        "id": 1
      }
    ]
  }
]""",
        }
    )
    forge = GitLabForge(glab)
    with pytest.raises(ForgeError) as ei:
        forge.list_discussions(MergeRef(ref="1294"))
    assert "mr note list" in str(ei.value)


def test_fetch_mr_malformed_json_raises_forgeerror():
    # Fake glab returning an empty object (missing 'iid')
    glab = fake_glab(
        {
            ("api", "user"): '{"username": "me"}',
            ("mr", "view"): "{}",
        }
    )
    forge = GitLabForge(glab)
    with pytest.raises(ForgeError) as ei:
        forge.fetch_mr(MergeRef(ref="1294"))
    assert "mr view" in str(ei.value)


def test_malformed_current_user_raises_forgeerror():
    # Fake glab returning a dict with no 'username' field
    glab = fake_glab(
        {
            ("api", "user"): "{}",
            ("mr", "note", "list"): """[
  {
    "id": "d",
    "individual_note": true,
    "notes": [
      {
        "id": 1,
        "author": {"username": "reviewer"},
        "body": "Test",
        "created_at": "2026-06-24T10:00:00Z",
        "updated_at": "2026-06-24T10:00:00Z",
        "system": false,
        "resolvable": false,
        "resolved": false
      }
    ]
  }
]""",
        }
    )
    forge = GitLabForge(glab)
    with pytest.raises(ForgeError) as ei:
        forge.list_discussions(MergeRef(ref="1294"))
    assert "api user" in str(ei.value)
