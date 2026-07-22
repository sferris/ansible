# -*- coding: utf-8 -*-

"""Python 2-compatible helpers for running external executables."""

from __future__ import absolute_import, division, print_function

import os
import subprocess
import threading


class CommandTimeout(Exception):
    """Raised when an executable does not finish within its timeout."""

    def __init__(self, command, timeout):
        self.command = command
        self.timeout = timeout
        super(CommandTimeout, self).__init__(
            "%s timed out after %s seconds" % (command, timeout)
        )


class CommandResult(object):
    """Minimal subprocess.CompletedProcess equivalent for Python 2."""

    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _communicate_with_timeout(process, timeout, command):
    if timeout is None:
        return process.communicate()

    result = [None, None]
    errors = []

    def target():
        try:
            result[0], result[1] = process.communicate()
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        try:
            process.kill()
        except Exception:
            pass
        process.wait()
        raise CommandTimeout(command, timeout)
    if errors:
        raise errors[0]
    return result[0], result[1]


def _python2_run(
    args,
    stdout=None,
    stderr=None,
    universal_newlines=False,
    timeout=None,
    check=False,
    env=None,
    **kwargs
):
    if universal_newlines:
        kwargs["universal_newlines"] = True

    process = subprocess.Popen(
        args,
        stdout=stdout,
        stderr=stderr,
        env=env,
        **kwargs
    )
    stdout_data, stderr_data = _communicate_with_timeout(process, timeout, args)

    if check and process.returncode:
        raise subprocess.CalledProcessError(process.returncode, args, stdout_data)

    return CommandResult(process.returncode, stdout_data or "", stderr_data or "")


if hasattr(subprocess, "run"):
    _subprocess_run = subprocess.run
    EXECUTABLE_ERRORS = (OSError, subprocess.SubprocessError)
else:
    _subprocess_run = _python2_run
    EXECUTABLE_ERRORS = (OSError, subprocess.CalledProcessError, ValueError, CommandTimeout)


def run_executable(executable, arguments=None, timeout=10, runner=None, env=None, env_overrides=None):
    """Run an executable safely and return its status, stdout, and stderr.

    ``runner`` is injectable for callers that need to test command execution
    without starting a process. ``env_overrides`` is merged into a copy of the
    supplied environment, or the current process environment when omitted.
    """
    command = [executable] + list(arguments or [])
    environment = (env or os.environ).copy()
    environment.update(env_overrides or {})
    runner = runner or _subprocess_run
    return runner(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        timeout=timeout,
        check=False,
        env=environment,
    )
