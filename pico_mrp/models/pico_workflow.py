from odoo import api, models, fields, SUPERUSER_ID
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from .api.pico_requests import PicoMESRequest, ConnectionError, HTTPError, InvalidSchema


def pico_api(env):
    params = env['ir.config_parameter'].sudo()
    pico_url = params.get_param('pico.url')
    pico_customer_key = params.get_param('pico.customer.key', None)
    if not pico_url:
        raise ValidationError('Creating Pico API requires a config parameter "pico.url"')
    return PicoMESRequest(pico_url, pico_customer_key)


class PicoBoMNeedsMap(ValidationError):
    pass


class PicoMESWorkflow(models.Model):
    _name = 'pico.workflow'
    _description = 'Workflow'

    name = fields.Char("Name")
    active = fields.Boolean(default=True)
    pico_id = fields.Char("Workflow ID")

    process_ids = fields.One2many('pico.workflow.process', 'workflow_id', string='Child Processes')
    version_ids = fields.One2many('pico.workflow.version', 'workflow_id', string='Child Versions')

    def pico_subscribe(self):
        api = pico_api(self.env)
        base_url = self._get_base_url()
        try:
            api.subscribe_jsonrpc(base_url + '/picoapi/webhook', 'newWorkflowVersionMethod', 'workOrderCompleteMethod')
        except InvalidSchema:
            raise UserError('Invalid Pico Endpoint URL (%s)' % (api.url, ))
        except ConnectionError:
            raise UserError('Cannot connect to Pico Endpoint URL (%s)' % (api.url, ))
        except HTTPError:
            raise UserError('Webhook Subscribe resulted in an error from Pico Endpoint URL (%s)' % (api.url, ))

    def _get_base_url(self):
        base_url = request and request.httprequest.url_root or self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return base_url.rstrip('/')

    @api.model
    def process_pico_data(self, values):
        return self._sync_data(values)

    def button_validate_bom_setup(self):
        no_errors = self.validate_bom_setup()
        if not no_errors:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Notice',
                    'message': 'BoM Activities Scheduled.',
                    'sticky': False,
                },
            }
        return no_errors

    def validate_bom_setup(self, boms=None, should_raise=False):
        res = True
        for workflow in self:
            if not boms:
                # Need to specifically find archived processes,
                # because BoM's for archived processes are not valid
                processes = self.env['pico.workflow.process'].with_context(active_test=False).search([
                    ('workflow_id', '=', workflow.id),
                ])
                boms = self.env['mrp.bom'].search([
                    ('pico_process_id', 'in', processes.ids),
                ])
            for bom in boms:
                try:
                    self._validate_bom_setup(bom)
                except PicoBoMNeedsMap:
                    if should_raise:
                        raise
                    res = False
                    bom.activity_schedule(
                        'pico_mrp.mail_activity_type_bom_map_needed',
                        user_id=bom.product_tmpl_id.responsible_id.id or SUPERUSER_ID,
                        note='The Pico Workflow requires setup or mapping consumed attributes.'
                    )
        return res

    def _validate_bom_setup(self, bom):
        # implied: inactive process shouldn't be used in a BoM
        if bom.pico_process_id and not bom.pico_process_id.active:
            raise PicoBoMNeedsMap('BoM Linked to Archived Process.')
        lines = bom.bom_line_ids.filtered(lambda l: l.pico_process_id and not l.pico_process_id.active)
        if lines:
            raise PicoBoMNeedsMap('BoM Line(s) linked to Archived Process.')

        # 1. All process attr's that are marked 'to consume' must be on a BoM Line
        process_attrs_to_consume = bom.pico_process_id.process_ids\
            .mapped('attr_ids').filtered(lambda a: a.type == 'consume')

        bom_attrs_to_consume = bom.bom_line_ids.mapped('pico_attr_id')
        if process_attrs_to_consume != bom_attrs_to_consume:
            raise PicoBoMNeedsMap('Not all consumption attrs are mapped to BoM Lines.')

        # 2. All BoM lines who's product trackig is (lot/serial) must have an associated consume attr
        lines = bom.bom_line_ids.filtered(lambda l: l.product_id.tracking in ('lot', 'serial') and not l.pico_attr_id)
        if lines:
            raise PicoBoMNeedsMap('Not all lot/serialized items are mapped to a pico attribute.')

    # TODO do we NEED a job here? tests are difficult
    # @job(default_channel='root.pico')
    def _sync_data(self, values):
        """ if data received has new fields, update model to match
            else missing, archive out of sink models

            then write end results
        """
        # Unmarshall the version id
        version_id = values.get('id')
        if not version_id:
            raise ValidationError('Missing Workflow Version ID.')

        # Unmarshall the workflow data
        workflow_data = values.get('workflow')
        if not workflow_data:
            raise ValidationError('Missing Workflow Data.')

        workflow_pico_id = workflow_data.get('id')
        if not workflow_pico_id:
            raise ValidationError('Cannot create Pico Workflow without an "id" in response.')

        # find or create workflow
        workflow = self.search([('pico_id', '=', workflow_pico_id)], limit=1)
        if not workflow:
            workflow = self.create(self._get_values_from_pico_data(workflow_data))

        # reconcile versions
        workflow._reconcile_versions(version_id)

        # reconcile processes
        processes = workflow_data.get('processes', [])
        workflow._reconcile_processes(processes)

        # validate all BoMs
        workflow.validate_bom_setup()
        return workflow

    def _get_values_from_pico_data(self, values):
        return {
            'name': values.get('name', ''),
            'pico_id': values['id'],
        }

    def _reconcile_versions(self, version_id):
        # commands to write on version_ids
        line_commands = []

        existing_versions = self.version_ids.filtered(lambda v: v.pico_id == version_id)

        # versions to archive (missing from current state)
        versions_to_archive = self.version_ids - existing_versions
        line_commands += [(1, v.id, {'active': False}) for v in versions_to_archive]

        # create new versions that are missing
        if not existing_versions:
            line_commands.append((0, 0, {'pico_id': version_id}))

        if line_commands:
            self.write({'version_ids': line_commands})

    def _reconcile_processes(self, process_list):
        # commands to write on process_ids
        line_commands = []
        # pre-process for easy reconcile
        process_dict = {p['id']: (i, p) for i, p in enumerate(process_list, 1)}

        original_processes = self.process_ids
        # all of our external pico_ids
        original_process_pico_ids = original_processes.mapped('pico_id')
        # processes that need updated
        existing_processes = original_processes.filtered(lambda p: p.pico_id in process_dict)
        for p in existing_processes:
            new_vals = {}
            sequence, process_vals = process_dict[p.pico_id]
            if p.name != process_vals.get('name', ''):
                new_vals['name'] = process_vals.get('name', '')
            if sequence != p.sequence:
                new_vals['sequence'] = sequence
            attr_commands = self._reconcile_process_attrs(p, process_vals)
            if attr_commands:
                new_vals['attr_ids'] = attr_commands
            if new_vals:
                line_commands.append((1, p.id, new_vals))
        # processes to archive (missing from current state)
        processes_to_archive = original_processes - existing_processes
        line_commands += [(1, p.id, {'active': False}) for p in processes_to_archive]
        # create new processes that are missing
        for p_id, seq_vals in process_dict.items():
            sequence, values = seq_vals
            if p_id not in original_process_pico_ids:
                new_vals = {'pico_id': p_id, 'name': values.get('name', ''), 'sequence': sequence}
                attr_commands = self._reconcile_process_attrs(None, values)
                if attr_commands:
                    new_vals['attr_ids'] = attr_commands
                line_commands.append((0, 0, new_vals))

        if line_commands:
            self.write({'process_ids': line_commands})
            # propagate producing_process_id
            # we only need to do this if we were going to create or otherwise write to processes
            line_commands = []
            pico_producing = self.process_ids.browse()  # Empty record to use .id == False
            for process in self.process_ids.sorted(lambda p: -p.sequence):  # Essentially reversed()
                if process.attr_ids.filtered(lambda a: a.type == 'produce'):
                    # this process itself produces
                    if process.producing_process_id:
                        line_commands.append((1, process.id, {'producing_process_id': False}))
                    pico_producing = process
                else:
                    if process.producing_process_id != pico_producing:
                        line_commands.append((1, process.id, {'producing_process_id': pico_producing.id}))
            if line_commands:
                self.write({'process_ids': line_commands})

    def _reconcile_process_attrs(self, odoo_process, process):
        line_commands = []
        attrs_dict = {a['id']: a for a in process.get('attrs', [])}
        original_attrs = odoo_process and odoo_process.attr_ids or self.env['pico.workflow.process.attr']
        original_pico_ids = original_attrs.mapped('pico_id')
        # update existing attrs
        existing_attrs = original_attrs.filtered(lambda a: a.pico_id in attrs_dict)
        for a in existing_attrs:
            new_vals = {}
            if a.name != attrs_dict[a.pico_id].get('label', ''):
                new_vals['name'] = attrs_dict[a.pico_id].get('label', '')
            if process.get('produced_attr_id') == a.pico_id and a.type != 'produce':
                new_vals['type'] = 'produce'
            if a.pico_id in process.get('consumed_attr_ids', []) and a.type != 'consume':
                new_vals['type'] = 'consume'
            if new_vals:
                line_commands.append((1, a.id, new_vals))
        # unlink any non existing attrs
        attrs_to_unlink = original_attrs - existing_attrs
        line_commands += [(3, a.id, 0) for a in attrs_to_unlink]
        # create new attrs
        for a_id, values in attrs_dict.items():
            if a_id not in original_pico_ids:
                vals = {'name': values.get('label', ''), 'pico_id': a_id}
                if process.get('produced_attr_id') == a_id:
                    vals['type'] = 'produce'
                elif a_id in process.get('consumed_attr_ids', []):
                    vals['type'] = 'consume'
                line_commands.append((0, 0, vals))
        return line_commands


