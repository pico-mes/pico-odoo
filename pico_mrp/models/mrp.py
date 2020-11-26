from odoo import api, models, fields
from odoo.addons.queue_job.job import job

from odoo.addons.pico_mrp.models.pico_workflow import pico_api


class MRPProduction(models.Model):
    _inherit = 'mrp.production'

    pico_workflow_version_id = fields.Many2one('pico.workflow.version', string='Pico Workflow Version ID')
    pico_workflow_id = fields.Many2one(related='bom_id.pico_workflow_id')
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
        model = self.env['mrp.production.pico.work.order'].sudo()
        for i in range(int(self.product_qty)):
            for p in self.pico_workflow_version_id.workflow_id.process_ids:
                work_order = model.create({
                    'production_id': self.id,
                    'process_id': p.id,
                })
                work_order.pico_create()

    def action_confirm(self):
        for production in self.filtered(lambda l: l.pico_workflow_version_id):
            production.pico_validate_bom_setup()
        res = super().action_confirm()
        for production in self.filtered(lambda l: l.pico_workflow_version_id):
            production._pico_create_work_orders()
        return res

    def pico_validate_bom_setup(self):
        self.bom_id.pico_workflow_id.validate_bom_setup(self.bom_id, should_raise=True)

    @job(default_channel='root.pico')
    def pico_complete(self):
        # This is called from a queue job, so we need to sudo to get correct permissions
        self = self.sudo()
        pending_work_orders = self.pico_work_order_ids.filtered(lambda wo: wo.state == 'pending')
        while pending_work_orders:
            work_orders = self.env['mrp.production.pico.work.order'].browse()
            for pending in pending_work_orders:
                if not work_orders.filtered(lambda wo: wo.process_id == pending.process_id):
                    work_orders += pending
            if work_orders.mapped('process_id') == self.pico_workflow_version_id.workflow_id.process_ids:
                # work_orders is a 'complete set'
                # reduce the pending work orders
                pending_work_orders -= work_orders
                self._pico_complete(work_orders)
                # mark lines as complete
                work_orders.write({'state': 'done'})
            else:
                # couldn't find a 'complete set'
                pending_work_orders = None

    def _pico_complete(self, work_orders):
        # work_orders should be a 'complete set' of Pico Work Orders
        def _serial(product, serial_name):
            serial = self.env['stock.production.lot'].search([
                ('product_id', '=', product.id),
                ('name', '=', serial_name),
            ], limit=1)
            if not serial:
                serial = serial.create({
                    'product_id': product.id,
                    'name': serial_name,
                    'company_id': self.env.user.company_id.id,  # Required for creating, search may pick up any you have permissions to
                })
            return serial

        produce = self.env['mrp.product.produce'].with_context(default_production_id=self.id).create({})
        if produce.serial:
            # requires finished serial number
            serial_name = work_orders.find_finished_serial()
            if not serial_name:
                raise ValueError('Process requires a finished serial, but none provided.')
            serial = _serial(produce.product_id, serial_name)
            # Assign lot we found or created
            produce.finished_lot_id = serial
        for line in produce.raw_workorder_line_ids.filtered(lambda line: line.product_tracking in ('lot', 'serial')):
            serial_name = work_orders.find_consumed_serial(line.move_id.bom_line_id)
            raise ValueError(serial_name)
            if not serial_name:
                raise ValueError('Stock Move requires a consumed serial, but none provided.')
            serial = _serial(line.product_id, serial_name)
            line.lot_id = serial
        produce.do_produce()
        # If this is the last qty to produce, we can finish the MRP Production
        if self.state == 'to_close':
            self.button_mark_done()


class MRPBoM(models.Model):
    _name = 'mrp.bom'
    _inherit = ['mrp.bom', 'mail.activity.mixin']

    pico_workflow_id = fields.Many2one('pico.workflow', string='Pico Workflow ID')

    @api.onchange('pico_workflow_id')
    def _onchange_pico_workflow(self):
        empty_pico_process = self.env['pico.workflow.process'].browse()
        for bom in self:
            pico_workflow = bom.pico_workflow_id
            for line in bom.bom_line_ids.filtered(lambda l: l.pico_process_id and
                                                            l.pico_process_id not in pico_workflow.process_ids):
                line.pico_process_id = empty_pico_process


class MRPBoMLine(models.Model):
    _inherit = 'mrp.bom.line'

    pico_process_id = fields.Many2one('pico.workflow.process', string='Pico Process')
    pico_attr_id = fields.Many2one('pico.workflow.process.attr', string='Pico Attr.')

    # onchange process need to clear pico attr
    @api.onchange('pico_process_id')
    def _onchange_pico_process_id(self):
        self.update({'pico_attr_id': False})


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
        ('pending', 'Pending'),
        ('done', 'Done'),
    ], string='State', default='draft')
    date_start = fields.Datetime(string='Started At')
    date_complete = fields.Datetime(string='Completed At')
    attr_value_ids = fields.One2many('mrp.pico.work.order.attr.value', 'work_order_id', string='Attr. Values')

    def pico_create(self):
        self.with_delay()._pico_create()

    @job(default_channel='root.pico')
    def _pico_create(self):
        api = pico_api(self.env)
        process_result = api.create_work_order(self.process_id.pico_id,
                                               self.production_id.pico_workflow_version_id.pico_id,
                                               self.production_id.name)
        self.write({
            'pico_id': process_result['id'],
            'state': 'running',
        })

    def pico_complete(self, values):
        def process_datetime(value):
            value = value.replace('T', ' ')
            return value.split('.')[0]
        # This is called on an empty record set from the controller
        if not self:
            pico_id = values.get('workOrderId', 'SENTINEL_THAT_DOESNT_EXIST')
            self = self.search([('pico_id', '=', pico_id)], limit=1)
            if not self:
                return

        write_vals = {'state': 'pending'}
        if 'startedAt' in values:
            write_vals['date_start'] = process_datetime(values['startedAt'])
        if 'completedAt' in values:
            write_vals['date_complete'] = process_datetime(values['completedAt'])
        if 'attributes' in values:
            line_commands = []
            for attr_vals in values.get('attributes', []):
                attr = self.process_id.attr_ids.filtered(lambda a: a.pico_id == attr_vals['id'])
                if attr:
                    line_commands.append((0, 0, {
                        'value': attr_vals['value'],
                        'attr_id': attr.id,
                    }))
            if line_commands:
                write_vals['attr_value_ids'] = line_commands
        self.write(write_vals)
        if self._context.get('skip_queue_job'):
            self.production_id.pico_complete()
        else:
            self.production_id.with_delay().pico_complete()

    def find_finished_serial(self):
        # self will be a 'complete set' of work orders
        attr_values = self.mapped('attr_value_ids').filtered(lambda av: av.attr_type == 'produce')
        if not attr_values:
            return None
        return attr_values[0].value

    def find_consumed_serial(self, bom_line):
        # self will be a 'complete set' of work orders
        attr_values = self.mapped('attr_value_ids').filtered(lambda av: av.attr_id == bom_line.pico_attr_value_id)
        if not attr_values:
            return None
        return attr_values[0].value


class MRPPicoWorkOrderAttrValue(models.Model):
    _name = 'mrp.pico.work.order.attr.value'
    _description = 'Pico Work Order Attr Value'
    _rec_name = 'value'

    work_order_id = fields.Many2one('mrp.production.pico.work.order', string='Pico Work Order')
    value = fields.Char(string='Value')
    attr_id = fields.Many2one('pico.workflow.process.attr', string='Attr', ondelete='set null')
    attr_type = fields.Selection(related='attr_id.type')
