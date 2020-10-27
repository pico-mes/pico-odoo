from contextlib import contextmanager
from datetime import datetime
import mock

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError
from odoo.addons.pico_mrp.models.api import pico_requests
from odoo.addons.pico_mrp.models.pico_workflow import pico_api

from logging import getLogger
_logger = getLogger(__name__)


class TestWorkflow(TransactionCase):
    @contextmanager
    def mock_with_delay(self):
        with mock.patch('odoo.addons.queue_job.models.base.DelayableRecordset',
                        name='DelayableRecordset', spec=True
                        ) as delayable_cls:
            # prepare the mocks
            delayable = mock.MagicMock(name='DelayableBinding')
            delayable_cls.return_value = delayable
            yield delayable_cls, delayable

    def setUp(self):
        super().setUp()
        self.admin_user = self.env.ref('base.user_admin')

        def subscribe_jsonrpc(self, endpoint_url, new_workflow_version_method, work_order_complete_method):
            _logger.warn('called subscribe_jsonrpc %s' % ([endpoint_url, new_workflow_version_method, work_order_complete_method],))
            return {}

        def create_work_order(self, process_id, workflow_version_id, annotation=''):
            _logger.warn('called create_work_order %s' % ([process_id, workflow_version_id, annotation], ))
            return {'id': str(process_id) + str(workflow_version_id) + str(annotation)}

        pico_requests.PicoMESRequest.subscribe_jsonrpc = subscribe_jsonrpc
        pico_requests.PicoMESRequest.create_work_order = create_work_order

        parameters = self.env['ir.config_parameter'].sudo()
        parameters.set_param('pico.url', 'http://test:9000')

    def test_creation(self):
        workflow = self.env['pico.workflow'].with_user(self.admin_user).create({
            'name': 'Test Flow',
            'pico_id': 'w156'
        })
        workflow.write({
            'process_ids': [(0, 0, {
                'name': 'Test Process',
                'pico_id': '370',
                'workflow_id': workflow.id
            })],
            'version_ids': [(0, 0, {
                'pico_id': 'v12',
                'workflow_id': workflow.id
            })],
        })

        self.assertEqual(workflow.name, "Test Flow", "Expected to have created a workflow")
        self.assertEqual(len(workflow.process_ids), 1, "Expected to have one process")
        self.assertEqual(workflow.process_ids.pico_id, '370', "Expected process to have same pico_id")

    def test_sync_data_add(self):
        response_data = {
            "id": "v12",
            "workflow": {
                "id": "w156",
                "name": "Test Flow",
                "processes": [{
                    "id": "p18",
                    "name": "test process"
                }]
            }
        }
        workflow = self.env['pico.workflow'].process_pico_data(response_data)
        self.assertEqual(len(workflow.version_ids), 1, "Expected to have one version")
        self.assertEqual(workflow.version_ids.pico_id, 'v12', "Expected version to be equal")
        self.assertEqual(len(workflow.process_ids), 1, "Expected to have one process")
        self.assertEqual(workflow.process_ids.pico_id, 'p18', "Expected process to be equal")

        response_data["workflow"]["processes"].append({'id': 'p19'})
        workflow = self.env['pico.workflow'].process_pico_data(response_data)
        self.assertEqual(len(workflow.version_ids), 1, "Expected to have one version")
        self.assertEqual(workflow.version_ids.pico_id, 'v12', "Expected version to be equal")
        self.assertEqual(len(workflow.process_ids), 2, "Expected to have two processes")

        del response_data["workflow"]["processes"][0]
        workflow = self.env['pico.workflow'].process_pico_data(response_data)
        self.assertEqual(len(workflow.version_ids), 1, "Expected to have one version")
        self.assertEqual(workflow.version_ids.pico_id, 'v12', "Expected version to be equal")
        self.assertEqual(len(workflow.process_ids), 1, "Expected to have one process")
        self.assertEqual(workflow.process_ids.pico_id, 'p19', "Expected process to be equal")

        response_data["workflow"]["processes"] = [{'id': 'p20'}, {'id': 'p21'}, {'id': 'p22'}, {'id': 'p23'}]
        workflow = self.env['pico.workflow'].process_pico_data(response_data)
        self.assertEqual(len(workflow.version_ids), 1, "Expected to have one version")
        self.assertEqual(workflow.version_ids.pico_id, 'v12', "Expected version to be equal")
        self.assertEqual(len(workflow.process_ids), 4, "Expected to have four processes")

        response_data["id"] = "v13"
        workflow = self.env['pico.workflow'].process_pico_data(response_data)
        self.assertEqual(len(workflow.version_ids), 1, "Expected to have one versions")
        self.assertEqual(workflow.version_ids.pico_id, 'v13', "Expected version to be equal")
        self.assertEqual(len(workflow.process_ids), 4, "Expected to have four processes")

    def test_pico_api(self):
        parameters = self.env['ir.config_parameter'].sudo()
        parameters.set_param('pico.url', None)
        with self.assertRaises(ValidationError):
            pico_api(self.env)
        parameters.set_param('pico.url', 'http://test:9000')
        api = pico_api(self.env)
        res = api.create_work_order('test', 'test')
        self.assertTrue(isinstance(res, dict))

    def test_mrp(self):
        # get product with known bom
        product = self.env.ref('mrp.product_product_wood_panel')
        # TODO handle serials
        product.tracking = 'none'
        for line in product.bom_ids.bom_line_ids:
            line.product_id.tracking = 'none'

        self.assertFalse(product.bom_ids.pico_workflow_id.pico_id, "Expect no Pico Workflow set")

        workflow = self.env['pico.workflow'].with_user(self.admin_user).create({
            'name': 'Test Flow',
            'pico_id': 'w156'
        })
        workflow.write({
            'process_ids': [(0, 0, {
                'name': 'Test Process',
                'pico_id': '370',
            })],
            'version_ids': [(0, 0, {
                'pico_id': 'v12',
            })],
        })

        v11 = workflow.version_ids.create({
            'active': False,
            'pico_id': 'v11',
            'workflow_id': workflow.id,
        })

        product.bom_ids.pico_workflow_id = workflow
        # consume all of the lines when this process completes
        product.bom_ids.bom_line_ids.write({
            'pico_process_id': workflow.process_ids.id,
        })
        self.assertEqual(product.bom_ids.pico_workflow_id.pico_id, "w156", "Expect Pico Workflow set")

        mo = self.env['mrp.production'].create({
            'product_id': product.id,
            'bom_id': product.bom_ids.id,
            'product_uom_id': product.uom_id.id,
        })
        self.assertEqual(mo.state, "draft")
        # we have 1 inactive and 1 active version, but we will have pre-assigned the active one
        self.assertEqual(mo.pico_workflow_version_id, workflow.version_ids)
        # assigning inactive to pretend that this MO 'found' the other one before it was inactive
        mo.pico_workflow_version_id = v11
        with self.assertRaises(UserError):
            # not allowed to start a MO with an inactive version
            mo.action_confirm()
        # assign the active version
        mo.pico_workflow_version_id = workflow.version_ids

        mo._onchange_move_raw()
        with self.mock_with_delay() as (delayable_cls, delayable):
            mo.action_confirm()
        self.assertEqual(mo.state, "confirmed", "Expect mo to be in confirm state")
        # process created pico work order(s)
        self.assertTrue(mo.pico_work_order_ids)
        self.assertTrue(mo.pico_work_order_ids.state, 'running')  # only because we are not queueing it

        # simulate complete
        mo.pico_work_order_ids.pico_complete({
            "id": "string",
            "attributes": [
                {
                    "id": "string",
                    "label": "string",
                    "value": "string"
                }
            ],
            "startedAt": "2020-10-01T10:40:50.043Z",
            "completedAt": "2020-10-02T10:40:50.043Z",
            "cycleTime": 0,
            "workflowId": "string",
            "processId": "string",
            "workOrderId": "string"
        })

        self.assertEqual(mo.pico_work_order_ids.state, 'done')
        self.assertEqual(mo.pico_work_order_ids.date_start, datetime(2020, 10, 1, 10, 40, 50))
        self.assertEqual(mo.pico_work_order_ids.date_complete, datetime(2020, 10, 2, 10, 40, 50))
        for sm in mo.move_raw_ids:
            self.assertEqual(sm.quantity_done, sm.product_uom_qty)
        self.assertEqual(mo.state, 'done')
