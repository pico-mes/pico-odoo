import requests
from json import dumps


class PicoMESRequest:
    def __init__(self, url):
        self.url = url
        self.headers = {"Content-Type": "application/json"}

    def post_request(self, endpoint, body):
        url = self.url + endpoint
        result = requests.request('POST', url, headers=self.headers, data=dumps(body))
        if result.status_code == result.codes.ok:
            result.raise_for_status()
        return result.json()

    def subscribe(self, new_workflow_version_url, work_complete_url):
        body = {'newWorkflowVersionUrl': new_workflow_version_url, 'workCompleteUrl': work_complete_url}
        return self.post_request('/subscribe', body)

    def create_work_order(self, process_id, workflow_version_id, annotation=''):
        body = {"processId": process_id, 'workflowVersionId': workflow_version_id, 'annotation': annotation}
        return self.post_request('/work_orders', body)
