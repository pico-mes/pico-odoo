FROM registry.gitlab.com/hibou-io/hibou-odoo/suite:15.0

COPY --chown=104 ./ /opt/odoo/pico
COPY ./odoo.conf.sample /etc/odoo/odoo.conf

