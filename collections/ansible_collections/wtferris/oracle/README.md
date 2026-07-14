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

The module always reports `changed: false` and supports check mode.

```yaml
- name: Discover Oracle installation
  wtferris.oracle.discovery:
  register: oracle

- ansible.builtin.debug:
    var: oracle.instances
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
