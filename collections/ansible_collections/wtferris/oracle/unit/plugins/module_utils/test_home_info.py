# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function

import os
import shutil
import tempfile
import unittest

from plugins.module_utils.home_info import (
    OracleHomeInfoError,
    get_oracle_home_info,
)


class OracleHomeInfoTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="oracle-home-info-")
        self.oracle_home = os.path.join(
            self.root, "linux-x64-19.26.0.0.250121-db"
        )
        comps_directory = os.path.join(
            self.oracle_home, "inventory", "ContentsXML"
        )
        os.makedirs(comps_directory)
        self.comps_path = os.path.join(comps_directory, "comps.xml")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write_comps(self):
        with open(self.comps_path, "w") as stream:
            stream.write("""<INVENTORY xmlns="urn:oracle"><PRD_LIST><TL_LIST>
              <COMP NAME="oracle.server" VER="19.0.0.0.0"
                BUILD_TIME="20190417.011331"
                INSTALL_TIME="2026.Mar.08 14:00:20 UTC"/>
              </TL_LIST></PRD_LIST></INVENTORY>""")

    def test_returns_discovery_compatible_home_record(self):
        self._write_comps()

        result = get_oracle_home_info(
            self.oracle_home,
            software_homename="linux_x64_192600250121_db",
        )

        self.assertEqual(result, {
            "software_build": "20190417.011331",
            "software_build_date": "2019-04-17 01:13:31",
            "software_home": self.oracle_home,
            "software_homename": "linux_x64_192600250121_db",
            "software_installed": "2026.Mar.08 14:00:20 UTC",
            "software_installed_date": "2026-03-08 14:00:20",
            "software_type": "oracle.server",
            "software_version": "19.0.0.0.0",
        })

    def test_defaults_home_name_to_normalized_directory_basename(self):
        self._write_comps()

        result = get_oracle_home_info(self.oracle_home)

        self.assertEqual(
            result["software_homename"],
            "linux_x64_192600250121_db",
        )

    def test_missing_comps_metadata_raises_actionable_error(self):
        with self.assertRaises(OracleHomeInfoError) as context:
            get_oracle_home_info(self.oracle_home)

        self.assertIn("inventory/ContentsXML/comps.xml", str(context.exception))


if __name__ == "__main__":
    unittest.main()
