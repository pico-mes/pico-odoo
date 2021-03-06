import requests
from requests.exceptions import ConnectionError, HTTPError, InvalidSchema
from json import dumps


class PicoMESRequest:
    def __init__(self, url, customer_key):
        self.url = url
        self.headers = {
            "Content-Type": "application/json",
            'Accept': 'application/json',
        }
        if customer_key:
            self.headers['x-pico-api-org'] = customer_key

    def post_request(self, endpoint, body):
        url = self.url + endpoint
        result = requests.post(url, headers=self.headers, data=dumps(body))
        result.raise_for_status()
        return result.json()

    def delete_request(self, endpoint):
        url = self.url + endpoint
        result = requests.delete(url, headers=self.headers)
        result.raise_for_status()

    def subscribe_jsonrpc(self, endpoint_url, new_workflow_version_method, work_order_complete_method):
        body = {
            'rpcHostUrl': endpoint_url,
            'newWorkflowVersionMethod': new_workflow_version_method,
            'workOrderCompleteMethod': work_order_complete_method,
        }
        return self.post_request('/subscribe_jsonrpc', body)

    def create_work_order(self, process_id, workflow_version_id, annotation=''):
        body = {"processId": process_id, 'workflowVersionId': workflow_version_id, 'annotation': annotation}
        return self.post_request('/work_orders', body)

    def delete_work_order(self, work_order_id):
        return self.delete_request('/work_orders/' + work_order_id)
