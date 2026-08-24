# wtferris.oracle

An Ansible collection for discovering Oracle software installations and runtime resources without shell-based process inspection.

## Module

### `wtferris.oracle.discovery`

The discovery module combines information from:

- `/etc/oraInst.loc` or `/var/opt/oracle/oraInst.loc` and the central `inventory.xml`
- Conventional Grid and database software roots (configurable through module arguments)
- Each software home's `inventory/ContentsXML/comps.xml`
- Native Python inspection of `/proc/<pid>/cmdline` and `/proc/<pid>/exe`
- `/etc/oratab` or `/var/opt/oracle/oratab`
- `/etc/oracle/ocr.loc`
- `<grid_home>/bin/crsctl get hostname`
- `<grid_home>/bin/crsctl stat res -f`

The module always reports `changed: false` and supports check mode. Oracle's original `software_build` and `software_installed` values are retained, while `software_build_date` and `software_installed_date` provide normalized `YYYY-MM-DD HH:MM:SS` values. Convert the normalized values with Ansible's `to_datetime` filter when performing date comparisons.

```yaml
- name: Discover Oracle installation
  wtferris.oracle.discovery:
  register: oracle

- ansible.builtin.debug:
    var: oracle.instances

- name: Identify homes installed before 2025
  ansible.builtin.debug:
    msg: "{{ item.value.software_home }}"
  loop: "{{ oracle.software_homes | dict2items }}"
  when:
    - item.value.software_installed_date | length > 0
    - item.value.software_installed_date | to_datetime < '2025-01-01 00:00:00' | to_datetime
```

Custom software roots can be supplied when installations do not use the defaults:

```yaml
- name: Discover Oracle installation in custom roots
  wtferris.oracle.discovery:
    grid_roots:
      - /opt/oracle/grid
    oracle_roots:
      - /opt/oracle/database
    crsctl_timeout: 15
  register: oracle
```

### `wtferris.oracle.home_version`

Run OPatch explicitly for one Oracle home and return the `oracle.server` base version and the highest `Database Release Update` patch version:

```yaml
- name: Read Oracle home versions
  wtferris.oracle.home_version:
    oracle_home: /u01/product/oracle/db19
  register: oracle_version

- name: Check the installed release update
  ansible.builtin.debug:
    msg: "Installed RU is {{ oracle_version.database_release_update_version }}"
  when: >-
    oracle_version.database_release_update_version_key >=
    '000000000019.000000000026.000000000000.000000000000.000000250121'
```

Versions are normalized to five positions. For example, `12.1.0.2` becomes `12.1.0.2.0`. The returned integer `*_version_parts` lists and fixed-width `*_version_key` strings preserve component-wise version ordering; unlike decimal conversion, they do not lose version boundaries or precision. `home_patched` reports whether the OPatch inventory contains any patch, independently of whether a Database Release Update is present.

This module is independent of discovery and only runs when explicitly invoked with an `oracle_home`.

### `wtferris.oracle.package_install`

Download, checksum, extract, and install a single-directory `.tgz`, `.tar.gz`, or `.zip` archive without placing temporary data beneath the remote user's home:

```yaml
- name: Install a package into /u01
  wtferris.oracle.package_install:
    installation_path: /u01/software
    temporary_directory_root: /u01/tmp
    source_url: https://packages.example.com/product.tar.gz
    md5sum: 0123456789abcdef0123456789abcdef
  register: package
```

The module calculates MD5 while downloading, verifies an optional expected checksum before extraction, validates archive member paths, requires exactly one top-level directory, and records successful installations as `.MD5.md5` symlinks beneath `~/.package_installation` by default. It uses operating-system `gzip`, `tar`, and `unzip` executables and supports local paths plus `file://`, `http://`, and `https://` sources.

Set `skip_post_relocation: true` to retain the extracted package in the returned `temporary_directory`. Normal relocation also returns the temporary path for troubleshooting, but that directory is removed after success. Set `force: true` to bypass inventory idempotency and rename an existing destination to `<destination>.trash` before installing the replacement.

The implementation is reusable by other collection modules:

```python
from ansible_collections.wtferris.oracle.plugins.module_utils.package_installer import install_package
```

## Requirements

- Ansible Core 2.15 or newer
- Python 3 on the managed host
- Permission for the remote user to inspect relevant Oracle processes in `/proc`

No third-party Python packages are required.

## Development

Run the parser and discovery unit tests from the collection root:

```bash
python3 -m unittest discover -s tests/unit -t . -v
```
