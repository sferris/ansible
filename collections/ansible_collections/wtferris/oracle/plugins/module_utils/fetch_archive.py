# -*- coding: utf-8 -*-

"""Download and unpack an archive into a temporary directory."""

from __future__ import absolute_import, division, print_function

import hashlib
import os
import posixpath
import re
import shutil
import ssl
import subprocess
import tempfile

try:
    from urllib.parse import unquote, urlparse
    from urllib.request import HTTPSHandler, build_opener, urlopen
except ImportError:  # pragma: no cover - Python 2
    _urllib = __import__("urllib")
    _urlparse = __import__("urlparse")
    _urllib2 = __import__("urllib2")
    unquote = _urllib.unquote
    urlparse = _urlparse.urlparse
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


def fetch_archive(source_url, temporary_directory_root=None, insecure=False, md5sum=None):
    """Download, optionally verify, and unpack an archive into temporary storage."""
    expected_md5 = md5sum.lower() if md5sum else None
    if expected_md5 and not re.match(r"^[0-9a-f]{32}$", expected_md5):
        raise FetchArchiveError("md5sum must contain exactly 32 hexadecimal characters")

    temporary_directory = None
    calculated_md5 = None
    try:
        if temporary_directory_root and not os.path.isdir(temporary_directory_root):
            os.makedirs(temporary_directory_root)
        temporary_directory = tempfile.mkdtemp(
            prefix="fetch-archive-",
            dir=temporary_directory_root,
        )
        unpack_directory = os.path.join(temporary_directory, "extract")
        os.mkdir(unpack_directory)

        kind = _archive_kind(source_url)
        archive_path = os.path.join(
            temporary_directory,
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
                temporary_directory=temporary_directory,
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

        return {
            "changed": True,
            "failed": False,
            "errors": [],
            "md5sum": calculated_md5,
            "temporary_directory": temporary_directory,
            "unpack_directory": unpack_directory,
            "contents": sorted(os.listdir(unpack_directory)),
        }
    except FetchArchiveError as exc:
        failed_directory = temporary_directory
        if temporary_directory and os.path.isdir(temporary_directory):
            shutil.rmtree(temporary_directory)
        if exc.md5sum is None:
            exc.md5sum = calculated_md5
        if exc.temporary_directory is None:
            exc.temporary_directory = failed_directory
        raise
    except Exception as exc:
        failed_directory = temporary_directory
        if temporary_directory and os.path.isdir(temporary_directory):
            shutil.rmtree(temporary_directory)
        raise FetchArchiveError(
            "Archive unpack failed: %s" % exc,
            md5sum=calculated_md5,
            temporary_directory=failed_directory,
        )
