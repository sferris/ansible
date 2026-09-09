# -*- coding: utf-8 -*-

"""Download and unpack an archive into a temporary directory."""

from __future__ import absolute_import, division, print_function

import errno
import hashlib
import os
import posixpath
import re
import shutil
import ssl
import subprocess
import tempfile
import time

try:
    from urllib.parse import unquote, urlparse, urlunparse
    from urllib.request import HTTPSHandler, build_opener, urlopen
except ImportError:  # pragma: no cover - Python 2
    _urllib = __import__("urllib")
    _urlparse = __import__("urlparse")
    _urllib2 = __import__("urllib2")
    unquote = _urllib.unquote
    urlparse = _urlparse.urlparse
    urlunparse = _urlparse.urlunparse
    HTTPSHandler = _urllib2.HTTPSHandler
    build_opener = _urllib2.build_opener
    urlopen = _urllib2.urlopen


class FetchArchiveError(Exception):
    """An archive could not be downloaded, verified, or unpacked."""

    def __init__(self, message, md5sum=None, temporary_directory=None):
        self.md5sum = md5sum
        self.temporary_directory = temporary_directory
        super(FetchArchiveError, self).__init__(message)


def _open_source(source_url, insecure):
    parsed = urlparse(source_url)
    if parsed.scheme in ("http", "https"):
        if parsed.scheme == "https" and insecure and hasattr(ssl, "_create_unverified_context"):
            context = ssl._create_unverified_context()
            try:
                return build_opener(HTTPSHandler(context=context)).open(source_url)
            except TypeError:
                # Early Python 2.7 releases did not verify HTTPS certificates
                # and did not accept an SSL context on HTTPSHandler.
                return urlopen(source_url)
        return urlopen(source_url)
    if parsed.scheme == "file":
        path = unquote(parsed.path)
        if parsed.netloc and parsed.netloc not in ("", "localhost"):
            path = "//%s%s" % (parsed.netloc, path)
    elif parsed.scheme:
        raise FetchArchiveError("Unsupported source URL scheme: %s" % parsed.scheme)
    else:
        path = source_url
    return open(path, "rb")


def _archive_kind(source_url):
    path = urlparse(source_url).path.lower()
    if path.endswith((".tar.gz", ".tgz")):
        return "tar"
    if path.endswith(".zip"):
        return "zip"
    raise FetchArchiveError(
        "Unsupported archive type for %s; expected .tgz, .tar.gz, or .zip" % source_url
    )


def _run(command):
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        stdout, stderr = process.communicate()
    except OSError as exc:
        raise FetchArchiveError("Unable to execute %s: %s" % (command[0], exc))
    if process.returncode:
        detail = (stderr or stdout or "no diagnostic output").strip()
        raise FetchArchiveError(
            "Command %r failed with exit status %s: %s"
            % (command, process.returncode, detail)
        )
    return stdout


