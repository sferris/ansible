#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, wtferris
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: discovery
short_description: Discover Oracle software and running services
version_added: "1.0.0"
description:
  - Discovers Oracle software homes from the central inventory and conventional locations.
  - Catalogs Grid Infrastructure, ASM, database PMON, and listener processes through C(/proc).
  - Augments runtime data with C(oratab), C(ocr.loc), and C(crsctl) information.
  - Uses Python filesystem APIs rather than commands such as C(ps) and C(readlink).
author:
  - wtferris
options:
  grid_roots:
    description:
      - Root directories whose immediate children are searched for Grid Infrastructure homes.
    type: list
    elements: path
    default:
      - /u01/product/grid
  oracle_roots:
    description:
      - Root directories whose immediate children are searched for other Oracle homes.
    type: list
    elements: path
    default:
      - /u01/product/oracle
  crsctl_timeout:
    description:
      - Maximum number of seconds for each C(crsctl) invocation.
    type: int
    default: 10
requirements:
  - Python 3
notes:
  - The remote user needs sufficient access to inspect Oracle processes in C(/proc).
  - Missing Oracle files and unavailable C(crsctl) commands are treated as absent discovery sources.
"""

EXAMPLES = r"""
- name: Discover Oracle installations
  wtferris.oracle.discovery:
  register: oracle_discovery

- name: Search additional software roots
  wtferris.oracle.discovery:
    grid_roots:
      - /u01/product/grid
      - /opt/oracle/grid
    oracle_roots:
      - /u01/product/oracle
      - /opt/oracle/database
  register: oracle_discovery
"""

RETURN = r"""
grid_installed:
  description: Whether a Grid home, process, or CRS resource was discovered.
  returned: always
  type: bool
grid_running:
  description: Whether an C(ocssd.bin) process is running.
  returned: always
  type: bool
grid_home:
  description: Discovered Grid Infrastructure home.
  returned: always
  type: str
grid_type:
  description: C(restart) or C(rac), as reported by C(ocr.loc).
  returned: always
  type: str
asm_installed:
  description: Whether ASM was discovered.
  returned: always
  type: bool
asm_running:
  description: Whether an ASM PMON process is running.
  returned: always
  type: bool
asm_instance:
  description: ASM instance name.
  returned: always
  type: str
asm_registered:
  description: Whether ASM is registered in CRS.
  returned: always
  type: bool
asm_home:
  description: ASM software home.
  returned: always
  type: str
asm_pwfile:
  description: ASM password file reported by CRS.
  returned: always
  type: str
asm_spfile:
  description: ASM server parameter file reported by CRS.
  returned: always
  type: str
software_homes:
  description: Software homes keyed by the lowercased home directory basename.
  returned: always
  type: dict
instances:
  description: Database instances keyed by lowercased instance name.
  returned: always
  type: dict
listener_name:
  description: Default listener name.
  returned: always
  type: str
listener_running:
  description: Whether the default listener process is running.
  returned: always
  type: bool
listener_registered:
  description: Whether the default listener is registered in CRS.
  returned: always
  type: bool
listener_standard_ports:
  description: TCP ports registered for the default listener.
  returned: always
  type: list
  elements: raw
listener_ssl_ports:
  description: TCPS ports registered for the default listener.
  returned: always
  type: list
  elements: raw
listener_others:
  description: Non-default listeners keyed by listener name.
  returned: always
  type: dict
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.wtferris.oracle.plugins.module_utils.oracle_discovery import (
    DEFAULT_GRID_ROOTS,
    DEFAULT_ORACLE_ROOTS,
    OracleDiscovery,
)


def main():
    module = AnsibleModule(
        argument_spec={
            "grid_roots": {
                "type": "list",
                "elements": "path",
                "default": DEFAULT_GRID_ROOTS,
            },
            "oracle_roots": {
                "type": "list",
                "elements": "path",
                "default": DEFAULT_ORACLE_ROOTS,
            },
            "crsctl_timeout": {"type": "int", "default": 10},
        },
        supports_check_mode=True,
    )

    result = OracleDiscovery(
        grid_roots=module.params["grid_roots"],
        oracle_roots=module.params["oracle_roots"],
        crsctl_timeout=module.params["crsctl_timeout"],
    ).discover()
    module.exit_json(changed=False, **result)


if __name__ == "__main__":
    main()

