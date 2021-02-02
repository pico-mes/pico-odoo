from odoo import fields, models
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pico_url = fields.Char(string="Pico Endpoint URL", config_parameter="pico.url")
    pico_customer_key = fields.Char(
        string="Pico Customer Key", config_parameter="pico.customer.key"
    )

    def pico_endpoint_subscribe(self):
        if not self.pico_url:
            raise UserError("missing Pico Endpoint URL")
        self.env["pico.workflow"].pico_subscribe()