class PicoMESProcess(models.Model):
    _name = 'pico.workflow.process'
    _description = 'Process'
    _order = 'workflow_id, sequence'

    active = fields.Boolean(default=True)
    name = fields.Char("Name")
    pico_id = fields.Char("Process ID")
    attr_ids = fields.One2many('pico.workflow.process.attr', 'process_id', string='Attrs')
    sequence = fields.Integer("Sequence", default=1)
    producing_process_id = fields.Many2one('pico.workflow.process', string='Producing Process')

    workflow_id = fields.Many2one('pico.workflow', string='Parent Workflow')

    process_ids = fields.One2many('pico.workflow.process', string='Related Processes',
                                  compute='_compute_process_ids')

    @api.depends('workflow_id.process_ids.producing_process_id')
    def _compute_process_ids(self):
        for process in self:
            process.process_ids = process.workflow_id.process_ids.filtered(lambda p:
                                                                           p == process
                                                                           or p.producing_process_id == process)


class PicoMESProcessAttr(models.Model):
    _name = 'pico.workflow.process.attr'
    _description = 'Process Attr'

    process_id = fields.Many2one('pico.workflow.process')
    type = fields.Selection([
        ('produce', 'Produce'),
        ('consume', 'Consume'),
        ('other', 'Other'),
    ], string='Type', default='other')
    name = fields.Char("Name")
    pico_id = fields.Char("Attr ID")


class PicoMESVersion(models.Model):
    _name = 'pico.workflow.version'
    _description = 'Version'
    _rec_name = 'pico_id'

    active = fields.Boolean(default=True)
    pico_id = fields.Char()

    workflow_id = fields.Many2one('pico.workflow', string='Parent Workflow')
