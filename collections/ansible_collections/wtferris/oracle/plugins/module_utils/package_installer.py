# -*- coding: utf-8 -*-

"""Install a single-directory package from a local or remote archive."""

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


class PackageInstallationError(Exception):
    """An archive could not be safely installed."""

    def __init__(self, message, md5sum=None, temporary_directory=None):
        self.md5sum = md5sum
        self.temporary_directory = temporary_directory
        super(PackageInstallationError, self).__init__(message)


def _result(md5sum, installed_directory="", temporary_directory="", changed=False):
    return {
        "md5sum": md5sum,
        "failed": False,
        "errors": [],
        "installed_directory": installed_directory,
        "temporary_directory": temporary_directory,
        "changed": changed,
    }


def _existing_inventory_target(inventory_directory, md5sum):
    link = os.path.join(inventory_directory, ".%s.md5" % md5sum)
    if not os.path.islink(link):
        return None
    target = os.path.realpath(link)
    if os.path.isdir(target):
        return target
    return None


def _open_source(source_url, insecure):
    parsed = urlparse(source_url)
    if parsed.scheme in ("http", "https"):
        if parsed.scheme == "https" and insecure and hasattr(ssl, "_create_unverified_context"):
            context = ssl._create_unverified_context()
            try:
                return build_opener(HTTPSHandler(context=context)).open(source_url)
            except TypeError:
                # Python 2.7 releases before HTTPSHandler accepted a context did
                # not verify HTTPS certificates by default.
                return urlopen(source_url)
        return urlopen(source_url)
    if parsed.scheme == "file":
        path = unquote(parsed.path)
        if parsed.netloc and parsed.netloc not in ("", "localhost"):
            path = "//%s%s" % (parsed.netloc, path)
    elif parsed.scheme:
        raise PackageInstallationError("Unsupported source URL scheme: %s" % parsed.scheme)
    else:
        path = source_url
    return open(path, "rb")


def _archive_kind(source_url):
    path = urlparse(source_url).path.lower()
    if path.endswith(".tar.gz") or path.endswith(".tgz"):
        return "tar"
    if path.endswith(".zip"):
        return "zip"
    raise PackageInstallationError(
        "Unsupported archive type for %s; expected .tgz, .tar.gz, or .zip" % source_url
    )


def _run(command):
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        stdout, stderr = process.communicate()
    except OSError as exc:
        raise PackageInstallationError(
            "Unable to execute %s: %s" % (command[0], exc)
        )
    if process.returncode:
        detail = (stderr or stdout or "no diagnostic output").strip()
        raise PackageInstallationError(
            "Command %r failed with exit status %s: %s"
            % (command, process.returncode, detail)
        )
    return stdout


