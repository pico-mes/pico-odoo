# pico-odoo

Odoo manufacturing add-on to connect to Pico MES. Build executable processes and step definitions with work instructions and quality checks using Pico MES and seamlessly integrate with Odoo's Inventory, BOM Management, and Manufacturing modules.

# Adding the Connector

### On-Premise/Community Edition

1. Clone or symlink the `pico_mrp` folder into your `addons_path` (likely configured in your `odoo.conf`). All files outside the `pico_mrp` folder in the base directory of this repo are only needed for development of the connector - those do not need to be symlinked.

### Odoo.sh

1. Add pico-odoo as a Git submodule following the [Odoo Submodule instructions](https://www.odoo.com/documentation/user/13.0/odoo_sh/advanced/submodules.html).
   - Use this repository URL: `git@github.com:pico-mes/pico-odoo.git`
   - Select branch: `13.0`
   - Path: `pico-mes/pico-odoo` _(can leave as the default)_

# Installation and Configuration

After following the steps above, we now need to install the connector in Odoo's interface. To do this:

1. Search for the Pico app in Odoo's Apps page. If you don't see it, you'll need to update the Apps list with the developer mode by following these steps:
   - Go to Settings, then find the Developer Tools section and click on "Activate the developer mode"
   - Go back to Apps back. In the top bar there should be a button to "Update apps list." Click on this, and then within the pop-up click on "Update"
   - You should now be able to find the Pico app in the Apps list.
1. Install the Pico MES connector through Apps list.
1. Once installed go to **Settings**, select **Manufacturing**, and enter `https://api.picomes.com` and the Pico MES provided api key in the Pico MES section, then click Save.
1. Return to the Manufacturing Settings and click **Subscribe to Webhooks**.
1. Once this is complete, check a specific User's permissions. In the "Other" section make sure the user is a Pico Manager or Pico User in the Pico Workflow dropdown menu.

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

# Contributing

### Python file formatting

Pico uses the [Black opinionated code formatter](https://black.readthedocs.io/en/stable/) for all Python files along with the default settings.
