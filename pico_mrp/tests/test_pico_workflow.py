from contextlib import contextmanager
from datetime import datetime
from collections import defaultdict
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

        # get product with known bom
        self.product = self.env.ref('mrp.product_product_wood_panel')
        self.product.tracking = 'serial'
        for line in self.product.bom_ids.bom_line_ids:
            line.product_id.tracking = 'serial'

        self.bom_activity = self.env.ref('pico_mrp.mail_activity_type_bom_map_needed')
        self.workflow_activities = defaultdict(lambda: self.env['mail.activity'].browse())

    def _product_add_workflow(self, workflow):
        # Assumes single process...
        self.product.bom_ids.pico_process_id = workflow.process_ids
        # consume all of the lines when this process completes
        self.product.bom_ids.bom_line_ids.write({
            'pico_process_id': workflow.process_ids.id,
            'pico_attr_id': workflow.process_ids.attr_ids.filtered(lambda a: a.type == 'consume').id,
        })

    def _new_workflow_activities(self, workflow):
        activities = self.env['mail.activity'].search([
            ('activity_type_id', '=', self.bom_activity.id),
            ('res_model_id', '=', self.env.ref('mrp.model_mrp_bom').id),
            ('res_id', 'not in', self.workflow_activities[workflow].ids),
        ])
        self.workflow_activities[workflow] += activities
        return activities

    def test_creation(self):
        workflow = self.env['pico.workflow'].with_user(self.admin_user).create({
            'name': 'Test Flow',
            'pico_id': 'w156'
        })
        workflow.write({
            'process_ids': [(0, 0, {
                'name': 'Test Process',
                'pico_id': '370',
                'workflow_id': workflow.id,
                'attr_ids': [
                    (0, 0, {'pico_id': 'a101', 'name': 'A 101', 'type': 'produce'}),
                    (0, 0, {'pico_id': 'a102', 'name': 'A 102', 'type': 'consume'}),
                ],
            })],
            'version_ids': [(0, 0, {
                'pico_id': 'v12',
                'workflow_id': workflow.id
            })],
        })

        self.assertEqual(workflow.name, "Test Flow", "Expected to have created a workflow")
        self.assertEqual(len(workflow.process_ids), 1, "Expected to have one process")
        self.assertEqual(workflow.process_ids.pico_id, '370', "Expected process to have same pico_id")
        self.assertEqual(len(workflow.process_ids.attr_ids), 2, "Expected to have 2 process attrs.")
        self.assertEqual(workflow.process_ids.attr_ids.filtered(lambda a: a.type == 'produce').name, 'A 101')
        self.assertEqual(workflow.process_ids.attr_ids.filtered(lambda a: a.type == 'consume').name, 'A 102')

    def test_sync_data_add(self):
        # use new workflow process on BoM
        self.assertFalse(self.product.bom_ids.pico_workflow_id.pico_id, "Expect no Pico Workflow set")

        response_data = {
            "id": "v12",
            "workflow": {
                "id": "w156",
                "name": "Test Flow",
                "processes": [{
                    "id": "p18",
                    "name": "test process",
                    'attrs': [
                        {'id': 'a101', 'label': 'A 101'},
                        {'id': 'a102', 'label': 'A 102'},
                    ],
                    'produced_attr_id': 'a101',
                    'consumed_attr_ids': [
                        'a102',
                    ],
                }]
            }
        }
        workflow = self.env['pico.workflow'].process_pico_data(response_data)
        self.assertEqual(len(workflow.version_ids), 1, "Expected to have one version")
        self.assertEqual(workflow.version_ids.pico_id, 'v12', "Expected version to be equal")
        self.assertEqual(len(workflow.process_ids), 1, "Expected to have one process")
        self.assertEqual(workflow.process_ids.pico_id, 'p18', "Expected process to be equal")
        self.assertEqual(len(workflow.process_ids.attr_ids), 2, "Expected to have 2 process attrs.")
        self.assertEqual(workflow.process_ids.attr_ids.filtered(lambda a: a.type == 'produce').name, 'A 101')
        self.assertEqual(workflow.process_ids.attr_ids.filtered(lambda a: a.type == 'consume').name, 'A 102')

        # Add workflow to product's BoM
        # Should be 'valid' already, so no activity should have been created.
        self._product_add_workflow(workflow)
        workflow.validate_bom_setup()
        activities = self._new_workflow_activities(workflow)
        self.assertFalse(activities)


        # The new p19 should ultimately go into the p18 production or have 'producing_process_id' == p18
        response_data["workflow"]["processes"].insert(0, {'id': 'p19'})
        workflow = self.env['pico.workflow'].process_pico_data(response_data)
        self.assertEqual(len(workflow.version_ids), 1, "Expected to have one version")
        self.assertEqual(workflow.version_ids.pico_id, 'v12', "Expected version to be equal")
        self.assertEqual(len(workflow.process_ids), 2, "Expected to have two processes")
        # normally, the order comes from the sequence, but we need to order it intentionally
        # because they are ordered when selected from the database, not when inserted....
        processes = workflow.process_ids.sorted(lambda p: p.sequence)
        p0 = processes[0]
        p1 = processes[1]
        self.assertEqual(p0.pico_id, 'p19')
        self.assertEqual(p0.producing_process_id, p1)
        self.assertEqual(p1.pico_id, 'p18')
        self.assertFalse(p1.producing_process_id)
        self.assertEqual(len(workflow.process_ids.attr_ids), 2, "Expected to have 2 process attrs.")
        self.assertEqual(workflow.process_ids.attr_ids.filtered(lambda a: a.type == 'produce').name, 'A 101')
        self.assertEqual(workflow.process_ids.attr_ids.filtered(lambda a: a.type == 'consume').name, 'A 102')

        # This change added a process, but should not have invalidated this BoM
        workflow.validate_bom_setup()
        activities = self._new_workflow_activities(workflow)
        self.assertFalse(activities)

        del response_data["workflow"]["processes"][1]
        workflow = self.env['pico.workflow'].process_pico_data(response_data)
        self.assertEqual(len(workflow.version_ids), 1, "Expected to have one version")
        self.assertEqual(workflow.version_ids.pico_id, 'v12', "Expected version to be equal")
        self.assertEqual(len(workflow.process_ids), 1, "Expected to have one process")
        self.assertEqual(workflow.process_ids.pico_id, 'p19', "Expected process to be equal")

        # This deleted (archived) the original process, therefor the BoM is now invalid
        workflow.validate_bom_setup()
        activities = self._new_workflow_activities(workflow)
        self.assertTrue(activities)

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
        self.assertFalse(self.product.bom_ids.pico_workflow_id.pico_id, "Expect no Pico Workflow set")

        workflow = self.env['pico.workflow'].with_user(self.admin_user).create({
            'name': 'Test Flow',
            'pico_id': 'w156'
        })
        workflow.write({
            'process_ids': [(0, 0, {
                'name': 'Test Process',
                'pico_id': '370',
                'attr_ids': [
                    (0, 0, {'pico_id': 'a1', 'name': 'A1', 'type': 'produce'}),
                    (0, 0, {'pico_id': 'a2', 'name': 'A2', 'type': 'consume'}),
                ]
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

        self._product_add_workflow(workflow)
        self.assertEqual(self.product.bom_ids.pico_process_id.pico_id, "370", "Expect Pico Process set")

        mo = self.env['mrp.production'].create({
            'product_id': self.product.id,
            'bom_id': self.product.bom_ids.id,
            'product_uom_id': self.product.uom_id.id,
        })
        self.assertEqual(mo.state, "draft")
        # we have 1 inactive and 1 active version, but we will have pre-assigned the active one
        self.assertEqual(mo.pico_process_id, workflow.process_ids)

        mo._onchange_move_raw()
        with self.mock_with_delay() as (delayable_cls, delayable):
            mo.action_confirm()
        self.assertEqual(mo.state, "confirmed", "Expect mo to be in confirm state")
        # process created pico work order(s)
        self.assertTrue(mo.pico_work_order_ids)
        self.assertTrue(mo.pico_work_order_ids.state, 'running')  # only because we are not queueing it

        # simulate complete
        mo.pico_work_order_ids.with_context(skip_queue_job=True).pico_complete({
            "id": "string",
            "attributes": [
                # Finished Serial
                {
                    "id": "a1",
                    "label": "A1",
                    "value": "F101",
                },
                # Consumed Serial
                {
                    "id": "a2",
                    "label": "A2",
                    "value": "C101",
                },
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
        self.assertEqual(mo.finished_move_line_ids.lot_id.name, 'F101')
        # self.assertEqual(mo.move_raw_ids.mapped('move_line_ids.lot_id.name'), 'C101')
