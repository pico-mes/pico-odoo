from odoo import api, models, fields
from odoo.exceptions import UserError

from odoo.addons.pico_mrp.models.pico_workflow import pico_api


class MRPProduction(models.Model):
    _inherit = 'mrp.production'

    pico_workflow_version_id = fields.Many2one('pico.workflow.version', string='Pico Workflow Version ID')

    @api.model
    def create(self, values):
        if 'pico_workflow_version_id' not in values and 'bom_id' in values:
            bom = self.env['mrp.bom'].browse(values['bom_id'])
            if bom.pico_workflow_id and bom.pico_workflow_id.version_ids:
                values['pico_workflow_version_id'] = bom.pico_workflow_id.version_ids[0].id
        res = super(MRPProduction, self).create(values)
        return res

    @api.onchange('bom_id')
    def _onchange_pico_bom_id(self):
        if self.bom_id.pico_workflow_id and self.bom_id.pico_workflow_id.version_ids:
            self.pico_workflow_version_id = self.bom_id.pico_workflow_id.version_ids[0]

    def _pico_create_work_orders(self):
        if self.pico_workflow_version_id:
            api = pico_api(self.env)
            created_process = {}
            for p in self.pico_workflow_version_id.workflow_id.process_ids:
                # process_id, workflow_version_id, annotation=''
                process_result = api.create_work_order(p.pico_id, self.pico_workflow_version_id.pico_id, self.name)
                # TODO can process_result fail
                created_process[p] = process_result
            # TODO create work order lines
            return created_process
        else:
            raise UserError("Cannot save without giving Pico Workflow at least on process.")

    def action_confirm(self):
        res = super().action_confirm()
        for s in self.filtered(lambda l: l.pico_workflow_version_id):
            s._pico_create_work_orders()
        return res


class MRPBoM(models.Model):
    _inherit = 'mrp.bom'

    pico_workflow_id = fields.Many2one('pico.workflow', string='Pico Workflow ID')
