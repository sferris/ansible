#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, wtferris
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.wtferris.oracle.plugins.module_utils.archive_unpack import (
    ArchiveUnpackError,
    unpack_archive,
)

__metaclass__ = type

DOCUMENTATION = r"""
---
module: archive_unpack
short_description: Download and unpack an archive into temporary storage
version_added: "1.0.0"
description:
  - Downloads a local or remote gzip tar or ZIP archive into a temporary working directory.
  - Calculates and optionally verifies its MD5 checksum before extraction.
  - Uses the operating system C(gzip), C(tar), and C(unzip) executables.
  - Preserves the temporary directory so another task or module can process the unpacked contents.
  - The implementation is also available from the collection's C(archive_unpack) module utility.
author:
  - wtferris
options:
  source_url:
    description:
      - Local path or C(file), C(http), or C(https) URL of a C(.tgz), C(.tar.gz), or C(.zip) archive.
    type: str
    required: true
  temporary_directory_root:
    description:
      - Parent directory in which the temporary working directory is created.
      - Uses the operating system temporary directory when omitted.
    type: path
  insecure:
    description:
      - Disable HTTPS certificate verification.
      - Has no effect for non-HTTPS sources.
    type: bool
    default: false
  md5sum:
    description:
      - Optional expected 32-character MD5 checksum.
    type: str
requirements:
  - Python 2.7 or newer
  - gzip and tar for gzip tar archives
  - unzip for ZIP archives
notes:
  - Downloads are completed and checksums verified before extraction.
  - The caller is responsible for removing the returned temporary directory.
  - Temporary content is removed automatically if download, verification, or extraction fails.
"""

EXAMPLES = r"""
- name: Download and unpack an archive beneath /u01/tmp
  wtferris.oracle.archive_unpack:
    source_url: https://packages.example.com/product.tar.gz
    temporary_directory_root: /u01/tmp
    md5sum: 0123456789abcdef0123456789abcdef
  register: archive

- name: Show unpacked top-level entries
  ansible.builtin.debug:
    var: archive.contents
"""

RETURN = r"""
md5sum:
  description: Calculated MD5 checksum.
  returned: always
  type: str
failed:
  description: Whether download or extraction failed.
  returned: always
  type: bool
errors:
  description: Errors encountered; empty on success.
  returned: always
  type: list
  elements: str
temporary_directory:
  description: Preserved temporary working directory containing the archive and extraction directory.
  returned: success
  type: str
unpack_directory:
  description: Directory beneath the temporary directory containing unpacked archive contents.
  returned: success
  type: str
contents:
  description: Sorted names found at the root of the unpack directory.
  returned: success
  type: list
  elements: str
changed:
  description: Whether the archive was downloaded and unpacked.
  returned: success
  type: bool
"""


def main():
    module = AnsibleModule(
        argument_spec={
            "source_url": {"type": "str", "required": True},
            "temporary_directory_root": {"type": "path", "default": None},
            "insecure": {"type": "bool", "default": False},
            "md5sum": {"type": "str", "default": None},
        },
        supports_check_mode=False,
    )

    try:
        result = unpack_archive(
            source_url=module.params["source_url"],
            temporary_directory_root=module.params["temporary_directory_root"],
            insecure=module.params["insecure"],
            md5sum=module.params["md5sum"],
        )
    except ArchiveUnpackError as exc:
        module.fail_json(
            msg=str(exc),
            md5sum=exc.md5sum or "",
            errors=[str(exc)],
            temporary_directory=exc.temporary_directory or "",
            unpack_directory="",
            contents=[],
        )

    module.exit_json(**result)


if __name__ == "__main__":
    main()
