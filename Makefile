
run:
	ansible-playbook -i inventory.yml playbook-test.yml

test:
	PYTHONPATH=collections/ansible_collections/wtferris/oracle \
 	  python3 collections/ansible_collections/wtferris/oracle/unit/plugins/module_utils/test_oracle_discovery.py
	PYTHONPATH=collections/ansible_collections/wtferris/oracle \
 	  python3 collections/ansible_collections/wtferris/oracle/unit/plugins/module_utils/test_oracle_home_version.py

