NULL=

UNITS=                               \
  test_oracle_discovery.py           \
  test_oracle_home_version.py        \
  test_package_installer.py          \
  $(NULL)

run:
	ansible-playbook -i inventory.yml playbook-test.yml

test: $(UNITS)

$(UNITS):
	PYTHONPATH=collections/ansible_collections/wtferris/oracle \
 	  python3 collections/ansible_collections/wtferris/oracle/unit/plugins/module_utils/$@

