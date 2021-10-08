# pico-odoo

Odoo manufacturing add-ons to connect to Pico MES

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

# Additional Logging

Extra logging can be added using Odoo's debug logs. To enable logging in any particular file within the Pico connector add the following lines to the top:

```
from logging import getLogger
_logger = getLogger(__name__)
```

Then within the section of interest, add log print statements as such:

```
_logger.info('Pico Rocks! But check this variable... {}'.format(thing_i_want_2_log))
```

# Development

## Setup

1. Copy odoo conf

```
cp odoo.conf.sample odoo.conf
```

1. Set db name to odoo (default db) in `odoo.conf`, if you have more than 1 (if you ran test)

```
#odoo.conf
db_name = odoo
```

1. Spin up external `odoo` network if it does not already exist: `docker network create odoo`
1. Confirm that api has access to this the `odoo` external network in pico-docker's docker-compose. There is an example of the setup in `docker-compose.overrides.example.yml` in pico-mes/pico-docker.
1. add an entry to your `/etc/hosts` like this:

```
127.0.0.1       odoo
```

1. Install odoo

```
docker-compose run --rm odoo -- -i pico_mrp,base -d odoo --stop-after-init --db_host=db -r odoo -w odoo
```

5. `docker-compose up -d` it all

## Running Tests

Note: initial run will take a while, but subsequent runs should be quicker:

```
docker-compose run --rm odoo bash
/opt/odoo/pico/test.sh
```
