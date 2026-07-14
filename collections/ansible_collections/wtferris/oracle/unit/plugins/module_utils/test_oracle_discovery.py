# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function

import os
import tempfile
import unittest
from types import SimpleNamespace

from plugins.module_utils.oracle_discovery import (
    OracleDiscovery,
    crsctl_get_hostname,
    crsctl_stat_resources,
    normalize_oracle_datetime,
    parse_comps_xml,
    parse_crsctl_sections,
    parse_environment_assignments,
    parse_inventory_xml,
    parse_listener_endpoints,
    parse_oratab,
)


class ParserTests(unittest.TestCase):
    def _write(self, path, content, binary=False):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mode = "wb" if binary else "w"
        with open(path, mode) as stream:
            stream.write(content)

    def test_inventory_and_component_xml_support_namespaces(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory = os.path.join(directory, "inventory.xml")
            comps = os.path.join(directory, "comps.xml")
            self._write(
                inventory,
                """<INVENTORY xmlns="urn:oracle"><HOME_LIST>
                <HOME NAME="OraGI19Home1" LOC="/u01/grid/home"/>
                <HOME NAME="OraDB19Home1" LOC="/u01/oracle/home"/>
                </HOME_LIST></INVENTORY>""",
            )
            self._write(
                comps,
                """<INVENTORY xmlns="urn:oracle"><PRD_LIST><TL_LIST>
                <COMP NAME="Oracle Database" VER="19.26.0.0.0"
                  BUILD_TIME="2025-01-21_02-03-18PM" INSTALL_TIME="2025-02-03"/>
                </TL_LIST></PRD_LIST></INVENTORY>""",
            )

            homes = parse_inventory_xml(inventory)
            component = parse_comps_xml(comps)

            self.assertEqual(homes[0]["software_homename"], "OraGI19Home1")
            self.assertEqual(homes[1]["software_home"], "/u01/oracle/home")
            self.assertEqual(component["software_type"], "Oracle Database")
            self.assertEqual(component["software_version"], "19.26.0.0.0")
            self.assertEqual(component["software_build"], "2025-01-21_02-03-18PM")
            self.assertEqual(component["software_build_date"], "2025-01-21 14:03:18")
            self.assertEqual(component["software_installed"], "2025-02-03")
            self.assertEqual(component["software_installed_date"], "2025-02-03 00:00:00")

    def test_oracle_datetime_normalization_rejects_unknown_formats(self):
        self.assertEqual(normalize_oracle_datetime("2025-01-21_14-03-18"), "2025-01-21 14:03:18")
        self.assertEqual(normalize_oracle_datetime("not a timestamp"), "")
        self.assertEqual(normalize_oracle_datetime(""), "")

    def test_oratab_ignores_comments_and_normalizes_homes(self):
        with tempfile.TemporaryDirectory() as directory:
            oratab = os.path.join(directory, "oratab")
            self._write(
                oratab,
                "# comment\n+ASM:/u01/grid/:N # ASM\nSMF01d_01:/u01/db/../db:Y\n*:ignored:N\nbad\n",
            )
            records = parse_oratab(oratab)

            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["instance_name"], "+ASM")
            self.assertEqual(records[0]["instance_home"], "/u01/grid")
            self.assertEqual(records[1]["instance_name"], "SMF01d_01")
            self.assertEqual(records[1]["instance_home"], "/u01/db")

    def test_crsctl_sections_environment_and_endpoints(self):
        output = """NAME=ora.LISTENER.lsnr
TYPE=ora.listener.type
ENDPOINTS=TCP:1521,1522 TCPS:5500

NAME=ora.db.db
TYPE=ora.database.type
USR_ORA_ENV=patch=\"foo bar\" home=baz empty= invalid
"""
        sections = parse_crsctl_sections(output)
        variables = parse_environment_assignments(sections[1]["USR_ORA_ENV"])
        standard, ssl = parse_listener_endpoints(sections[0]["ENDPOINTS"])

        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0]["NAME"], "ora.LISTENER.lsnr")
        self.assertEqual(variables, {"patch": "foo bar", "home": "baz", "empty": ""})
        self.assertEqual(standard, [1521, 1522])
        self.assertEqual(ssl, [5500])

    def test_crsctl_utility_uses_argument_lists(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            if command[-2:] == ["get", "hostname"]:
                return SimpleNamespace(returncode=0, stdout="node01\n", stderr="")
            return SimpleNamespace(
                returncode=0,
                stdout="NAME=ora.asm\nTYPE=ora.asm.type\n",
                stderr="",
            )

        self.assertEqual(crsctl_get_hostname("/grid", runner=runner), "node01")
        resources = crsctl_stat_resources("/grid", runner=runner)

        self.assertEqual(resources[0]["TYPE"], "ora.asm.type")
        self.assertEqual(calls[0][0], ["/grid/bin/crsctl", "get", "hostname"])
        self.assertEqual(calls[1][0], ["/grid/bin/crsctl", "stat", "res", "-f"])
        self.assertNotIn("shell", calls[0][1])


class DiscoveryTests(unittest.TestCase):
    def _write(self, path, content, binary=False):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mode = "wb" if binary else "w"
        with open(path, mode) as stream:
            stream.write(content)

    def _process(self, proc_root, pid, arguments, executable):
        process_dir = os.path.join(proc_root, str(pid))
        os.makedirs(process_dir)
        self._write(
            os.path.join(process_dir, "cmdline"),
            b"\0".join(item.encode("utf-8") for item in arguments) + b"\0",
            binary=True,
        )
        os.symlink(executable, os.path.join(process_dir, "exe"))

    def test_complete_discovery_merges_all_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory_root = os.path.join(directory, "oraInventory")
            grid_root = os.path.join(directory, "product", "grid")
            oracle_root = os.path.join(directory, "product", "oracle")
            grid_home = os.path.join(grid_root, "grid19")
            db_home = os.path.join(oracle_root, "db19")
            proc_root = os.path.join(directory, "proc")
            os.makedirs(proc_root)

            orainst = os.path.join(directory, "etc", "oraInst.loc")
            oratab = os.path.join(directory, "etc", "oratab")
            ocr = os.path.join(directory, "etc", "oracle", "ocr.loc")
            self._write(orainst, "inventory_loc={0}\ninst_group=dba\n".format(inventory_root))
            self._write(
                os.path.join(inventory_root, "ContentsXML", "inventory.xml"),
                """<INVENTORY><HOME_LIST>
                <HOME NAME="OraGI19Home1" LOC="{0}"/>
                <HOME NAME="OraDB19Home1" LOC="{1}"/>
                </HOME_LIST></INVENTORY>""".format(grid_home, db_home),
            )
            comps_template = """<INVENTORY><PRD_LIST><TL_LIST>
              <COMP NAME="{0}" VER="19.26.0.0.0" BUILD_TIME="build" INSTALL_TIME="install"/>
              </TL_LIST></PRD_LIST></INVENTORY>"""
            self._write(
                os.path.join(grid_home, "inventory", "ContentsXML", "comps.xml"),
                comps_template.format("Oracle Grid Infrastructure"),
            )
            self._write(
                os.path.join(db_home, "inventory", "ContentsXML", "comps.xml"),
                comps_template.format("Oracle Database"),
            )
            self._write(
                oratab,
                "+ASM:{0}:N\nSMF01d_01:{1}:N\nORATAB_ONLY:{1}:N\n".format(grid_home, db_home),
            )
            self._write(ocr, "local_only=false\n")

            self._process(proc_root, 10, [os.path.join(grid_home, "bin", "ocssd.bin")], os.path.join(grid_home, "bin", "ocssd.bin"))
            self._process(proc_root, 11, ["asm_pmon_+ASM1"], os.path.join(grid_home, "bin", "oracle"))
            self._process(proc_root, 12, ["ora_pmon_SMF01d_01"], os.path.join(db_home, "bin", "oracle"))
            self._process(proc_root, 13, [os.path.join(grid_home, "bin", "tnslsnr"), "LISTENER", "-inherit"], os.path.join(grid_home, "bin", "tnslsnr"))
            self._process(proc_root, 14, [os.path.join(db_home, "bin", "tnslsnr"), "APP_LISTENER"], os.path.join(db_home, "bin", "tnslsnr"))

            crs_output = """NAME=ora.asm
TYPE=ora.asm.type
USR_ORA_INST_NAME=+ASM1
PWFILE=+DATA/orapwasm
SPFILE=+DATA/spfileasm.ora

NAME=ora.smf.db
TYPE=ora.database.type
HOSTING_MEMBERS=node01
USR_ORA_INST_NAME=SMF01d_01
ORACLE_HOME={db_home}
PWFILE=+DATA/orapwsmf
SPFILE=+DATA/spfilesmf.ora
MANAGEMENT_POLICY=AUTOMATIC
GEN_AUDIT_FILE_DEST=/u01/audit
USR_ORA_ENV=patch=\"foo bar\" home=baz

NAME=ora.remote.db
TYPE=ora.database.type
HOSTING_MEMBERS=node02
USR_ORA_INST_NAME=REMOTE
ORACLE_HOME=/remote/home

NAME=ora.LISTENER.lsnr
TYPE=ora.listener.type
ENDPOINTS=TCP:1521,1522 TCPS:5500

NAME=ora.APP_LISTENER.lsnr
TYPE=ora.listener.type
ENDPOINTS=TCP:1621
""".format(db_home=db_home)

            def runner(command, **kwargs):
                if command[-2:] == ["get", "hostname"]:
                    return SimpleNamespace(returncode=0, stdout="node01\n", stderr="")
                return SimpleNamespace(returncode=0, stdout=crs_output, stderr="")

            result = OracleDiscovery(
                grid_roots=[grid_root],
                oracle_roots=[oracle_root],
                proc_root=proc_root,
                orainst_paths=[orainst],
                oratab_paths=[oratab],
                ocr_path=ocr,
                crsctl_runner=runner,
            ).discover()

            self.assertTrue(result["grid_installed"])
            self.assertTrue(result["grid_running"])
            self.assertEqual(result["grid_home"], grid_home)
            self.assertEqual(result["grid_type"], "rac")

            self.assertTrue(result["asm_installed"])
            self.assertTrue(result["asm_running"])
            self.assertTrue(result["asm_registered"])
            self.assertEqual(result["asm_instance"], "+ASM1")
            self.assertEqual(result["asm_home"], grid_home)
            self.assertEqual(result["asm_pwfile"], "+DATA/orapwasm")

            self.assertEqual(result["software_homes"]["grid19"]["software_homename"], "OraGI19Home1")
            self.assertEqual(result["software_homes"]["db19"]["software_type"], "Oracle Database")

            instance = result["instances"]["smf01d_01"]
            self.assertTrue(instance["instance_running"])
            self.assertTrue(instance["instance_registered"])
            self.assertTrue(instance["instance_in_oratab"])
            self.assertEqual(instance["instance_name"], "SMF01d_01")
            self.assertEqual(instance["instance_variables"], {"patch": "foo bar", "home": "baz"})
            self.assertIn("oratab_only", result["instances"])
            self.assertNotIn("remote", result["instances"])

            self.assertTrue(result["listener_running"])
            self.assertTrue(result["listener_registered"])
            self.assertEqual(result["listener_standard_ports"], [1521, 1522])
            self.assertEqual(result["listener_ssl_ports"], [5500])
            other = result["listener_others"]["APP_LISTENER"]
            self.assertTrue(other["listener_running"])
            self.assertTrue(other["listener_registered"])
            self.assertEqual(other["listener_standard_ports"], [1621])


if __name__ == "__main__":
    unittest.main()
