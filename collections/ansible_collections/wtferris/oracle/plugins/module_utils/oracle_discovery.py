# -*- coding: utf-8 -*-

"""Standard-library utilities used by the Oracle discovery Ansible module."""

from __future__ import absolute_import, division, print_function

import glob
import os
import re
import shlex
import subprocess
import threading
import xml.etree.ElementTree as ET
from datetime import datetime

# For Python 2.7 compatibility, we need to handle the subprocess.run differently
# Since subprocess.run was added in Python 3.5, we need this compatibility layer

# Define shared custom exceptions and classes first to avoid scope/binding warnings
class _TimeoutExpired(Exception):
    def __init__(self, cmd, timeout):
        self.cmd = cmd
        self.timeout = timeout
        super(_TimeoutExpired, self).__init__("%s timed out after %s seconds" % (cmd, timeout))

class _CompletedProcess(object):
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

def _communicate_with_timeout(process, timeout, cmd):
    if timeout is None:
        return process.communicate()

    result = [None, None]
    error = [None]

    def target():
        try:
            result[0], result[1] = process.communicate()
        except Exception as exc:
            error[0] = exc # type: ignore[assignment]

    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        try:
            process.kill()
        except Exception:
            pass
        process.wait()
        raise _TimeoutExpired(cmd, timeout)
    if error[0] is not None:
        raise error[0]
    return result[0], result[1]

def _py2_subprocess_run(
    args,
    stdout=None,
    stderr=None,
    universal_newlines=False,
    timeout=None,
    check=False,
    env=None,
    **kwargs
):
    if universal_newlines:
        kwargs['universal_newlines'] = True

    process = subprocess.Popen(
        args,
        stdout=stdout,
        stderr=stderr,
        env=env,
        **kwargs
    )

    stdout_data, stderr_data = _communicate_with_timeout(process, timeout, args)

    if check and process.returncode:
        raise subprocess.CalledProcessError(process.returncode, args, stdout_data)

    return _CompletedProcess(process.returncode, stdout_data or "", stderr_data or "")

# Clear branch for the type checker: Python 3 vs Python 2 fallback
if hasattr(subprocess, "run"):
    _subprocess_run = subprocess.run
    _SUBPROCESS_ERRORS = (OSError, subprocess.SubprocessError)
else:
    _subprocess_run = _py2_subprocess_run
    _SUBPROCESS_ERRORS = (OSError, subprocess.CalledProcessError, ValueError, _TimeoutExpired)

DEFAULT_GRID_ROOTS = ["/u01/product/grid"]
DEFAULT_ORACLE_ROOTS = ["/u01/product/oracle"]
DEFAULT_ORAINST_PATHS = ["/etc/oraInst.loc", "/var/opt/oracle/oraInst.loc"]
DEFAULT_ORATAB_PATHS = ["/etc/oratab", "/var/opt/oracle/oratab"]
DEFAULT_OCR_PATH = "/etc/oracle/ocr.loc"


def normalize_path(path):
    """Normalize a path without requiring it to exist."""
    if not path:
        return ""
    return os.path.normpath(os.path.abspath(os.path.expanduser(path.strip())))


