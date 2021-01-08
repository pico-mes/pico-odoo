# pico-odoo

Odoo manufacturing add-ons to connect to Pico MES

# Adding the Connector

### On-Premise/Community Edition

1. Clone or symlink the `pico_mrp` folder into your `addons_path` (likely configured in your `odoo.conf`). All files outside the `pico_mrp` folder in the base directory of this repo are only needed for development of the connector - those do not need to be symlinked.

### Odoo.sh

1. Add pico-odoo as a Git submodule following the [Odoo Submodule instructions](https://www.odoo.com/documentation/user/13.0/odoo_sh/advanced/submodules.html).
   - Use this repository URL: `git@github.com:pico-mes/pico-odoo.git`
   - Select branch: `13.0-test`
   - Path: `pico-mes/pico-odoo` _(can leave as the default)_

# Installation and Configuration

1. After following the steps above, update the Apps list via developer mode if you don't see the Pico MES connector in the listing.
1. Install the Pico MES connector through Apps list.
1. Once installed go to **Settings**, select **Manufacturing**, and enter `https://api.picomes.com` and the Pico MES provided api key in the Pico MES section, then click Save.
1. Return to the Manufacturing Settings and click **Subscribe to Webhooks**.

# Development Environment Setup

### copy nginx conf (if necessary)

```
#!/bin/bash
cp nginx-site.conf.sample nginx-site.conf
```

### copy odoo conf

```
#!/bin/bash
cp odoo.conf.sample odoo.conf
```

### set db name to odoo (default db) if you have more than 1 (if you ran test)

```
#odoo.conf
db_name = odoo
```

### change nginx port to not conflict with others (if necessary)

```
#!/bin/bash
cp docker-compose.override.yml.sample docker-compose.override.yml
```

### create odoo directory, and make sure user odoo user in container has write access

```
#!/bin/bash
mkdir -p var/data/odoo
```
