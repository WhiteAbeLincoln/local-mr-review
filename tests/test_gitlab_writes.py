from mr_review.domain import MergeRef
from mr_review.forge.gitlab import GitLabForge
from mr_review.forge.glab import GlabRunner


def recording_forge():
    calls = []

    def exec_runner(args, input):
        calls.append((args, input))
        return (0, "{}", "")

    return GitLabForge(GlabRunner(exec_runner=exec_runner)), calls


def test_reply_uses_create_reply_with_stdin_body():
    forge, calls = recording_forge()
    forge.reply(MergeRef(ref="1294", repo="g/r"), "abc12345", "Thanks!")
    args, stdin = calls[0]
    assert args[:4] == ["mr", "note", "create", "1294"]
    assert "--reply" in args and "abc12345" in args
    assert "-R" in args and "g/r" in args
    assert stdin == "Thanks!"


def test_edit_note_uses_update_with_mr_before_note_id_and_stdin():
    # glab reads `update <mr> <note-id>`; the MR ref MUST precede the note id
    # (verified against a live MR — the reverse order 404s).
    forge, calls = recording_forge()
    forge.edit_note(MergeRef(ref="1294"), "abc", "502", "Revised")
    args, stdin = calls[0]
    assert args == ["mr", "note", "update", "1294", "502"]
    assert stdin == "Revised"


def test_edit_note_includes_repo_flag():
    forge, calls = recording_forge()
    forge.edit_note(MergeRef(ref="1294", repo="g/r"), "abc", "502", "Revised")
    args, stdin = calls[0]
    assert "-R" in args and "g/r" in args
    assert stdin == "Revised"


def test_set_resolved_true_resolves_false_reopens():
    # `resolve|reopen <mr> <discussion-id>`: MR ref before the discussion id
    # (verified against a live MR — the reverse order fails to find the MR).
    forge, calls = recording_forge()
    forge.set_resolved(MergeRef(ref="1294"), "abc12345", True)
    forge.set_resolved(MergeRef(ref="1294"), "abc12345", False)
    assert calls[0][0] == ["mr", "note", "resolve", "1294", "abc12345"]
    assert calls[1][0] == ["mr", "note", "reopen", "1294", "abc12345"]


def test_set_resolved_includes_repo_flag():
    forge, calls = recording_forge()
    forge.set_resolved(MergeRef(ref="1294", repo="g/r"), "abc12345", True)
    forge.set_resolved(MergeRef(ref="1294", repo="g/r"), "abc12345", False)
    assert "-R" in calls[0][0] and "g/r" in calls[0][0]
    assert "-R" in calls[1][0] and "g/r" in calls[1][0]
