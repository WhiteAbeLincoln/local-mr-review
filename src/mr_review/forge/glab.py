import json
import subprocess
from collections.abc import Callable

ExecRunner = Callable[[list[str], str | None], tuple[int, str, str]]


class ForgeError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        args_: list[str] | None = None,
        returncode: int | None = None,
        stderr: str | None = None,
    ) -> None:
        self.args_ = args_
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(message)


def _subprocess_exec(args: list[str], input: str | None) -> tuple[int, str, str]:
    proc = subprocess.run(["glab", *args], input=input, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


class GlabRunner:
    def __init__(self, exec_runner: ExecRunner | None = None) -> None:
        self._exec = exec_runner or _subprocess_exec

    def run(self, args: list[str], stdin: str | None = None) -> str:
        rc, out, err = self._exec(args, stdin)
        if rc != 0:
            raise ForgeError(
                f"glab {' '.join(args)} failed ({rc}): {err.strip()}",
                args_=args,
                returncode=rc,
                stderr=err,
            )
        return out

    def json(self, args: list[str]) -> object:
        out = self.run(args)
        try:
            return json.loads(out)
        except json.JSONDecodeError as e:
            raise ForgeError(f"glab {' '.join(args)} returned invalid JSON: {e}", args_=args) from e
