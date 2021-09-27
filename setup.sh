#!/bin/bash

set -ex

odoo -i base,demo,pico_mrp -d odoo --stop-after-init --db_host=db -r odoo -w odoo_db_pass
