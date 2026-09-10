#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, wtferris
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.wtferris.oracle.plugins.module_utils.home_info import (
    OracleHomeInfoError,
    get_oracle_home_info,
)

__metaclass__ = type

DOCUMENTATION = r"""
---
module: home_info
short_description: Read component information for one Oracle home
version_added: "1.0.0"
description:
  - Reads C(inventory/ContentsXML/comps.xml) beneath an explicitly supplied Oracle home.
  - Returns the same software-home metadata fields used by M(wtferris.oracle.discovery).
  - Does not run full Oracle discovery or OPatch.
author:
  - wtferris
options:
  oracle_home:
    description:
      - Oracle software home containing C(inventory/ContentsXML/comps.xml).
    type: path
    required: true
  software_homename:
    description:
      - Optional central-inventory name for the Oracle home.
      - Defaults to the Oracle home directory basename with dashes replaced by underscores and periods removed.
    type: str
requirements:
  - Python 2.7 or newer
notes:
  - The module only reads local filesystem metadata and always reports C(changed=false).
"""

EXAMPLES = r"""
- name: Read one Oracle home's component information
  wtferris.oracle.home_info:
    oracle_home: /u01/product/oracle/linux-x64-19.26.0.0.250121-db
    software_homename: linux_x64_192600250121_db
  register: oracle_home

- ansible.builtin.debug:
    var: oracle_home
"""

RETURN = r"""
software_home:
  description: Normalized Oracle home path.
  returned: success
  type: str
software_homename:
  description: Supplied home name, or the normalized Oracle home directory basename.
  returned: success
  type: str
software_type:
  description: Component C(NAME) from C(comps.xml).
  returned: success
  type: str
software_version:
  description: Component C(VER) from C(comps.xml).
  returned: success
  type: str
software_build:
  description: Original component C(BUILD_TIME) value.
  returned: success
  type: str
software_build_date:
  description: Build timestamp normalized as C(YYYY-MM-DD HH:MM:SS), or an empty string.
  returned: success
  type: str
software_installed:
  description: Original component C(INSTALL_TIME) value.
  returned: success
  type: str
software_installed_date:
  description: Installation timestamp normalized as C(YYYY-MM-DD HH:MM:SS), or an empty string.
  returned: success
  type: str
"""


def main():
    module = AnsibleModule(
        argument_spec={
            "oracle_home": {"type": "path", "required": True},
            "software_homename": {"type": "str", "default": None},
        },
        supports_check_mode=True,
    )

    try:
        result = get_oracle_home_info(
            module.params["oracle_home"],
            software_homename=module.params["software_homename"],
        )
    except OracleHomeInfoError as exc:
        module.fail_json(msg=str(exc))

    module.exit_json(changed=False, **result)


if __name__ == "__main__":
    main()
