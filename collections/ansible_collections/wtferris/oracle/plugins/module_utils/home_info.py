# -*- coding: utf-8 -*-

"""Read Oracle software-home metadata from inventory/ContentsXML/comps.xml."""

from __future__ import absolute_import, division, print_function

from datetime import datetime
import os
import xml.etree.ElementTree as ET


class OracleHomeInfoError(Exception):
    """Oracle home metadata could not be read."""


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def normalize_oracle_datetime(value):
    """Convert an Oracle inventory timestamp to an Ansible-friendly string."""
    value = (value or "").strip()
    if not value:
        return ""

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


def parse_comps_xml(path):
    """Extract component metadata from an Oracle comps.xml file."""
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


def get_oracle_home_info(oracle_home, software_homename=None):
    """Return the standard software-home record for one Oracle home."""
    oracle_home = os.path.normpath(
        os.path.abspath(os.path.expanduser((oracle_home or "").strip()))
    )
    comps_path = os.path.join(oracle_home, "inventory", "ContentsXML", "comps.xml")
    metadata = parse_comps_xml(comps_path)
    if not metadata:
        raise OracleHomeInfoError(
            "Oracle component metadata was not found in %s" % comps_path
        )

    result = {
        "software_home": oracle_home,
        "software_homename": (
            software_homename.strip()
            if software_homename and software_homename.strip()
            else os.path.basename(oracle_home).replace("-", "_").replace(".", "")
        ),
    }
    result.update(metadata)
    return result
