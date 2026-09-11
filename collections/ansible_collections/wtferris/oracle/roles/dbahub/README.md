# dbahub role

Interact with the selected dbahub v2 package APIs. Set `dbahub_operation`, include the role, and read the result from `dbahub_result`.

## Defaults

```yaml
dbahub_operation: health
dbahub_url: ""                         # required
dbahub_validate_certs: true
dbahub_timeout: 30

dbahub_client_id: ""
dbahub_client_secret: ""
dbahub_access_token: ""

dbahub_os: "{{ ansible_facts.system | lower }}"
dbahub_arch: "{{ ansible_facts.architecture | lower }}"
dbahub_type: oracle-database
dbahub_release: latest
dbahub_package: latest.tar.gz

dbahub_md5: ""
dbahub_package_path: ""
dbahub_update_symlink: false
dbahub_symlink_name: latest.tar.gz
dbahub_symlink_target: ""
```

## Health

```yaml
- name: Check dbahub health
  ansible.builtin.include_role:
    name: wtferris.oracle.dbahub
  vars:
    dbahub_url: https://dbahub.example.com
    dbahub_operation: health
```

## Authenticate

Authentication uses OAuth client credentials at `POST /oauth/token`. Mutation operations authenticate automatically when `dbahub_access_token` is empty. Credentials and token tasks use `no_log`.

```yaml
- name: Authenticate to dbahub
  ansible.builtin.include_role:
    name: wtferris.oracle.dbahub
  vars:
    dbahub_url: https://dbahub.example.com
    dbahub_operation: authenticate
    dbahub_client_id: deployment-client
    dbahub_client_secret: "{{ vault_dbahub_client_secret }}"
```

The bearer token is available as `dbahub_access_token`; the token response is available as `dbahub_result`.

## Search by MD5

```yaml
- name: Find a package checksum
  ansible.builtin.include_role:
    name: wtferris.oracle.dbahub
  vars:
    dbahub_url: https://dbahub.example.com
    dbahub_operation: search_by_md5
    dbahub_md5: 0123456789abcdef0123456789abcdef
```

## List releases

```yaml
- name: List Oracle Database releases
  ansible.builtin.include_role:
    name: wtferris.oracle.dbahub
  vars:
    dbahub_url: https://dbahub.example.com
    dbahub_operation: releases
```

## List packages for a release

```yaml
- name: List latest packages
  ansible.builtin.include_role:
    name: wtferris.oracle.dbahub
  vars:
    dbahub_url: https://dbahub.example.com
    dbahub_operation: packages
    dbahub_release: latest
```

## Query one package

The `package` operation reads the release package listing and returns the metadata entry whose `item` matches `dbahub_package`. The package defaults to `latest.tar.gz`.

```yaml
- name: Query the latest package
  ansible.builtin.include_role:
    name: wtferris.oracle.dbahub
  vars:
    dbahub_url: https://dbahub.example.com
    dbahub_operation: package
    dbahub_release: latest
    dbahub_package: latest.tar.gz

- ansible.builtin.debug:
    var: dbahub_result.url
```

The role fails with a descriptive message when the requested package is not present in the release.

## Upload a package

The upload is read from the managed host (`remote_src: true`). Its MD5 is calculated and sent in `X-Checksum-MD5` for server-side verification.

```yaml
- name: Upload package and update latest alias
  ansible.builtin.include_role:
    name: wtferris.oracle.dbahub
  vars:
    dbahub_url: https://dbahub.example.com
    dbahub_operation: upload
    dbahub_client_id: deployment-client
    dbahub_client_secret: "{{ vault_dbahub_client_secret }}"
    dbahub_release: 19.26.0.0.250121
    dbahub_package: linux-x64-19.26.0.0.250121-db.tar.gz
    dbahub_package_path: /u01/stage/linux-x64-19.26.0.0.250121-db.tar.gz
    dbahub_update_symlink: true
    dbahub_symlink_name: latest.tar.gz
```

`dbahub_symlink_name` must differ from `dbahub_package` when updating an alias.

## Update a symlink

For the `symlink` operation, `dbahub_package` is the alias name and `dbahub_symlink_target` is an existing package in the same release.

```yaml
- name: Update latest package alias
  ansible.builtin.include_role:
    name: wtferris.oracle.dbahub
  vars:
    dbahub_url: https://dbahub.example.com
    dbahub_operation: symlink
    dbahub_client_id: deployment-client
    dbahub_client_secret: "{{ vault_dbahub_client_secret }}"
    dbahub_release: 19.26.0.0.250121
    dbahub_package: latest.tar.gz
    dbahub_symlink_target: linux-x64-19.26.0.0.250121-db.tar.gz
```
