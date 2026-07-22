#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, wtferris
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.wtferris.oracle.plugins.module_utils.oracle_home_version import (
    OracleHomeVersionError,
    get_oracle_home_versions,
)

__metaclass__ = type

DOCUMENTATION = r"""
---
module: home_version
short_description: Get Oracle Database versions from an Oracle home
version_added: "1.0.0"
description:
  - Runs C(OPatch/opatch lsinventory -xml) for one explicitly supplied Oracle home.
  - Returns the C(oracle.server) component version and the highest Database Release Update version.
  - This module is independent of and is not invoked by M(wtferris.oracle.discovery).
author:
  - wtferris
options:
  oracle_home:
    description:
      - Oracle home whose OPatch inventory should be inspected.
    type: path
    required: true
  timeout:
    description:
      - Maximum number of seconds allowed for OPatch execution.
    type: int
    default: 120
requirements:
  - A functional OPatch installation below the supplied Oracle home
notes:
  - The module does not modify the Oracle home and always reports C(changed=false).
  - Versions are normalized to five numeric components by appending zero components.
  - Compare the returned C(*_version_parts) lists or fixed-width C(*_version_key) strings.
"""

EXAMPLES = r"""
- name: Read versions from one Oracle home
  wtferris.oracle.home_version:
    oracle_home: /u01/product/oracle/db19
  register: oracle_version

- name: Compare the installed RU with a required RU
  ansible.builtin.debug:
    msg: Oracle home meets the required RU
  when: >-
    oracle_version.database_release_update_version_key >=
    '000000000019.000000000026.000000000000.000000000000.000000250121'
"""

RETURN = r"""
oracle_home:
  description: Normalized Oracle home path inspected by OPatch.
  returned: always
  type: str
home_patched:
  description: Whether the OPatch inventory contains any patches.
  returned: success
  type: bool
base_version:
  description: Normalized five-part C(oracle.server) component version.
  returned: success
  type: str
base_version_parts:
  description: Base version as five integers for component-wise comparison.
  returned: success
  type: list
  elements: int
base_version_key:
  description: Fixed-width, lexically sortable base version.
  returned: success
  type: str
database_release_update_version:
  description: Normalized highest Database Release Update version, or an empty string when absent.
  returned: success
  type: str
database_release_update_version_parts:
  description: Release Update as five integers, or an empty list when absent.
  returned: success
  type: list
  elements: int
database_release_update_version_key:
  description: Fixed-width, lexically sortable Release Update version, or an empty string when absent.
  returned: success
  type: str
"""


def main():
    module = AnsibleModule(
        argument_spec={
            "oracle_home": {"type": "path", "required": True},
            "timeout": {"type": "int", "default": 120},
        },
        supports_check_mode=True,
    )

    try:
        result = get_oracle_home_versions(
            module.params["oracle_home"],
            timeout=module.params["timeout"],
        )
    except OracleHomeVersionError as exc:
        module.fail_json(msg=str(exc))

    module.exit_json(changed=False, **result)


if __name__ == "__main__":
    main()
