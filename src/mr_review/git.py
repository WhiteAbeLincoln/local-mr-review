import subprocess
from collections.abc import Callable

ExecRunner = Callable[[list[str], str | None], tuple[int, str, str]]


class GitError(RuntimeError):
    pass


def _subprocess_exec(args: list[str], input: str | None) -> tuple[int, str, str]:
    proc = subprocess.run(["git", *args], input=input, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


class GitRunner:
    def __init__(self, exec_runner: ExecRunner | None = None) -> None:
        self._exec = exec_runner or _subprocess_exec

    def _run(self, args: list[str]) -> str:
        rc, out, err = self._exec(args, None)
        if rc != 0:
            raise GitError(err.strip())
        return out

    def show(self, sha: str, path: str) -> str:
        return self._run(["show", f"{sha}:{path}"])

    def toplevel(self) -> str:
        return self._run(["rev-parse", "--show-toplevel"]).strip()