def _tar(command, archive, extract_directory=None):
    """Run gzip and tar as a pipeline without invoking a shell."""
    try:
        gzip_process = subprocess.Popen(
            ["gzip", "-dc", archive],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        tar_command = ["tar", command, "-"]
        if extract_directory is not None:
            tar_command.extend(["-C", extract_directory])
        tar_process = subprocess.Popen(
            tar_command,
            stdin=gzip_process.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        if gzip_process.stdout is not None:
            gzip_process.stdout.close()
        tar_stdout, tar_stderr = tar_process.communicate()
        gzip_stderr = gzip_process.communicate()[1]
    except OSError as exc:
        raise FetchArchiveError("Unable to execute gzip/tar: %s" % exc)
    if gzip_process.returncode:
        raise FetchArchiveError(
            "gzip failed with exit status %s: %s"
            % (gzip_process.returncode, gzip_stderr.decode("utf-8", "replace").strip())
        )
    if tar_process.returncode:
        raise FetchArchiveError(
            "tar failed with exit status %s: %s"
            % (tar_process.returncode, (tar_stderr or "no diagnostic output").strip())
        )
    return tar_stdout


def _validate_members(listing):
    members = []
    for raw_name in listing.splitlines():
        name = raw_name.strip().replace("\\", "/")
        if not name:
            continue
        drive, unused = os.path.splitdrive(name)
        normalized = posixpath.normpath(name)
        if drive or name.startswith("/") or normalized == ".." or normalized.startswith("../"):
            raise FetchArchiveError("Archive contains unsafe path: %s" % raw_name)
        members.append(normalized)
    if not members:
        raise FetchArchiveError("Archive is empty")
    return members


def normalize_source_url(source_url):
    """Return a stable source identity without URL fragments."""
    parsed = urlparse(source_url)
    if not parsed.scheme:
        return "file://" + os.path.realpath(os.path.abspath(os.path.expanduser(source_url)))
    if parsed.scheme.lower() == "file":
        path = unquote(parsed.path)
        if parsed.netloc and parsed.netloc not in ("", "localhost"):
            path = "//%s%s" % (parsed.netloc, path)
        return "file://" + os.path.realpath(os.path.abspath(os.path.expanduser(path)))

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    return urlunparse((scheme, netloc, path, parsed.params, parsed.query, ""))


def _archive_identity(source_url, expected_md5):
    if expected_md5:
        return "md5-" + expected_md5
    normalized = normalize_source_url(source_url).encode("utf-8")
    return "url-" + hashlib.sha256(normalized).hexdigest()


def _completed_result(temporary_directory):
    marker = os.path.join(temporary_directory, ".complete")
    unpack_directory = os.path.join(temporary_directory, "extract")
    if not os.path.isfile(marker) or not os.path.isdir(unpack_directory):
        return None
    try:
        stream = open(marker, "r")
        try:
            calculated_md5 = stream.readline().strip().lower()
        finally:
            stream.close()
    except (IOError, OSError):
        return None
    if not re.match(r"^[0-9a-f]{32}$", calculated_md5):
        return None
    return {
        "changed": False,
        "failed": False,
        "errors": [],
        "md5sum": calculated_md5,
        "temporary_directory": temporary_directory,
        "unpack_directory": unpack_directory,
        "contents": sorted(os.listdir(unpack_directory)),
    }


def _acquire_lock(lock_directory, completed_directory, force, lock_timeout):
    deadline = time.time() + lock_timeout
    while True:
        try:
            os.mkdir(lock_directory)
            return True, None
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
        if not force:
            completed = _completed_result(completed_directory)
            if completed:
                return False, completed
        if time.time() >= deadline:
            raise FetchArchiveError(
                "Timed out waiting for archive lock %s after %s seconds"
                % (lock_directory, lock_timeout)
            )
        time.sleep(0.1)


def fetch_archive(source_url, installation_path=None, insecure=False, md5sum=None,
                  force=False, lock_timeout=300):
    """Download, optionally verify, and unpack an archive into cached storage."""
    expected_md5 = md5sum.lower() if md5sum else None
    if expected_md5 and not re.match(r"^[0-9a-f]{32}$", expected_md5):
        raise FetchArchiveError("md5sum must contain exactly 32 hexadecimal characters")
    if lock_timeout < 0:
        raise FetchArchiveError("lock_timeout must be zero or greater")

    kind = _archive_kind(source_url)
    root = os.path.abspath(os.path.expanduser(installation_path or tempfile.gettempdir()))
    if not os.path.isdir(root):
        os.makedirs(root)

    identity = _archive_identity(source_url, expected_md5)
    completed_directory = os.path.join(root, "fetch-archive-" + identity)
    lock_directory = completed_directory + ".lock"
    staging_directory = None
    calculated_md5 = None
    lock_acquired = False
    try:
        lock_acquired, completed = _acquire_lock(
            lock_directory, completed_directory, force, lock_timeout
        )
        if completed:
            return completed
        if not force:
            completed = _completed_result(completed_directory)
            if completed:
                return completed

        staging_directory = tempfile.mkdtemp(
            prefix="." + os.path.basename(completed_directory) + ".staging-",
            dir=root,
        )
        unpack_directory = os.path.join(staging_directory, "extract")
        os.mkdir(unpack_directory)
        archive_path = os.path.join(
            staging_directory,
            "archive.%s" % ("tar.gz" if kind == "tar" else "zip"),
        )

        digest = hashlib.md5()
        source = _open_source(source_url, insecure)
        try:
            output = open(archive_path, "wb")
            try:
                while True:
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)
                    digest.update(block)
            finally:
                output.close()
        finally:
            source.close()

        calculated_md5 = digest.hexdigest()
        if expected_md5 and calculated_md5 != expected_md5:
            raise FetchArchiveError(
                "MD5 checksum mismatch: expected %s, got %s"
                % (expected_md5, calculated_md5),
                md5sum=calculated_md5,
                temporary_directory=staging_directory,
            )

        if kind == "tar":
            listing = _tar("-tf", archive_path)
        else:
            listing = _run(["unzip", "-Z1", archive_path])
        _validate_members(listing)

        if kind == "tar":
            _tar("-xf", archive_path, unpack_directory)
        else:
            _run(["unzip", "-q", archive_path, "-d", unpack_directory])
        os.unlink(archive_path)

        marker = open(os.path.join(staging_directory, ".complete"), "w")
        try:
            marker.write(calculated_md5 + "\n")
        finally:
            marker.close()

        trash_directory = completed_directory + ".trash"
        moved_previous = False
        if os.path.lexists(completed_directory):
            if os.path.lexists(trash_directory):
                if os.path.isdir(trash_directory) and not os.path.islink(trash_directory):
                    shutil.rmtree(trash_directory)
                else:
                    os.unlink(trash_directory)
            os.rename(completed_directory, trash_directory)
            moved_previous = True
        try:
            os.rename(staging_directory, completed_directory)
            staging_directory = None
        except Exception:
            if moved_previous and not os.path.lexists(completed_directory):
                os.rename(trash_directory, completed_directory)
            raise
        if moved_previous:
            shutil.rmtree(trash_directory)

        result = _completed_result(completed_directory)
        if result is None:
            raise FetchArchiveError("Completed archive cache could not be validated")
        result["changed"] = True
        return result
    except FetchArchiveError as exc:
        failed_directory = staging_directory
        if staging_directory and os.path.isdir(staging_directory):
            shutil.rmtree(staging_directory)
        if exc.md5sum is None:
            exc.md5sum = calculated_md5
        if exc.temporary_directory is None:
            exc.temporary_directory = failed_directory
        raise
    except Exception as exc:
        failed_directory = staging_directory
        if staging_directory and os.path.isdir(staging_directory):
            shutil.rmtree(staging_directory)
        raise FetchArchiveError(
            "Archive fetch failed: %s" % exc,
            md5sum=calculated_md5,
            temporary_directory=failed_directory,
        )
    finally:
        if lock_acquired and os.path.isdir(lock_directory):
            try:
                os.rmdir(lock_directory)
            except OSError:
                pass
