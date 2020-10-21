from odoo import api, models, fields
from odoo.addons.queue_job.job import job

from odoo.addons.pico_mrp.models.pico_workflow import pico_api


class MRPProduction(models.Model):
    _inherit = 'mrp.production'

    pico_workflow_version_id = fields.Many2one('pico.workflow.version', string='Pico Workflow Version ID')
    pico_work_order_ids = fields.One2many('mrp.production.pico.work.order', 'production_id',
                                          string='Pico Work Orders')

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
            model = self.env['mrp.production.pico.work.order'].sudo()
            for p in self.pico_workflow_version_id.workflow_id.process_ids:
                work_order = model.create({
                    'production_id': self.id,
                    'process_id': p.id,
                })
                work_order.pico_create()

    def action_confirm(self):
        res = super().action_confirm()
        for s in self.filtered(lambda l: l.pico_workflow_version_id):
            s._pico_create_work_orders()
        return res

    def pico_complete(self):
        if all(wo.state == 'done' for wo in self.pico_work_order_ids):
            self._pico_complete()

    def _pico_complete(self):
        # TODO handle completed serial number?
        move_line = self.env['stock.move.line']
        for sm in self.move_finished_ids.filtered(lambda sm: sm.state not in ('done', 'cancel')):
            # TODO all qty can be done by single line
            move_line.create({
                'move_id': sm.id,
                'product_id': sm.product_id.id,
                # 'lot_id': self.finished_lot_id.id,  # from mrp.abstract.workorder
                'product_uom_qty': self.product_qty,
                'product_uom_id': sm.product_uom.id,
                'qty_done': self.product_qty,
                'location_id': sm.location_id.id,
                'location_dest_id': sm.location_dest_id.id,
            })
        if self.post_inventory():
            self.state = 'done'


class MRPBoM(models.Model):
    _inherit = 'mrp.bom'

    pico_workflow_id = fields.Many2one('pico.workflow', string='Pico Workflow ID')


class MRPBoMLine(models.Model):
    _inherit = 'mrp.bom.line'

    pico_process_id = fields.Many2one('pico.workflow.process', string='Pico Process')


class MRPPicoWorkOrder(models.Model):
    _name = 'mrp.production.pico.work.order'
    _description = 'Pico Work Order'
    _rec_name = 'pico_id'

    pico_id = fields.Char()
    process_id = fields.Many2one('pico.workflow.process', string='Process')
    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('running', 'Running'),
        ('done', 'Done'),
    ], string='State', default='draft')
    date_start = fields.Datetime(string='Started At')
    date_complete = fields.Datetime(string='Completed At')

    def pico_create(self):
        self.with_delay()._pico_create()

    @job(default_channel='root.pico')
    def _pico_create(self):
        api = pico_api(self.env)
        process_result = api.create_work_order(self.process_id.pico_id,
                                               self.production_id.pico_workflow_version_id.pico_id,
                                               self.production_id.name)
        # TODO can process_result fail
        self.write({
            'pico_id': process_result['id'],
            'state': 'running',
        })

    def pico_complete(self, values):
        def process_datetime(value):
            value = value.replace('T', ' ')
            return value.split('.')[0]
        write_vals = {'state': 'done'}
        if 'startedAt' in values:
            write_vals['date_start'] = process_datetime(values['startedAt'])
        if 'completedAt' in values:
            write_vals['date_complete'] = process_datetime(values['completedAt'])
        # TODO process attributes for 'consumed lots/serials'
        stock_moves_for_process = self.production_id.move_raw_ids\
            .filtered(lambda sm: sm.bom_line_id.pico_process_id == self.process_id)
        for sm in stock_moves_for_process:
            sm.quantity_done = sm.product_uom_qty
        self.write(write_vals)
        self.production_id.pico_complete()
