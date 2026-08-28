#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, wtferris
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.wtferris.oracle.plugins.module_utils.package_installer import (
    PackageInstallationError,
    install_package,
)

__metaclass__ = type

DOCUMENTATION = r"""
---
module: package_install
short_description: Download, verify, and install a single-directory archive
version_added: "1.0.0"
description:
  - Downloads a local or remote gzip tar or ZIP archive into a configurable temporary root.
  - Calculates and optionally verifies its MD5 checksum before extraction.
  - Uses the operating system C(gzip), C(tar), and C(unzip) executables.
  - Installs the archive's single top-level directory and records it with a checksum symlink.
  - The implementation is also available from the collection's C(package_installer) module utility.
author:
  - wtferris
options:
  installation_path:
    description:
      - Parent directory beneath which the extracted package directory is installed.
    type: path
    required: true
  temporary_directory_root:
    description:
      - Parent directory in which the temporary working directory is created.
      - Defaults to O(installation_path).
    type: path
  source_url:
    description:
      - Local path or C(file), C(http), or C(https) URL of a C(.tgz), C(.tar.gz), or C(.zip) archive.
    type: str
    required: true
  insecure:
    description:
      - Disable HTTPS certificate verification.
      - Has no effect for non-HTTPS sources.
    type: bool
    default: false
  skip_post_relocation:
    description:
      - Leave the extracted package in the temporary directory instead of moving it into O(installation_path).
      - The caller is responsible for removing the returned temporary directory.
    type: bool
    default: false
  md5sum:
    description:
      - Optional expected 32-character MD5 checksum.
      - A valid package inventory entry for this checksum makes the operation idempotent unless O(force=true).
    type: str
  package_inventory_directory:
    description:
      - Directory containing checksum symlinks for installed packages.
    type: path
    default: ~/.package_installation
  force:
    description:
      - Reinstall even when the checksum inventory identifies an existing installation.
      - An existing destination is renamed with a C(.trash) suffix; an older C(.trash) is removed first.
    type: bool
    default: false
requirements:
  - Python 2.7 or newer
  - gzip and tar for gzip tar archives
  - unzip for ZIP archives
notes:
  - Downloads are completed and checksums verified before extraction.
  - Archives must contain exactly one top-level directory.
  - Temporary content is removed after normal installation and on failure.
"""

EXAMPLES = r"""
- name: Install an Oracle archive outside the remote user's home
  wtferris.oracle.package_install:
    installation_path: /u01/stage
    temporary_directory_root: /u01/tmp
    source_url: https://packages.example.com/oracle/db-home.tar.gz
    md5sum: 0123456789abcdef0123456789abcdef
  register: package

- name: Extract a local ZIP and retain the temporary directory
  wtferris.oracle.package_install:
    installation_path: /opt/software
    source_url: file:///var/tmp/package.zip
    skip_post_relocation: true
  register: extracted_package
"""

RETURN = r"""
md5sum:
  description: Calculated MD5 checksum, or the supplied checksum for an inventory short circuit.
  returned: always
  type: str
failed:
  description: Whether installation failed.
  returned: always
  type: bool
errors:
  description: Installation errors; empty on success.
  returned: always
  type: list
  elements: str
installed_directory:
  description: Installed package directory, or an empty string when relocation was skipped.
  returned: always
  type: str
temporary_directory:
  description: Working directory path used for the operation. It remains present only when relocation was skipped.
  returned: always
  type: str
changed:
  description: Whether the package was extracted or installed.
  returned: success
  type: bool
"""


def main():
    module = AnsibleModule(
        argument_spec={
            "installation_path": {"type": "path", "required": True},
            "temporary_directory_root": {"type": "path", "default": None},
            "source_url": {"type": "str", "required": True},
            "insecure": {"type": "bool", "default": False},
            "skip_post_relocation": {"type": "bool", "default": False},
            "md5sum": {"type": "str", "default": None},
            "package_inventory_directory": {
                "type": "path",
                "default": "~/.packages",
            },
            "force": {"type": "bool", "default": False},
        },
        supports_check_mode=False,
    )

    try:
        result = install_package(
            installation_path=module.params["installation_path"],
            temp_root=module.params["temporary_directory_root"],
            source_url=module.params["source_url"],
            insecure=module.params["insecure"],
            skip_relocation=module.params["skip_post_relocation"],
            md5sum=module.params["md5sum"],
            inventory_directory=module.params["package_inventory_directory"],
            force=module.params["force"],
        )
    except PackageInstallationError as exc:
        module.fail_json(
            msg=str(exc),
            md5sum=exc.md5sum or "",
            errors=[str(exc)],
            installed_directory="",
            temporary_directory=exc.temporary_directory or "",
        )

    module.exit_json(**result)


if __name__ == "__main__":
    main()
