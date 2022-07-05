from odoo import api, models, fields, SUPERUSER_ID

from odoo.addons.pico_mrp.models.pico_workflow import pico_api

from logging import getLogger
_logger = getLogger(__name__)

class MRPProduction(models.Model):
    # _inherit = ['mrp.production', 'mail.activity.mixin']
    _inherit = 'mrp.production'

    pico_process_id = fields.Many2one(related='bom_id.pico_process_id')
    pico_work_order_ids = fields.One2many('mrp.production.pico.work.order', 'production_id',
                                          string='Pico Work Orders')
    no_finished_serial_err = ValueError('Process requires a finished serial, but none provided.')

    def _pico_create_work_orders(self):
        model = self.env['mrp.production.pico.work.order'].sudo()
        # oly ever create 1 pico work order, others will be created by back order
        # for i in range(int(self.product_qty)):
        for p in self.pico_process_id.process_ids:
            work_order = model.create({
                'production_id': self.id,
                'process_id': p.id,
            })
            work_order.pico_create()

    def action_confirm(self):
        for production in self.filtered(lambda l: l.pico_process_id):
            production.pico_validate_bom_setup()
        res = super().action_confirm()
        for production in self.filtered(lambda l: l.pico_process_id):
            production._pico_create_work_orders()
        return res

    def _pico_delete_work_orders(self):
        incomplete_work_orders = self.pico_work_order_ids.filtered(lambda wo: wo.state != "done")
        for work_order in incomplete_work_orders:
            work_order.pico_delete()
            work_order.unlink()

    def action_cancel(self):
        res = super().action_cancel()
        self._pico_delete_work_orders()
        return res

    def pico_validate_bom_setup(self):
        self.bom_id.pico_workflow_id.validate_bom_setup(self.bom_id, should_raise=True)

    def pico_complete(self):
        pending_work_orders = self.pico_work_order_ids.filtered(lambda wo: wo.state == 'pending')
        while pending_work_orders:
            work_orders = self.env['mrp.production.pico.work.order'].browse()
            for pending in pending_work_orders:
                if not work_orders.filtered(lambda wo: wo.process_id == pending.process_id):
                    work_orders += pending
            if work_orders.mapped('process_id') == self.pico_process_id.process_ids:
                # work_orders is a 'complete set'
                # reduce the pending work orders
                pending_work_orders -= work_orders
                self._pico_complete(work_orders)
                # mark lines as complete
                work_orders.write({'state': 'done'})
            else:
                # couldn't find a 'complete set'
                pending_work_orders = None

    def _pico_find_or_create_serial(self, product, serial_name):
        serial = self.env['stock.production.lot'].search([
            ('product_id', '=', product.id),
            ('name', '=', serial_name),
        ], limit=1)
        if not serial:
            serial = serial.create({
                'product_id': product.id,
                'name': serial_name,
                'company_id': self.env.user.company_id.id,
                # Required for creating, search may pick up any you have permissions to
            })
        return serial

    def _pico_complete(self, work_orders):
        # work_orders should be a 'complete set' of Pico Work Orders

        self.qty_producing = 1
        if self.product_tracking:
            # requires finished serial number
            serial_name = work_orders.find_finished_serial()
            if not serial_name:
                raise self.no_finished_serial_err
            serial = self._pico_find_or_create_serial(self.product_id, serial_name)
            # Assign lot we found or created
            self.lot_producing_id = serial
        res = self.button_mark_done()
        if res is not True:
            if res['xml_id'] == 'mrp.action_mrp_production_backorder':
                backorder = self.env['mrp.production.backorder'].with_context(res['context']).create({})
                backorder.action_backorder()
                return
            raise ValueError('unexpected response: %s' % ([res], ))


