import pytest

from mr_review.markers import DRAFT_PREFIX, PUBLISHED_PREFIX, note_close, note_open
from mr_review.parse import ParseError, parse_thread


def build(reply="", my_note="my body", extra_draft=False):
    draft = f"{DRAFT_PREFIX} — write below -->"
    text = (
        "---\n"
        "thread: 1\npublish: true\nresolve: false\nedit_notes: [2]\n"
        "---\n\n"
        f"# header\n\n{PUBLISHED_PREFIX} -->\n\n"
        "### @reviewer · t · note 1\n\nWhy not the helper?\n\n"
        "### @me · t · note 2\n\n"
        f"{note_open(2)}\n{my_note}\n{note_close(2)}\n\n"
        f"{draft}\n\n{reply}"
    )
    if extra_draft:
        text += f"\n{draft}\n"
    return text


def test_parses_frontmatter_reply_and_note_edit():
    p = parse_thread(build(reply="Fixed in abc123.", my_note="Edited body."))
    assert p.frontmatter["publish"] is True
    assert p.frontmatter["edit_notes"] == [2]
    assert p.reply == "Fixed in abc123."
    assert p.note_edits == {2: "Edited body."}


def test_empty_reply_is_empty_string():
    assert parse_thread(build(reply="")).reply == ""


def test_missing_frontmatter_fails_loud():
    with pytest.raises(ParseError):
        parse_thread("# no frontmatter\n")


def test_missing_draft_marker_fails_loud():
    text = build().replace(f"{DRAFT_PREFIX} — write below -->", "")
    with pytest.raises(ParseError):
        parse_thread(text)


def test_duplicate_draft_marker_fails_loud():
    with pytest.raises(ParseError):
        parse_thread(build(extra_draft=True))


def test_unbalanced_note_marker_fails_loud():
    text = build().replace(note_close(2), "")
    with pytest.raises(ParseError):
        parse_thread(text)


def test_mismatched_note_handle_fails_loud():
    text = build().replace(note_close(2), note_close(3))
    with pytest.raises(ParseError):
        parse_thread(text)


def test_note_close_before_open_fails_loud():
    text = (
        "---\n"
        "thread: 1\npublish: true\nresolve: false\nedit_notes: [2]\n"
        "---\n\n"
        f"# header\n\n{note_close(2)}\n{PUBLISHED_PREFIX} -->\n\n"
        "### @reviewer · t · note 1\n\nWhy not the helper?\n\n"
        "### @me · t · note 2\n\n"
        f"{note_open(2)}\nEdited body.\n\n"
        f"{DRAFT_PREFIX} — write below -->\n\nFixed in abc123."
    )
    with pytest.raises(ParseError):
        parse_thread(text)


def test_interleaved_note_markers_fail_loud():
    text = (
        "---\n"
        "thread: 1\npublish: true\nresolve: false\nedit_notes: [2, 3]\n"
        "---\n\n"
        f"# header\n\n{PUBLISHED_PREFIX} -->\n\n"
        "### @reviewer · t · note 1\n\nWhy not the helper?\n\n"
        "### @me · t · note 2\n\n"
        f"{note_open(2)}\n"
        f"{note_open(3)}\n"
        "Edited body 2.\n"
        f"{note_close(2)}\n"
        "Edited body 3.\n"
        f"{note_close(3)}\n"
        f"{DRAFT_PREFIX} — write below -->\n\nFixed in abc123."
    )
    with pytest.raises(ParseError):
        parse_thread(text)
