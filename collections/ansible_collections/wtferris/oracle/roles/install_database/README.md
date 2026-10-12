# install_database role

Install an Oracle Database software archive while delegating transaction management to `wtferris.oracle.software_install`.

The outer role supplies the database-specific installation callback. The shared lifecycle continues to own metadata resolution, registration checks, locking, archive fetching and extraction, verification, registration commit, cache cleanup, and lock release.

## Example

```yaml
- name: Install Oracle Database software
  ansible.builtin.include_role:
    name: wtferris.oracle.install_database
  vars:
    dbahub_url: https://dbahub.example.com
    software_registration_directory: /u01/app/oracle/.packages
    software_package:
      name: oracle_database
      installation_directory: /u01/app/oracle/product/19.0.0/dbhome_1
      verifier_tasks_file: verifiers/executable.yml
      verification_executable: /u01/app/oracle/product/19.0.0/dbhome_1/bin/oracle
      type: oracle-database
      release: 19.26.0.0.250121
      package: linux-x64-19.26.0.0.250121-db.tar.gz
```

The archive must contain exactly one top-level directory. The callback atomically moves that directory to `software_package.installation_directory` while the lifecycle lock is held. It refuses to overwrite an existing unregistered destination.

The callback receives the standard lifecycle variables, including `package`, `software_resolved_package`, and `software_installation_directory`. Add database-specific preparation or installer execution to `tasks/install.yml`; do not create the registration symlink there, because registration remains the lifecycle's final commit point.