def path_is_within(path, root):
    """Return whether path is root or one of its descendants."""
    path = normalize_path(path)
    root = normalize_path(root)
    if not path or not root:
        return False
    try:
        relative = os.path.relpath(path, root)
    except ValueError:
        return False
    return relative == os.curdir or (
        not os.path.isabs(relative)
        and relative != os.pardir
        and not relative.startswith(os.pardir + os.sep)
    )


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def normalize_oracle_datetime(value):
    """Convert an Oracle inventory timestamp to an Ansible-friendly datetime string."""
    value = (value or "").strip()
    if not value:
        return ""

    # 2026.Mar.08 13:54:00 UTC
    formats = (
        "%Y.%b.%d %H:%M:%S %Z",
        "%Y%m%d.%H%M%S",
        "%Y-%m-%d_%I-%M-%S%p",
        "%Y-%m-%d_%H-%M-%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    )
    for timestamp_format in formats:
        try:
            parsed = datetime.strptime(value, timestamp_format)
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return ""


def _new_instance(name=""):
    return {
        "instance_audit_dest": "",
        "instance_dbname": "",
        "instance_dbname_unique": "",
        "instance_home": "",
        "instance_in_oratab": False,
        "instance_management_policy": "",
        "instance_name": name,
        "instance_pwfile": "",
        "instance_registered": False,
        "instance_running": False,
        "instance_server": "",
        "instance_spfile": "",
        "instance_variables": {},
    }


def _new_listener(name=""):
    return {
        "listener_home": "",
        "listener_name": name,
        "listener_registered": False,
        "listener_running": False,
        "listener_ssl_ports": [],
        "listener_standard_ports": [],
        "listener_type": "",
    }


def _new_details():
    listener = _new_listener("LISTENER")
    return {
        "grid_home": "",
        "grid_installed": False,
        "grid_running": False,
        "grid_server": "",
        "grid_type": "",
        "asm_home": "",
        "asm_installed": False,
        "asm_instance": "",
        "asm_pwfile": "",
        "asm_registered": False,
        "asm_running": False,
        "asm_spfile": "",
        "software_homes": {},
        "instances": {},
        "listener_home": listener["listener_home"],
        "listener_name": listener["listener_name"],
        "listener_others": {},
        "listener_registered": listener["listener_registered"],
        "listener_running": listener["listener_running"],
        "listener_ssl_ports": listener["listener_ssl_ports"],
        "listener_standard_ports": listener["listener_standard_ports"],
        "listener_type": listener["listener_type"],
    }


def _new_result():
    return {"details": _new_details()}


def parse_key_value_file(path):
    """Parse a simple KEY=VALUE file, ignoring comments and malformed lines."""
    values = {}
    try:
        with open(path, "r") as stream:
            for raw_line in stream:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    except (IOError, OSError):
        return {}
    return values


def parse_inventory_xml(path):
    """Return Oracle homes declared in a central inventory.xml file."""
    homes = []
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, IOError, OSError):
        return homes

    for home_list in root.iter():
        if _local_name(home_list.tag) != "HOME_LIST":
            continue
        for home in list(home_list):
            if _local_name(home.tag) != "HOME":
                continue
            location = home.attrib.get("LOC", "").strip()
            if home.attrib.get("REMOVED", "").strip() == "T":
                continue
            if not location:
                continue
            homes.append({
                "software_home": normalize_path(location),
                "software_homename": home.attrib.get("NAME", "").strip(),
            })
    return homes


