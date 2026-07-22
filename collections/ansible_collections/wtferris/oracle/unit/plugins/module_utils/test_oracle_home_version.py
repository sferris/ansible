# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function

import os
import tempfile
import unittest

from plugins.module_utils.oracle_command import CommandResult
from plugins.module_utils.oracle_home_version import (
    OracleHomeVersionError,
    get_oracle_home_versions,
    normalize_oracle_version,
    parse_opatch_inventory_xml,
)


INVENTORY_XML = """<?xml version="1.0"?>
<InventoryInstance>
  <components>
    <component id="oracle.jdk"><version>1.8.0.0.0</version></component>
    <component xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xsi:type="OUIComponent" id="oracle.server" name="Oracle Database 19c">
      <description>Oracle Database server</description>
      <version>19.0.0.0.0</version>
    </component>
  </components>
  <patches>
    <patch><patchDescription>JDK BUNDLE PATCH 19.0.0.0.250121</patchDescription></patch>
    <patch><patchDescription>Database Release Update : 19.25.0.0.241015 (36912597)</patchDescription></patch>
    <patch><patchDescription>Database Release Update : 19.26.0.0.250121 (37260974)</patchDescription></patch>
  </patches>
</InventoryInstance>
"""

DUPLICATE_12C_XML = """<InventoryInstance>
  <components>
    <component id="oracle.server" name="Oracle Database 12c">
      <description>Oracle Database server</description>
      <version>12.1.0.2</version>
      <description>Oracle Database server</description>
      <name>Oracle Database 12c</name>
      <version>12.1.0.2</version>
    </component>
  </components>
  <patches/>
</InventoryInstance>
"""


class OracleHomeVersionTests(unittest.TestCase):
    def _xml_file(self, content):
        descriptor, path = tempfile.mkstemp(suffix=".xml")
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return path

    def test_normalize_oracle_version_pads_to_five_parts(self):
        normalized, parts, key = normalize_oracle_version("19.26.0.0")

        self.assertEqual(normalized, "19.26.0.0.0")
        self.assertEqual(parts, [19, 26, 0, 0, 0])
        self.assertEqual(
            key,
            "000000000019.000000000026.000000000000.000000000000.000000000000",
        )

    def test_parse_inventory_extracts_server_and_highest_database_ru(self):
        result = parse_opatch_inventory_xml(self._xml_file(INVENTORY_XML))

        self.assertTrue(result["home_patched"])
        self.assertEqual(result["base_version"], "19.0.0.0.0")
        self.assertEqual(result["base_version_parts"], [19, 0, 0, 0, 0])
        self.assertEqual(result["database_release_update_version"], "19.26.0.0.250121")
        self.assertEqual(
            result["database_release_update_version_parts"],
            [19, 26, 0, 0, 250121],
        )

    def test_parse_inventory_accepts_duplicate_12c_elements_and_no_ru(self):
        result = parse_opatch_inventory_xml(self._xml_file(DUPLICATE_12C_XML))

        self.assertFalse(result["home_patched"])
        self.assertEqual(result["base_version"], "12.1.0.2.0")
        self.assertEqual(result["database_release_update_version"], "")
        self.assertEqual(result["database_release_update_version_parts"], [])

    def test_get_versions_runs_requested_home_opatch_and_removes_xml(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            with open(command[-1], "w") as stream:
                stream.write(INVENTORY_XML)
            return CommandResult(0, "", "")

        result = get_oracle_home_versions("/u01/oracle/db19", runner=runner)

        self.assertEqual(
            calls[0][0],
            [
                "/u01/oracle/db19/OPatch/opatch",
                "lsinventory",
                "-xml",
                calls[0][0][-1],
            ],
        )
        self.assertEqual(calls[0][1]["env"]["ORACLE_HOME"], "/u01/oracle/db19")
        self.assertEqual(calls[0][1]["env"]["LC_ALL"], "C")
        self.assertFalse(os.path.exists(calls[0][0][-1]))
        self.assertEqual(result["oracle_home"], "/u01/oracle/db19")

    def test_get_versions_reports_opatch_failure(self):
        def runner(command, **kwargs):
            return CommandResult(1, "", "inventory unavailable")

        with self.assertRaises(OracleHomeVersionError) as context:
            get_oracle_home_versions("/u01/oracle/db19", runner=runner)

        self.assertIn("inventory unavailable", str(context.exception))


if __name__ == "__main__":
    unittest.main()
