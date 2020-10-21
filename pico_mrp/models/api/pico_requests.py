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

    def subscribe(self, new_workflow_version_url, work_complete_url):
        body = {'newWorkflowVersionUrl': new_workflow_version_url, 'workCompleteUrl': work_complete_url}
        return self.post_request('/subscribe', body)

    def create_work_order(self, process_id, workflow_version_id, annotation=''):
        body = {"processId": process_id, 'workflowVersionId': workflow_version_id, 'annotation': annotation}
        return self.post_request('/work_orders', body)
