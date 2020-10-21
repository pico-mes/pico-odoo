from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError
from odoo.addons.pico_mrp.models.api import pico_requests
from odoo.addons.pico_mrp.models.pico_workflow import pico_api

from logging import getLogger
_logger = getLogger(__name__)


class TestWorkflow(TransactionCase):
    def setUp(self):
        super().setUp()
        self.admin_user = self.env.ref('base.user_admin')

        def subscribe(*args, **kwargs):
            _logger.warn('called subscribe args: %s kwargs: %s' % (args, kwargs))
            return {}

        def create_work_order(*args, **kwargs):
            _logger.warn('called create_work_order args: %s kwargs: %s' % (args, kwargs))
            return {}
        pico_requests.PicoMESRequest.subscribe = subscribe
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
        res = api.create_work_order('test')
        self.assertTrue(isinstance(res, dict))

    def test_mrp(self):
        # get product with known bom
        product = self.env.ref('mrp.product_product_wood_panel_product_template')
        self.assertFalse(product.bom_ids.pico_workflow_id.pico_id, "Expect no Pico Workflow set")

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
        product.bom_ids.pico_workflow_id = workflow.id
        self.assertEqual(product.bom_ids.pico_workflow_id.pico_id, "w156", "Expect Pico Workflow set")

        mo = self.env['mrp.production'].create({
            'product_id': product.id,
            'bom_id': product.bom_ids.id,
            'product_uom_id': product.uom_id.id,
        })
        self.assertEqual(mo.state, "draft")

        mo._onchange_move_raw()
        mo.action_confirm()
        self.assertEqual(mo.state, "confirmed", "Expect mo to be in confirm state")
