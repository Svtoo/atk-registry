"""Test doubles for the plugin CLI tests: a scripted stand-in for shell.run and
a capturing entry-point runner."""
import contextlib
import io
import subprocess


def _coerce(value, kwargs):
    """Mirrors subprocess: captured output is bytes unless text mode is on."""
    if kwargs.get("text") or kwargs.get("universal_newlines"):
        return value.decode() if isinstance(value, bytes) else value
    return value.encode() if isinstance(value, str) else value


def ok(stdout=""):
    def respond(cmd, kwargs):
        out = stdout
        if hasattr(kwargs.get("stdout"), "write"):
            data = out if isinstance(out, bytes) else out.encode()
            kwargs["stdout"].write(data)
            out = ""
        return subprocess.CompletedProcess(
            cmd, 0, stdout=_coerce(out, kwargs), stderr=_coerce("", kwargs))
    return respond


def fail(returncode=1, stderr=""):
    def respond(cmd, kwargs):
        err = _coerce(stderr, kwargs)
        if kwargs.get("check"):
            raise subprocess.CalledProcessError(returncode, cmd, stderr=err)
        return subprocess.CompletedProcess(
            cmd, returncode, stdout=_coerce("", kwargs), stderr=err)
    return respond


def interrupt():
    def respond(cmd, kwargs):
        raise KeyboardInterrupt()
    return respond


class FakeRun:
    """Plays back scripted (needle, respond) entries in call order and records
    every command; an unscripted or out-of-order call fails the test loudly."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.call_kwargs = []

    def __call__(self, cmd, **kwargs):
        argv = list(cmd)
        self.calls.append(argv)
        self.call_kwargs.append(kwargs)
        if not self.script:
            raise AssertionError("unexpected command: %s" % " ".join(argv))
        needle, respond = self.script.pop(0)
        joined = " ".join(argv)
        if needle not in joined:
            raise AssertionError("expected %r next, got: %s" % (needle, joined))
        return respond(argv, kwargs)

    def joined_calls(self):
        return [" ".join(c) for c in self.calls]

    def index_of(self, needle):
        for i, joined in enumerate(self.joined_calls()):
            if needle in joined:
                return i
        return -1

    def call_at(self, needle):
        return self.calls[self.index_of(needle)]

    def assert_done(self):
        if self.script:
            raise AssertionError(
                "unconsumed script entries: %s" % [n for n, _ in self.script])


class FakeHttp:
    """Plays back scripted (needle, response) entries in call order and records
    every request; an unscripted or out-of-order call fails the test loudly."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    def __call__(self, method, url, timeout=30, body=None):
        self.requests.append((method, url, body))
        target = "%s %s" % (method, url)
        if not self.script:
            raise AssertionError("unexpected request: %s" % target)
        needle, response = self.script.pop(0)
        if needle not in target:
            raise AssertionError("expected %r next, got: %s" % (needle, target))
        return response

    def assert_done(self):
        if self.script:
            raise AssertionError(
                "unconsumed script entries: %s" % [n for n, _ in self.script])


def invoke(argv):
    """Runs app.main(argv); returns (exit_code, stdout, stderr)."""
    from hindsight_cli import app
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = app.main(list(argv))
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return (0 if code is None else code), out.getvalue(), err.getvalue()
