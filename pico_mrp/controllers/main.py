from odoo import http

from logging import getLogger
_logger = getLogger(__name__)

class PicoMESController(http.Controller):
    """Webhooks for callbacks from pico mes request api"""

    @http.route('/picoapi/webhook', methods=['POST'], type='json', auth='public')
    def picoapi_webhook(self, **data):
        jsonrequest = http.request.jsonrequest
        id = data.get('id')
        if not id or len(id) < 14:
            return

        method = jsonrequest.get('method')
        if method == 'newWorkflowVersionMethod':
            http.request.env['pico.workflow'].sudo().process_pico_data(data)
        elif method == 'workOrderCompleteMethod':
            _logger.info(data)
            http.request.env['mrp.production.pico.work.order'].sudo().pico_complete(data)
        else:
            raise Exception('Invalid method called. (01)')
