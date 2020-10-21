from odoo import api, models, fields
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
            api.subscribe(base_url + '/picoapi/new-workflow-version', base_url + '/picoapi/work-complete')
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
        process_dict = {p['id']: p for p in process_list}

        original_processes = self.process_ids
        # all of our external pico_ids
        original_process_pico_ids = original_processes.mapped('pico_id')
        # processes that need updated
        existing_processes = original_processes.filtered(lambda p: p.pico_id in process_dict)
        for p in existing_processes:
            if p.name != process_dict[p.pico_id].get('name', ''):
                line_commands.append((1, p.id, {'name': process_dict[p.pico_id].get('name', '')}))
        # processes to archive (missing from current state)
        processes_to_archive = original_processes - existing_processes
        line_commands += [(1, p.id, {'active': False}) for p in processes_to_archive]
        # create new processes that are missing
        for p_id, values in process_dict.items():
            if p_id not in original_process_pico_ids:
                line_commands.append((0, 0, {'pico_id': p_id, 'name': values.get('name', '')}))

        if line_commands:
            self.write({'process_ids': line_commands})


class PicoMESProcess(models.Model):
    _name = 'pico.workflow.process'
    _description = 'Process'

    active = fields.Boolean(default=True)
    name = fields.Char("Name")
    pico_id = fields.Char("Process ID")

    workflow_id = fields.Many2one('pico.workflow', string='Parent Workflow')


class PicoMESVersion(models.Model):
    _name = 'pico.workflow.version'
    _description = 'Version'
    _rec_name = 'pico_id'

    active = fields.Boolean(default=True)
    pico_id = fields.Char()

    workflow_id = fields.Many2one('pico.workflow', string='Parent Workflow')