def _tar(command, archive, extract_directory=None):
    """Run gzip and tar as a pipeline, without invoking a shell."""
    try:
        gzip_process = subprocess.Popen(
            ["gzip", "-dc", archive], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        tar_command = ["tar", command, "-"]
        if extract_directory is not None:
            tar_command.extend(["-C", extract_directory])
        tar_process = subprocess.Popen(
            tar_command, stdin=gzip_process.stdout, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, universal_newlines=True,
        )
        if gzip_process.stdout is not None:
            gzip_process.stdout.close()
        tar_stdout, tar_stderr = tar_process.communicate()
        gzip_stderr = gzip_process.communicate()[1]
    except OSError as exc:
        raise PackageInstallationError("Unable to execute gzip/tar: %s" % exc)
    if gzip_process.returncode:
        raise PackageInstallationError(
            "gzip failed with exit status %s: %s"
            % (gzip_process.returncode, gzip_stderr.decode("utf-8", "replace").strip())
        )
    if tar_process.returncode:
        raise PackageInstallationError(
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
            raise PackageInstallationError(
                "Archive contains unsafe path: %s" % raw_name
            )
        members.append(normalized)
    if not members:
        raise PackageInstallationError("Archive is empty")
    return members


def _inventory_link(inventory_directory, md5sum, destination):
    if not os.path.isdir(inventory_directory):
        os.makedirs(inventory_directory)
    link = os.path.join(inventory_directory, ".%s.md5" % md5sum)
    if os.path.lexists(link):
        os.unlink(link)
    os.symlink(os.path.abspath(destination), link)


def install_package(installation_path, source_url, temp_root=None, insecure=False,
                    skip_relocation=False, md5sum=None, inventory_directory=None,
                    force=False):
    """Download, verify, extract, and optionally relocate an archive package."""
    expected_md5 = md5sum.lower() if md5sum else None
    if expected_md5 and not re.match(r"^[0-9a-f]{32}$", expected_md5):
        raise PackageInstallationError("md5sum must contain exactly 32 hexadecimal characters")
    inventory_directory = os.path.expanduser(
        inventory_directory or "~/.package_installation"
    )
    tempdir = None
    calculated_md5 = None

    try:
        if expected_md5 and not force:
            target = _existing_inventory_target(inventory_directory, expected_md5)
            if target:
                return _result(expected_md5, target, changed=False)

        if not os.path.isdir(installation_path):
            os.makedirs(installation_path)
        root = temp_root or installation_path
        if not os.path.isdir(root):
            os.makedirs(root)
        tempdir = tempfile.mkdtemp(prefix="package-installer-", dir=root)
        extract_directory = os.path.join(tempdir, "extract")
        os.mkdir(extract_directory)
        kind = _archive_kind(source_url)
        archive = os.path.join(tempdir, "package.%s" % ("tar.gz" if kind == "tar" else "zip"))

        digest = hashlib.md5()
        source = _open_source(source_url, insecure)
        try:
            with open(archive, "wb") as output:
                while True:
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)
                    digest.update(block)
        finally:
            source.close()
        calculated_md5 = digest.hexdigest()
        if expected_md5 and calculated_md5 != expected_md5:
            raise PackageInstallationError(
                "MD5 checksum mismatch: expected %s, got %s"
                % (expected_md5, calculated_md5),
                md5sum=calculated_md5, temporary_directory=tempdir,
            )

        if kind == "tar":
            listing = _tar("-tf", archive)
        else:
            listing = _run(["unzip", "-Z1", archive])
        _validate_members(listing)

        if kind == "tar":
            _tar("-xf", archive, extract_directory)
        else:
            _run(["unzip", "-q", archive, "-d", extract_directory])

        top_entries = os.listdir(extract_directory)
        real_directories = [
            name for name in top_entries
            if os.path.isdir(os.path.join(extract_directory, name))
            and not os.path.islink(os.path.join(extract_directory, name))
        ]
        if len(top_entries) != 1 or len(real_directories) != 1:
            raise PackageInstallationError(
                "Archive must extract to exactly one top-level real directory"
            )
        source_directory = os.path.join(extract_directory, real_directories[0])

        if skip_relocation:
            return _result(calculated_md5, temporary_directory=tempdir, changed=True)

        destination = os.path.join(installation_path, real_directories[0])
        if os.path.isdir(destination) and not os.path.islink(destination) and not force:
            shutil.rmtree(tempdir)
            completed_tempdir = tempdir
            tempdir = None
            return _result(
                calculated_md5,
                destination,
                temporary_directory=completed_tempdir,
                changed=False,
            )

        if os.path.lexists(destination):
            if not force:
                raise PackageInstallationError(
                    "Destination already exists and is not a directory: %s" % destination
                )
            trash = destination + ".trash"
            if os.path.lexists(trash):
                if os.path.isdir(trash) and not os.path.islink(trash):
                    shutil.rmtree(trash)
                else:
                    os.unlink(trash)
            os.rename(destination, trash)

        shutil.move(source_directory, destination)
        _inventory_link(inventory_directory, calculated_md5, destination)
        shutil.rmtree(tempdir)
        completed_tempdir = tempdir
        tempdir = None
        return _result(
            calculated_md5,
            destination,
            temporary_directory=completed_tempdir,
            changed=True,
        )
    except PackageInstallationError as exc:
        if tempdir and os.path.isdir(tempdir):
            shutil.rmtree(tempdir)
        if exc.md5sum is None:
            exc.md5sum = calculated_md5
        if exc.temporary_directory is None:
            exc.temporary_directory = tempdir
        raise
    except Exception as exc:
        failed_tempdir = tempdir
        if tempdir and os.path.isdir(tempdir):
            shutil.rmtree(tempdir)
        raise PackageInstallationError(
            "Package installation failed: %s" % exc,
            md5sum=calculated_md5, temporary_directory=failed_tempdir,
        )
