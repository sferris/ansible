#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, wtferris
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.wtferris.oracle.plugins.module_utils.fetch_archive import (
    FetchArchiveError,
    fetch_archive,
)

__metaclass__ = type

DOCUMENTATION = r"""
---
module: fetch_archive
short_description: Download and unpack an archive into temporary storage
version_added: "1.0.0"
description:
  - Downloads a local or remote gzip tar or ZIP archive into a temporary working directory.
  - Calculates and optionally verifies its MD5 checksum before extraction.
  - Uses the operating system C(gzip), C(tar), and C(unzip) executables.
  - Preserves the temporary directory so another task or module can process the unpacked contents.
  - The implementation is also available from the collection's C(fetch_archive) module utility.
author:
  - wtferris
options:
  source_url:
    description:
      - Local path or C(file), C(http), or C(https) URL of a C(.tgz), C(.tar.gz), or C(.zip) archive.
    type: str
    required: true
  installation_path:
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
      - When supplied, it is used as the archive cache identity.
    type: str
  force:
    description:
      - Fetch and replace a completed cached archive instead of returning it unchanged.
    type: bool
    default: false
  lock_timeout:
    description:
      - Maximum number of seconds to wait for another process fetching the same archive.
    type: int
    default: 300
requirements:
  - Python 2.7 or newer
  - gzip and tar for gzip tar archives
  - unzip for ZIP archives
notes:
  - Downloads are completed and checksums verified before extraction.
  - Completed archives are cached by expected MD5, or by normalized source URL when MD5 is omitted.
  - Concurrent callers for the same archive are serialized with an atomic directory lock.
  - The caller may remove the returned cache directory when it is no longer needed.
  - Staging content is removed automatically if download, verification, or extraction fails.
"""

EXAMPLES = r"""
- name: Download and unpack an archive beneath /u01/tmp
  wtferris.oracle.fetch_archive:
    source_url: https://packages.example.com/product.tar.gz
    installation_path: /u01/tmp
    md5sum: 0123456789abcdef0123456789abcdef
    lock_timeout: 300
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
  description: Preserved cache directory containing the extraction directory and completion marker. The downloaded archive is removed after extraction.
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
  description: Whether the archive was downloaded and unpacked rather than returned from cache.
  returned: success
  type: bool
"""


def main():
    module = AnsibleModule(
        argument_spec={
            "source_url": {"type": "str", "required": True},
            "installation_path": {"type": "path", "default": None},
            "insecure": {"type": "bool", "default": False},
            "md5sum": {"type": "str", "default": None},
            "force": {"type": "bool", "default": False},
            "lock_timeout": {"type": "int", "default": 300},
        },
        supports_check_mode=False,
    )

    try:
        result = fetch_archive(
            source_url=module.params["source_url"],
            installation_path=module.params["installation_path"],
            insecure=module.params["insecure"],
            md5sum=module.params["md5sum"],
            force=module.params["force"],
            lock_timeout=module.params["lock_timeout"],
        )
    except FetchArchiveError as exc:
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
