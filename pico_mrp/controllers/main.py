from odoo import http


class PicoMESController(http.Controller):
    """Webhooks for callbacks from pico mes request api"""

    @http.route('/picoapi/new-workflow-version', methods=['POST'], type='json', auth='public')
    def new_workflow_version_url(self, **data):
        if data:
            http.request.env['pico.workflow'].sudo().process_pico_data(data)

    @http.route('/picoapi/work-complete', methods=['POST'], type='json', auth='public')
    def work_complete_url(self, **data):
        pass
