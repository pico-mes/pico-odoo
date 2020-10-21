import json

from odoo import http


class PicoMESController(http.Controller):
    """Webhooks for callbacks from pico mes request api"""

    @http.route('/picoapi/new-workflow-version', methods=['POST'], auth='user')
    def new_workflow_version_url(self, new_workflow_version_url):
        data = json.loads(new_workflow_version_url)
        http.request.env['pico.workflow'].process_pico_data(data)

    @http.route('/picoapi/work-complete', methods=['POST'], auth='user')
    def work_complete_url(self, work_complete_url):
        pass