class MRPBoM(models.Model):
    _name = 'mrp.bom'
    _inherit = ['mrp.bom', 'mail.activity.mixin']

    pico_process_id = fields.Many2one('pico.workflow.process', string='Pico Process ID')
    pico_workflow_id = fields.Many2one(related='pico_process_id.workflow_id', string='Pico Workflow ID', store=True)

    @api.onchange('pico_process_id')
    def _onchange_pico_process(self):
        empty_pico_process = self.env['pico.workflow.process'].browse()
        for bom in self:
            if bom.pico_process_id:
                pico_processes = bom.pico_process_id.process_ids
                for line in bom.bom_line_ids.filtered(lambda l: l.pico_process_id and
                                                                l.pico_process_id not in pico_processes):
                    line.pico_process_id = empty_pico_process
            else:
                for line in bom.bom_line_ids:
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
    cycle_time = fields.Integer(string='Cycle Time')
    attr_value_ids = fields.One2many('mrp.pico.work.order.attr.value', 'work_order_id', string='Attr. Values')
    build_url = fields.Char()
    show_build_url = fields.Boolean()
    process_version = fields.Char()
    build_url_set = fields.Boolean(compute="_set_build_url_set")

    def _set_build_url_set(self):
        for wo in self:
            wo.build_url_set = not not wo.build_url

    def pico_create(self):
        self._pico_create()

    def _pico_create(self):
        api = pico_api(self.env)
        version = self.process_id.workflow_id.version_ids[0]
        process_result = api.create_work_order(self.process_id.pico_id,
                                               version.pico_id,
                                               self.production_id.name)
        self.write({
            'pico_id': process_result['id'],
            'state': 'running',
        })

    def pico_delete(self):
        self._pico_delete()

    def _pico_delete(self):
        api = pico_api(self.env)
        api.delete_work_order(self.pico_id)

    def _workorder_should_consume_in_real_time(self):
        # 1. Must be making a single 'unit' qty
        if self.production_id.product_qty != 1.0:
            _logger.warning('product quantity > 1,  %s' % ([self.production_id.product_qty], ))
            return False
        # 2. Anything consuming lots/serials should be unit so that it is 'safe' to just swap the lot
        moves_with_multi_qty_lot = self.production_id.move_raw_ids.filtered(lambda m:
                                                                            m.has_tracking in ('lot', 'serial')
                                                                            and m.product_uom_qty != 1.0)
        if moves_with_multi_qty_lot:
            _logger.warning('moves_with multi qty')
            return False
        # 3. Should not do it if there are not multiple work orders, because then the 'set' completing is preferred
        if len(self.production_id.pico_work_order_ids) == 1:
            return False
        return True

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

        # if work order already completed, just update work order attributes
        # leave state as done, and don't consume or produce
        already_done = self.state == 'done'

        write_vals = {'state': 'pending'}
        if already_done:
            write_vals['state'] = 'done'
        if 'startedAt' in values:
            write_vals['date_start'] = process_datetime(values['startedAt'])
        if 'completedAt' in values:
            write_vals['date_complete'] = process_datetime(values['completedAt'])
        if 'cycleTime' in values:
            write_vals['cycle_time'] = values['cycleTime']
        if 'buildUrl' in values:
            write_vals['build_url'] = values['buildUrl']
            write_vals['show_build_url'] = values['buildUrl'] != ""
        if 'processVersion' in values:
            write_vals['process_version'] = values['processVersion']
        if 'attributes' in values:
            line_commands = []
            if already_done:
                #clear previous attributes
                for attr_value_id in self.attr_value_ids:
                    line_commands.append((2, attr_value_id.id, 0))
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
        if already_done:
            # don't consume or produce
            return
        # assumes a work order is always producing 1
        qty_producing = 1
        # only complete moves related to the completed process
        for move in self.production_id.move_raw_ids.filtered(lambda m: m.bom_line_id.pico_process_id == self.process_id):
            lot_id = False
            # adjust qty_consuming
            if move.has_tracking in ('lot', 'serial'):
                serial_name = self.find_consumed_serial(move.bom_line_id)
                if not serial_name:
                    # do not want to raise error because we want the transaction to finish and queue
                    # the completion
                    break
                serial = self.production_id._pico_find_or_create_serial(move.product_id, serial_name)
                lot_id = serial.id

            qty_consuming = move.product_uom_qty * qty_producing/self.production_id.product_qty
            if move.move_line_ids:
                # Line was 'reserved', we may have a new serial, but we will for sure increment done qty
                move.move_line_ids.write({
                    'qty_done': qty_consuming,
                    'lot_id': lot_id,
                })
            else:
                # Was not reserved, create new line manually (will result in underflow if inventory isn't available)
                move.write({
                    'move_line_ids': [(0, 0, {
                        'product_id': move.product_id.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'product_uom_id': move.product_uom.id,
                        'qty_done': qty_consuming,
                        'lot_id': lot_id,
                    })]
                })

        self.production_id.pico_complete()

    def find_finished_serial(self):
        # self will be a 'complete set' of work orders
        attr_values = self.mapped('attr_value_ids').filtered(lambda av: av.attr_type == 'produce')
        if not attr_values:
            return None
        return attr_values[0].value

    def find_consumed_serial(self, bom_line):
        # self will be a 'complete set' of work orders
        attr_values = self.mapped('attr_value_ids').filtered(lambda av: av.attr_id == bom_line.pico_attr_id)
        if not attr_values:
            return None
        return attr_values[0].value

    def action_build_url(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': self.build_url, 'target': 'new'}

class MRPPicoWorkOrderAttrValue(models.Model):
    _name = 'mrp.pico.work.order.attr.value'
    _description = 'Pico Work Order Attr Value'
    _rec_name = 'value'

    work_order_id = fields.Many2one('mrp.production.pico.work.order', string='Pico Work Order')
    value = fields.Char(string='Value')
    attr_id = fields.Many2one('pico.workflow.process.attr', string='Attr', ondelete='set null')
    attr_type = fields.Selection(related='attr_id.type')
