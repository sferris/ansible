# software_install role

Transactionally resolve, fetch, install, verify, and register archive-based software. Registration is committed only after the package-specific installer and verifier complete successfully.

## Lifecycle

1. Include a metadata resolver.
2. Inspect the exact MD5-and-name registration link.
3. Verify an already registered installation and return without fetching when valid.
4. Acquire an atomic installation lock.
5. Recheck registration after acquiring the lock.
6. Call `wtferris.oracle.fetch_archive` when installation is still required.
7. Include the package-specific installer.
8. Include the package-specific verifier, or perform default directory verification.
9. Create the registration symlink as the final commit point.
10. Optionally remove the fetched cache.

Registration is never a handler or an `always` task.

## Inputs

```yaml
software_package:
  name: oracle_client                         # required, safe filename component
  installation_directory: /u01/oracle/client # required
  installer_tasks_file: installers/oracle_client.yml # required, role-relative
  verifier_tasks_file: verifiers/oracle_client.yml   # optional, role-relative

software_metadata_resolver_tasks_file: resolvers/dbahub.yml
software_registration_directory: "{{ ansible_user_dir }}/.packages"
software_cleanup_temporary_directory: true
software_repair_invalid_registration: false
software_fetch_installation_path: ""         # defaults to installation parent
software_fetch_force: false
software_fetch_lock_timeout: 300
software_install_lock_retries: 60
software_install_lock_delay: 5
```

Package-specific dictionaries may contain additional keys consumed by their resolver, installer, or verifier.

## Metadata resolver contract

Resolver task files must live under this role's `tasks/resolvers/` directory and be selected with a path such as `resolvers/dbahub.yml`. Arbitrary caller-relative paths are intentionally unsupported because Ansible resolves dynamic includes relative to the containing role.

A resolver must set:

```yaml
package_url: file:///path/to/archive.tar.gz
package_md5sum: 0123456789abcdef0123456789abcdef
software_resolved_package:
  name: archive.tar.gz
  type: oracle-database
  url: file:///path/to/archive.tar.gz
  md5sum: 0123456789abcdef0123456789abcdef
```

`resolvers/dbahub.yml` uses `wtferris.oracle.dbahub` with its `package` operation. It accepts these optional `software_package` keys:

```yaml
software_package:
  os: linux
  arch: x86_64
  type: oracle-database
  release: latest
  package: latest.tar.gz
```

Configure `dbahub_url`, authentication, and TLS variables as documented by the dbahub role.

`resolvers/fixture.yml` consumes `software_fixture_package_metadata` and is intended for offline tests or caller-provided metadata.

## Installer contract

Installer files must live under `tasks/installers/`. They receive:

- `software_package`: caller configuration.
- `software_resolved_package`: complete resolver metadata.
- `software_installation_directory`: normalized final directory.
- `package`: the complete registered `fetch_archive` result, including:

```yaml
package.md5sum
package.temporary_directory
package.unpack_directory
package.contents
```

Installers own only installation. They must not create or modify the registration link. They must be safely rerunnable and should validate meaningful artifacts rather than treating an empty directory as success.

### Directory publication example

```yaml
software_package:
  name: oracle_database
  installation_directory: /u01/product/oracle/19.26/db
  installer_tasks_file: installers/publish_directory.yml
```

`publish_directory.yml` requires one top-level extracted directory and atomically renames the candidate into place.

### Installer-program example

```yaml
software_package:
  name: oracle_client
  installation_directory: /u01/product/oracle/19.26/client
  installer_tasks_file: installers/run_installer.yml
  installer_executable: install/runInstaller
  installer_arguments:
    - -silent
    - -responseFile
    - /u01/config/client.rsp
  installer_environment:
    ORACLE_BASE: /u01/product/oracle
  verification_path: /u01/product/oracle/19.26/client/bin/sqlplus
  verifier_tasks_file: verifiers/executable.yml
  verification_executable: /u01/product/oracle/19.26/client/bin/sqlplus
```

The example uses `creates: software_package.verification_path` for rerun safety.

## Verifier contract

Verifier files must live under `tasks/verifiers/`. A verifier should use `ansible.builtin.stat`, assertions, or a read-only command with `changed_when: false`. It must fail when installation is incomplete.

When omitted, `verifiers/default.yml` requires `software_installation_directory` to exist and be a directory. `verifiers/executable.yml` checks a meaningful executable artifact.

Verifiers run both after installation and when evaluating an existing registration. Therefore, they must not require `package` to be defined when checking a pre-existing installation.

## Registration

The registration path is:

```text
<software_registration_directory>/.<md5>-<software_package.name>
```

It is an absolute symlink to `software_package.installation_directory`.

A package is installed only when:

- the registration object is a symlink;
- its recorded target is the expected installation directory;
- following it reaches an existing directory; and
- verification succeeds.

A broken link to the expected destination causes installation to run. A regular file, directory, or wrong-target symlink fails without modification. Set `software_repair_invalid_registration: true` to explicitly remove and repair such an object.

A changed MD5 creates a distinct registration transaction. Package-specific installer logic remains responsible for safe upgrade behavior when multiple revisions share one final directory.

## Failure and cleanup

Installer or verifier failure prevents registration. Errors are not ignored.

Cleanup defaults to `true` and runs from an `always` section after success or failure without masking the original lifecycle failure. Set `software_cleanup_temporary_directory: false` when the deterministic `fetch_archive` cache must be retained or another process still needs it.

Cleanup is deliberately conservative. It proceeds only when `.complete` is a regular file and `package.unpack_directory` is exactly `<package.temporary_directory>/extract` with the literal basename `extract`. The role recursively removes only that `extract` directory, removes `.complete`, and then uses `rmdir` on the cache directory. Any unexpected remaining content prevents removal of the parent and is reported for manual inspection.

## Concurrency

`fetch_archive` locks only download and unpack publication. This role additionally acquires an atomic `mkdir` lock named after the exact MD5 and package name and holds it through installation, verification, and registration. A second execution waits, acquires the lock, then rechecks registration before doing work.

This protects concurrent executions on the same filesystem and registration directory. It does not provide a distributed lock across hosts with independent filesystems. A process killed without Ansible cleanup can leave a stale lock; the timeout diagnostic identifies the path that must be inspected before manual removal.

## Check mode

For a valid existing registration, check mode verifies and reports no change. For an absent or broken registration, it reports that installation would change without fetching, installing, locking, or registering. Package-specific install and post-install verification cannot be simulated.

## Privilege escalation

The role does not set `become`. The caller must provide privileges needed to write the installation directory and registration directory and to run the package installer.

## Complete dbahub example

```yaml
- hosts: database_servers
  become: true
  roles:
    - role: wtferris.oracle.software_install
      vars:
        dbahub_url: https://dbahub.example.com
        software_package:
          name: oracle_database
          installation_directory: /u01/product/oracle/19.26/db
          installer_tasks_file: installers/publish_directory.yml
          verifier_tasks_file: verifiers/executable.yml
          verification_executable: /u01/product/oracle/19.26/db/bin/oracle
          type: oracle-database
          release: 19.26.0.0.250121
          package: linux-x64-19.26.0.0.250121-db.tar.gz
```

## Contributor guide

To add package support:

1. Add a safely rerunnable task file beneath `tasks/installers/`.
2. Optionally add a read-only verifier beneath `tasks/verifiers/`.
3. Add a resolver only when the existing dbahub contract is insufficient.
4. Never create registration links from package-specific tasks; the central transaction always owns verification and registration.
