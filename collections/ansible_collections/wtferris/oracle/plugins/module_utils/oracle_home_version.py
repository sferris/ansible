# -*- coding: utf-8 -*-

"""Extract Oracle Database versions from OPatch XML inventory output."""

from __future__ import absolute_import, division, print_function

import os
import re
import tempfile
import xml.etree.ElementTree as ET

from .oracle_command import EXECUTABLE_ERRORS, run_executable


class OracleHomeVersionError(Exception):
    """Raised when Oracle home version information cannot be collected."""


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def normalize_oracle_version(value):
    """Return a five-part Oracle version, integer parts, and a sortable key."""
    value = (value or "").strip()
    if not re.match(r"^\d+(?:\.\d+){0,4}$", value):
        raise ValueError("invalid Oracle version: %s" % value)

    parts = [int(part) for part in value.split(".")]
    parts.extend([0] * (5 - len(parts)))
    normalized = ".".join(str(part) for part in parts)
    comparison_key = ".".join("%012d" % part for part in parts)
    return normalized, parts, comparison_key


def _empty_release_update():
    return {
        "database_release_update_version": "",
        "database_release_update_version_parts": [],
        "database_release_update_version_key": "",
    }


def parse_opatch_inventory_xml(path):
    """Parse oracle.server and Database Release Update versions from OPatch XML."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, IOError, OSError) as exc:
        raise OracleHomeVersionError("unable to parse OPatch XML inventory: %s" % exc)

    base_version = ""
    for components in root.iter():
        if _local_name(components.tag).lower() != "components":
            continue
        for component in list(components):
            if _local_name(component.tag).lower() != "component":
                continue
            if component.attrib.get("id", "").strip().lower() != "oracle.server":
                continue
            for child in list(component):
                child_text = (child.text or "").strip()
                if _local_name(child.tag).lower() == "version" and child_text:
                    base_version = child_text
                    break
            if base_version:
                break
        if base_version:
            break

    if not base_version:
        raise OracleHomeVersionError("oracle.server component version was not found in OPatch XML")

    try:
        normalized_base, base_parts, base_key = normalize_oracle_version(base_version)
    except ValueError as exc:
        raise OracleHomeVersionError(str(exc))

    home_patched = False
    for patches in root.iter():
        if _local_name(patches.tag).lower() != "patches":
            continue
        if any(_local_name(child.tag).lower() == "patch" for child in list(patches)):
            home_patched = True
            break

    release_updates = []
    description_pattern = re.compile(
        r"^\s*Database Release Update\s*:\s*(\d+(?:\.\d+){0,4})\s*(?:\(|$)",
        re.IGNORECASE,
    )
    for element in root.iter():
        if _local_name(element.tag).lower() != "patchdescription":
            continue
        match = description_pattern.match(element.text or "")
        if not match:
            continue
        try:
            release_updates.append(normalize_oracle_version(match.group(1)))
        except ValueError:
            continue

    result = {
        "base_version": normalized_base,
        "base_version_parts": base_parts,
        "base_version_key": base_key,
        "home_patched": home_patched,
    }
    result.update(_empty_release_update())
    if release_updates:
        normalized_ru, ru_parts, ru_key = max(release_updates, key=lambda item: item[1])
        result.update({
            "database_release_update_version": normalized_ru,
            "database_release_update_version_parts": ru_parts,
            "database_release_update_version_key": ru_key,
        })
    return result


def get_oracle_home_versions(oracle_home, timeout=120, runner=None, temp_dir=None):
    """Run OPatch for an Oracle home and return its database version information."""
    oracle_home = os.path.abspath(os.path.expanduser((oracle_home or "").strip()))
    executable = os.path.join(oracle_home, "OPatch", "opatch")
    descriptor, xml_path = tempfile.mkstemp(prefix="opatch_inventory_", suffix=".xml", dir=temp_dir)
    os.close(descriptor)
    os.unlink(xml_path)

    try:
        try:
            completed = run_executable(
                executable,
                ["lsinventory", "-xml", xml_path],
                timeout=timeout,
                runner=runner,
                env_overrides={"ORACLE_HOME": oracle_home, "LC_ALL": "C"},
            )
        except EXECUTABLE_ERRORS as exc:
            raise OracleHomeVersionError("unable to execute OPatch: %s" % exc)

        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "OPatch failed").strip()
            raise OracleHomeVersionError(
                "OPatch exited with status %s: %s" % (completed.returncode, message)
            )
        if not os.path.isfile(xml_path):
            raise OracleHomeVersionError("OPatch did not create its XML inventory file")

        result = parse_opatch_inventory_xml(xml_path)
        result["oracle_home"] = oracle_home
        return result
    finally:
        try:
            os.unlink(xml_path)
        except OSError:
            pass
