import pytest

from mr_review.forge.glab import ForgeError, GlabRunner


def make_runner(returncode, stdout="", stderr=""):
    calls = []

    def exec_runner(args, input):
        calls.append((args, input))
        return (returncode, stdout, stderr)

    return GlabRunner(exec_runner=exec_runner), calls


def test_run_returns_stdout_and_forwards_args_and_stdin():
    runner, calls = make_runner(0, stdout="ok\n")
    out = runner.run(["mr", "note", "create", "1", "--reply", "abc"], stdin="hello")
    assert out == "ok\n"
    assert calls == [(["mr", "note", "create", "1", "--reply", "abc"], "hello")]


def test_run_raises_forgeerror_with_stderr_on_failure():
    runner, _ = make_runner(1, stderr="401 Unauthorized")
    with pytest.raises(ForgeError) as ei:
        runner.run(["mr", "view", "1"])
    assert ei.value.returncode == 1
    assert "401 Unauthorized" in ei.value.stderr


def test_json_parses_stdout():
    runner, _ = make_runner(0, stdout='[{"id": 1}]')
    assert runner.json(["mr", "note", "list"]) == [{"id": 1}]


def test_json_raises_forgeerror_on_invalid_json():
    runner, _ = make_runner(0, stdout="not json{")
    with pytest.raises(ForgeError) as ei:
        runner.json(["mr", "note", "list"])
    assert "invalid JSON" in str(ei.value)
    assert ei.value.args_ == ["mr", "note", "list"]
