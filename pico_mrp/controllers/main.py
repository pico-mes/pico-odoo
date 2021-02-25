from odoo import http


class PicoMESController(http.Controller):
    """Webhooks for callbacks from pico mes request api"""

    @http.route('/picoapi/webhook', methods=['POST'], type='json', auth='public')
    def picoapi_webhook(self, **data):
        jsonrequest = http.request.jsonrequest
        id = data.get('id')
        if not id or len(id) < 14:
            return http.Response('Invalid Request. ID Length incorrect', status=400)

        method = jsonrequest.get('method')
        if method == 'newWorkflowVersionMethod':
            http.request.env['pico.workflow'].sudo().process_pico_data(data)
            return http.Response('Workflow version acknowledged', status=200)
        elif method == 'workOrderCompleteMethod':
            http.request.env['mrp.production.pico.work.order'].sudo().pico_complete(data)
            return http.Response('Work order complete acknowledged', status=200)
        return http.Response('Invalid method called. (01)', status=400)