def parse_comps_xml(path):
    """Extract the requested component metadata from an Oracle comps.xml file."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, IOError, OSError):
        return {}

    candidates = []
    for product_list in root.iter():
        if _local_name(product_list.tag) != "PRD_LIST":
            continue
        for technology_list in product_list.iter():
            if _local_name(technology_list.tag) != "TL_LIST":
                continue
            candidates.extend(
                element for element in technology_list.iter()
                if _local_name(element.tag) == "COMP"
            )

    if not candidates:
        candidates = [element for element in root.iter() if _local_name(element.tag) == "COMP"]
    if not candidates:
        return {}

    component = candidates[0]
    software_build = component.attrib.get("BUILD_TIME", "").strip()
    software_installed = component.attrib.get("INSTALL_TIME", "").strip()
    return {
        "software_type": component.attrib.get("NAME", "").strip(),
        "software_version": component.attrib.get("VER", "").strip(),
        "software_build": software_build,
        "software_build_date": normalize_oracle_datetime(software_build),
        "software_installed": software_installed,
        "software_installed_date": normalize_oracle_datetime(software_installed),
    }


def parse_oratab(path):
    """Parse an oratab file into instance records."""
    records = []
    try:
        with open(path, "r") as stream:
            for raw_line in stream:
                line = raw_line.split("#", 1)[0].strip()
                if not line:
                    continue
                fields = [field.strip() for field in line.split(":")]
                if len(fields) < 2 or not fields[0] or not fields[1] or fields[0] == "*":
                    continue
                records.append({
                    "instance_name": fields[0],
                    "instance_home": normalize_path(fields[1]),
                    "start_on_reboot": fields[2] if len(fields) > 2 else "",
                })
    except (IOError, OSError):
        return []
    return records


def parse_crsctl_sections(output):
    """Parse ``crsctl stat res -f`` output into a list of dictionaries."""
    sections = []
    current = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                sections.append(current)
                current = {}
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key == "NAME" and current:
            sections.append(current)
            current = {}
        current[key] = value.strip()
    if current:
        sections.append(current)
    return sections


def parse_environment_assignments(value):
    """Parse shell-style NAME=value assignments without evaluating them."""
    if not value:
        return {}
    try:
        words = shlex.split(value, posix=True)
    except ValueError:
        return {}

    variables = {}
    for word in words:
        if "=" not in word:
            continue
        key, item_value = word.split("=", 1)
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            variables[key] = item_value
    return variables


def parse_listener_endpoints(value):
    """Return TCP and TCPS port lists from a CRS ENDPOINTS value."""
    standard = []
    ssl = []
    for match in re.finditer(r"(?:^|\s)(TCP|TCPS):([^\s]+)", value or "", re.IGNORECASE):
        destination = standard if match.group(1).upper() == "TCP" else ssl
        for raw_port in match.group(2).split(","):
            port = raw_port.strip()
            if not port:
                continue
            parsed_port = int(port) if port.isdigit() else port
            if parsed_port not in destination:
                destination.append(parsed_port)
    return standard, ssl


def _run_crsctl(grid_home, arguments, timeout=10, runner=None):
    """Run crsctl safely with an argument list and a controlled locale."""
    runner = runner or _subprocess_run
    executable = os.path.join(normalize_path(grid_home), "bin", "crsctl")
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    try:
        completed = runner(
            [executable] + list(arguments),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=timeout,
            check=False,
            env=environment,
        )
    except _SUBPROCESS_ERRORS:
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def crsctl_get_hostname(grid_home, timeout=10, runner=None):
    """Return the hostname reported by ``crsctl get hostname``."""
    return _run_crsctl(grid_home, ["get", "hostname"], timeout=timeout, runner=runner).strip()


def crsctl_stat_resources(grid_home, timeout=10, runner=None):
    """Return parsed sections from ``crsctl stat res -f``."""
    output = _run_crsctl(grid_home, ["stat", "res", "-f"], timeout=timeout, runner=runner)
    return parse_crsctl_sections(output) if output else []


class OracleDiscovery(object):
    """Collect Oracle installation and runtime information from a server."""

    def __init__(
        self,
        grid_roots=None,
        oracle_roots=None,
        proc_root="/proc",
        orainst_paths=None,
        oratab_paths=None,
        ocr_path=DEFAULT_OCR_PATH,
        crsctl_timeout=10,
        crsctl_runner=None,
    ):
        self.grid_roots = [normalize_path(path) for path in (grid_roots or DEFAULT_GRID_ROOTS)]
        self.oracle_roots = [normalize_path(path) for path in (oracle_roots or DEFAULT_ORACLE_ROOTS)]
        self.proc_root = proc_root
        self.orainst_paths = orainst_paths or list(DEFAULT_ORAINST_PATHS)
        self.oratab_paths = oratab_paths or list(DEFAULT_ORATAB_PATHS)
        self.ocr_path = ocr_path
        self.crsctl_timeout = crsctl_timeout
        self.crsctl_runner = crsctl_runner
        self.result = _new_result()
        self.details = self.result["details"]

    def discover(self):
        self.discover_software_homes()
        self.discover_processes()
        self.discover_oratab()
        self.discover_grid_type()
        self.discover_crsctl()
        self.details["software_homes"] = dict(sorted(self.details["software_homes"].items()))
        self.details["instances"] = dict(sorted(self.details["instances"].items()))
        self.details["listener_others"] = dict(sorted(self.details["listener_others"].items()))
        return self.result

    def _software_home_key(self, path):
        return os.path.basename(normalize_path(path)).lower()

    def _is_grid_home(self, home):
        return any(path_is_within(home, root) for root in self.grid_roots)

    def _add_software_home(self, home, homename=""):
        home = normalize_path(home)
        if not home:
            return
        key = self._software_home_key(home)
        if not key:
            return
        record = self.details["software_homes"].setdefault(key, {
            "software_home": home,
            "software_homename": homename or os.path.basename(home),
            "software_type": "",
            "software_version": "",
            "software_build": "",
            "software_build_date": "",
            "software_installed": "",
            "software_installed_date": "",
        })
        if homename:
            record["software_homename"] = homename
        if self._is_grid_home(home):
            self.details["grid_installed"] = True
            if not self.details["grid_home"]:
                self.details["grid_home"] = home

    def discover_software_homes(self):
        for pointer_path in self.orainst_paths:
            inventory_location = parse_key_value_file(pointer_path).get("inventory_loc", "")
            if not inventory_location:
                continue
            inventory_xml = os.path.join(normalize_path(inventory_location), "ContentsXML", "inventory.xml")
            homes = parse_inventory_xml(inventory_xml)
            for home in homes:
                self._add_software_home(home["software_home"], home["software_homename"])
            if homes:
                break

        for root in self.grid_roots + self.oracle_roots:
            pattern = os.path.join(root, "*", "inventory", "ContentsXML", "comps.xml")
            for comps_path in sorted(glob.glob(pattern)):
                home = os.path.dirname(os.path.dirname(os.path.dirname(comps_path)))
                self._add_software_home(home)

        for record in self.details["software_homes"].values():
            comps_path = os.path.join(record["software_home"], "inventory", "ContentsXML", "comps.xml")
            record.update(parse_comps_xml(comps_path))

    def _process_arguments(self, pid):
        cmdline_path = os.path.join(self.proc_root, str(pid), "cmdline")
        try:
            with open(cmdline_path, "rb") as stream:
                data = stream.read()
        except (IOError, OSError):
            return []
        return [item.decode("utf-8", "surrogateescape") for item in data.split(b"\0") if item]

    def _process_home(self, pid):
        executable_path = os.path.join(self.proc_root, str(pid), "exe")
        try:
            target = os.readlink(executable_path)
        except (IOError, OSError):
            return ""
        if target.endswith(" (deleted)"):
            target = target[:-10]
        target = normalize_path(target)
        executable_directory = os.path.dirname(target)
        if os.path.basename(executable_directory) == "bin":
            return os.path.dirname(executable_directory)
        return executable_directory

    def _set_default_listener(self, record):
        for key, value in record.items():
            self.details[key] = value

    def _get_listener(self, name):
        if name.lower() == "listener":
            record = _new_listener(self.details.get("listener_name") or name)
            for key in record:
                if key in self.details:
                    record[key] = self.details[key]
            return record, True
        for existing_name, record in self.details["listener_others"].items():
            if existing_name.lower() == name.lower():
                return record, False
        record = _new_listener(name)
        self.details["listener_others"][name] = record
        return record, False

    def discover_processes(self):
        try:
            pids = sorted((name for name in os.listdir(self.proc_root) if name.isdigit()), key=int)
        except (IOError, OSError):
            return

        for pid in pids:
            arguments = self._process_arguments(pid)
            if not arguments:
                continue
            process_name = os.path.basename(arguments[0])
            home = self._process_home(pid)

            if process_name == "ohasd.bin":
                self.details["grid_installed"] = True
                self.details["grid_running"] = True
                if home:
                    self.details["grid_home"] = home
                    self._add_software_home(home)
                continue

            asm_match = re.match(r"^asm_pmon_(\+ASM\d*)$", process_name, re.IGNORECASE)
            if asm_match:
                self.details["asm_installed"] = True
                self.details["asm_running"] = True
                self.details["asm_instance"] = asm_match.group(1)
                if home:
                    self.details["asm_home"] = home
                continue

            instance_match = re.match(r"^ora_pmon_(.+)$", process_name)
            if instance_match:
                instance_name = instance_match.group(1)
                key = instance_name.lower()
                instance = self.details["instances"].setdefault(key, _new_instance(instance_name))
                instance["instance_running"] = True
                if home:
                    instance["instance_home"] = home
                continue

            if process_name == "tnslsnr":
                listener_name = "LISTENER"
                if len(arguments) > 1 and arguments[1] and not arguments[1].startswith("-"):
                    listener_name = arguments[1]
                listener, is_default = self._get_listener(listener_name)
                listener["listener_running"] = True
                listener["listener_name"] = listener_name
                if home:
                    listener["listener_home"] = home
                if is_default:
                    self._set_default_listener(listener)

    def discover_oratab(self):
        records = []
        for path in self.oratab_paths:
            if os.path.isfile(path):
                records = parse_oratab(path)
                break
        for record in records:
            instance_name = record["instance_name"]
            if re.match(r"^\+ASM\d*$", instance_name, re.IGNORECASE):
                self.details["asm_installed"] = True
                if not self.details["asm_instance"]:
                    self.details["asm_instance"] = instance_name
                if not self.details["asm_home"]:
                    self.details["asm_home"] = record["instance_home"]
                continue
            key = instance_name.lower()
            instance = self.details["instances"].setdefault(key, _new_instance(instance_name))
            instance["instance_in_oratab"] = True
            if not instance["instance_home"]:
                instance["instance_home"] = record["instance_home"]

    def discover_grid_type(self):
        values = parse_key_value_file(self.ocr_path)
        if "local_only" not in values:
            return
        local_only = values["local_only"].strip().lower()
        if local_only in ("true", "yes", "y", "1"):
            self.details["grid_type"] = "Restart"
        elif local_only in ("false", "no", "n", "0"):
            self.details["grid_type"] = "RAC"

    def _server_parameter(self, resource, parameter_name):
        hostname = self.details.get("grid_server", "")

        #debug = []
        for key, value in resource.items():
            #debug.append(key)

            #GEN_USR_ORA_INST_NAME=
            #GEN_USR_ORA_INST_NAME@SERVERNAME(t16-31b1)=lab01c_01
            #GEN_USR_ORA_INST_NAME@SERVERNAME(t16-31b2)=lab01c_02

            pattern = r"^{0}@SERVERNAME\(([^)]+)\)$".format(re.escape(parameter_name))

            match = re.match(pattern, key, re.IGNORECASE)
            if match and match.group(1).lower() == hostname.lower():
                return value.strip()

        #if resource.get("ID") == "ora.lab01c.db":
        #    self.details["debug"]={"parameters": debug, "hostname": hostname}

        return ""

    def _merge_asm_instance(self, resource):
        self.details["asm_installed"] = True
        self.details["asm_registered"] = True

        try:
            asm_instance_count = int(resource.get("INSTANCE_COUNT", 1))
        except (TypeError, ValueError):
            asm_instance_count = 0

        self.details["asm_instance_count"] = asm_instance_count

        self.details["asm_instance_name"] = self._server_parameter(resource, "GEN_USR_ORA_INST_NAME") or resource.get("USR_ORA_INST_NAME", "")

        if not self.details["asm_home"]:
            self.details["asm_home"] = self.details["grid_home"]

        self.details["asm_pwfile"] = resource.get("PWFILE", "")
        self.details["asm_spfile"] = resource.get("SPFILE", "")

    def _merge_crs_instance(self, resource):
        hostname = self.details.get("grid_server", "")

        try:
            instance_count = int(resource.get("INSTANCE_COUNT", 1))
        except (TypeError, ValueError):
            instance_count = 0

        instance_name = self._server_parameter(resource, "GEN_USR_ORA_INST_NAME") or resource.get("USR_ORA_INST_NAME", "").strip()

        if not instance_name:
            instance_name = resource.get("NAME", "")

        key = instance_name.lower()
        instance = self.details["instances"].setdefault(key, _new_instance(instance_name))
        instance["instance_registered"] = True
        instance["instance_name"] = instance_name
        instance["instance_count"] = instance_count

        match = re.match(r"^ora\.(.+)\.db$", resource.get("NAME", ""), re.IGNORECASE)
        if match:
          instance["instance_dbname"] = match.group(1)
        instance["instance_dbname_unique"] = resource.get("DB_UNIQUE_NAME", "")

        values = {
            "instance_home": normalize_path(resource.get("ORACLE_HOME", "")),
            "instance_pwfile": resource.get("PWFILE", ""),
            "instance_spfile": resource.get("SPFILE", ""),
            "instance_type": resource.get("DATABASE_TYPE", ""),
            "instance_management_policy": resource.get("MANAGEMENT_POLICY", ""),
            "instance_audit_dest": resource.get("GEN_AUDIT_FILE_DEST", ""),
            "instance_variables": parse_environment_assignments(resource.get("USR_ORA_ENV", "")),
            "instance_server": hostname,
        }
        for field, value in values.items():
            if value or field == "instance_variables":
                instance[field] = value

    def _merge_crs_listener(self, resource):
        listener_type = resource.get("TYPE")

        if listener_type == "ora.mgmtlsnr.type":
          match = re.match(r"^ora\.(.+)?$", resource.get("NAME", ""), re.IGNORECASE)
          if not match:
              return
        else:
          match = re.match(r"^ora\.(.+)\.lsnr?(?:\([^)]*\))?$", resource.get("NAME", ""), re.IGNORECASE)
          if not match:
              return

        # listener_types = {
        #     "ora.listener.type": "database",
        #     "ora.asm_listener.type": "asm",
        #     "ora.scan_listener.type": "scan",
        # }

        listener_name = match.group(1)
        listener, is_default = self._get_listener(listener_name)
        listener["listener_name"] = listener_name
        listener["listener_registered"] = True
        listener["listener_type"] = resource.get("TYPE")

        standard, ssl = parse_listener_endpoints(resource.get("ENDPOINTS", ""))
        listener["listener_standard_ports"] = standard
        listener["listener_ssl_ports"] = ssl

        if is_default:
            self._set_default_listener(listener)

    def discover_crsctl(self):
        if not self.details["grid_home"]:
            return
        hostname = crsctl_get_hostname(
            self.details["grid_home"], timeout=self.crsctl_timeout, runner=self.crsctl_runner
        )
        self.details["grid_server"] = hostname

        resources = crsctl_stat_resources(
            self.details["grid_home"], timeout=self.crsctl_timeout, runner=self.crsctl_runner
        )

        for resource in resources:
            resource_type = resource.get("TYPE", "")
            if resource_type == "ora.asm.type":
                self._merge_asm_instance(resource)
            elif resource_type in ("ora.database.type", "ora.mgmtdb.type"):
                self._merge_crs_instance(resource)
            elif resource_type in ("ora.listener.type", "ora.scan_listener.type", "ora.asm_listener.type", "ora.mgmtlsnr.type"):
                self._merge_crs_listener(resource)
