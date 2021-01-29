from datetime import datetime
from collections import defaultdict

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError
from odoo.addons.pico_mrp.models.api import pico_requests
from odoo.addons.pico_mrp.models.pico_workflow import pico_api

from logging import getLogger

_logger = getLogger(__name__)


class TestWorkflow(TransactionCase):
    def setUp(self):
        super().setUp()
        self.admin_user = self.env.ref("base.user_admin")

        def subscribe_jsonrpc(
            self, endpoint_url, new_workflow_version_method, work_order_complete_method
        ):
            _logger.warn(
                "called subscribe_jsonrpc %s"
                % (
                    [
                        endpoint_url,
                        new_workflow_version_method,
                        work_order_complete_method,
                    ],
                )
            )
            return {}

        def create_work_order(self, process_id, workflow_version_id, annotation=""):
            _logger.warn(
                "called create_work_order %s"
                % ([process_id, workflow_version_id, annotation],)
            )
            return {"id": str(process_id) + str(workflow_version_id) + str(annotation)}

        def delete_work_order(self, work_order_id):
            _logger.warn("called delete_work_order %s" % (work_order_id,))

        pico_requests.PicoMESRequest.subscribe_jsonrpc = subscribe_jsonrpc
        pico_requests.PicoMESRequest.create_work_order = create_work_order
        pico_requests.PicoMESRequest.delete_work_order = delete_work_order

        parameters = self.env["ir.config_parameter"].sudo()
        parameters.set_param("pico.url", "http://test:9000")

        # get product with known bom
        self.product = self.env.ref("mrp.product_product_wood_panel")
        self.product.tracking = "serial"
        for line in self.product.bom_ids.bom_line_ids:
            # Note that serial should be possible, but would require more produce setup because this
            # product was procured and it will not be able to update the history with serial.
            line.product_id.tracking = "lot"
        self.product.bom_ids.bom_line_ids[1:].unlink()

        self.bom_activity = self.env.ref("pico_mrp.mail_activity_type_bom_map_needed")
        self.workflow_activities = defaultdict(
            lambda: self.env["mail.activity"].browse()
        )

    def _product_add_workflow(self, workflow):
        # Assumes single process...
        produce_process = workflow.process_ids.filtered(
            lambda p: p.attr_ids.filtered(lambda a: a.type == "produce")
        )
        self.assertTrue(produce_process)
        self.assertEqual(len(produce_process), 1)
        self.product.bom_ids.pico_process_id = produce_process
        consume_process = workflow.process_ids.filtered(
            lambda p: p.attr_ids.filtered(lambda a: a.type == "consume")
        )
        self.assertTrue(consume_process)
        self.assertEqual(len(consume_process), 1)
        # consume all of the lines when this process completes
        self.product.bom_ids.bom_line_ids.write(
            {
                "pico_process_id": consume_process.id,
                "pico_attr_id": consume_process.attr_ids.filtered(
                    lambda a: a.type == "consume"
                ).id,
                "product_qty": 1.0,
            }
        )

    def _new_workflow_activities(self, workflow):
        activities = self.env["mail.activity"].search(
            [
                ("activity_type_id", "=", self.bom_activity.id),
                ("res_model_id", "=", self.env.ref("mrp.model_mrp_bom").id),
                ("res_id", "not in", self.workflow_activities[workflow].ids),
            ]
        )
        self.workflow_activities[workflow] += activities
        return activities

    def test_creation(self):
        workflow = (
            self.env["pico.workflow"]
            .with_user(self.admin_user)
            .create({"name": "Test Flow", "pico_id": "w156"})
        )
        workflow.write(
            {
                "process_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Test Process",
                            "pico_id": "370",
                            "workflow_id": workflow.id,
                            "attr_ids": [
                                (
                                    0,
                                    0,
                                    {
                                        "pico_id": "a101",
                                        "name": "A 101",
                                        "type": "produce",
                                    },
                                ),
                                (
                                    0,
                                    0,
                                    {
                                        "pico_id": "a102",
                                        "name": "A 102",
                                        "type": "consume",
                                    },
                                ),
                            ],
                        },
                    )
                ],
                "version_ids": [(0, 0, {"pico_id": "v12", "workflow_id": workflow.id})],
            }
        )

        self.assertEqual(
            workflow.name, "Test Flow", "Expected to have created a workflow"
        )
        self.assertEqual(len(workflow.process_ids), 1, "Expected to have one process")
        self.assertEqual(
            workflow.process_ids.pico_id, "370", "Expected process to have same pico_id"
        )
        self.assertEqual(
            len(workflow.process_ids.attr_ids), 2, "Expected to have 2 process attrs."
        )
        self.assertEqual(
            workflow.process_ids.attr_ids.filtered(lambda a: a.type == "produce").name,
            "A 101",
        )
        self.assertEqual(
            workflow.process_ids.attr_ids.filtered(lambda a: a.type == "consume").name,
            "A 102",
        )

    def test_sync_data_add(self):
        # use new workflow process on BoM
        self.assertFalse(
            self.product.bom_ids.pico_workflow_id.pico_id, "Expect no Pico Workflow set"
        )

        response_data = {
            "id": "v12",
            "workflow": {
                "id": "w156",
                "name": "Test Flow",
                "processes": [
                    {
                        "id": "p18",
                        "name": "test process",
                        "attrs": [
                            {"id": "a101", "label": "A 101"},
                            {"id": "a102", "label": "A 102"},
                        ],
                        "produced_attr_id": "a101",
                        "consumed_attr_ids": ["a102"],
                    }
                ],
            },
        }
        workflow = self.env["pico.workflow"].process_pico_data(response_data)
        self.assertEqual(len(workflow.version_ids), 1, "Expected to have one version")
        self.assertEqual(
            workflow.version_ids.pico_id, "v12", "Expected version to be equal"
        )
        self.assertEqual(len(workflow.process_ids), 1, "Expected to have one process")
        self.assertEqual(
            workflow.process_ids.pico_id, "p18", "Expected process to be equal"
        )
        self.assertEqual(
            len(workflow.process_ids.attr_ids), 2, "Expected to have 2 process attrs."
        )
        self.assertEqual(
            workflow.process_ids.attr_ids.filtered(lambda a: a.type == "produce").name,
            "A 101",
        )
        self.assertEqual(
            workflow.process_ids.attr_ids.filtered(lambda a: a.type == "consume").name,
            "A 102",
        )

        # Add workflow to product's BoM
        # Should be 'valid' already, so no activity should have been created.
        self._product_add_workflow(workflow)
        workflow.validate_bom_setup()
        activities = self._new_workflow_activities(workflow)
        self.assertFalse(activities)

        # The new p19 should ultimately go into the p18 production or have 'producing_process_id' == p18
        response_data["workflow"]["processes"].insert(0, {"id": "p19"})
        workflow = self.env["pico.workflow"].process_pico_data(response_data)
        self.assertEqual(len(workflow.version_ids), 1, "Expected to have one version")
        self.assertEqual(
            workflow.version_ids.pico_id, "v12", "Expected version to be equal"
        )
        self.assertEqual(len(workflow.process_ids), 2, "Expected to have two processes")
        # normally, the order comes from the sequence, but we need to order it intentionally
        # because they are ordered when selected from the database, not when inserted....
        processes = workflow.process_ids.sorted(lambda p: p.sequence)
        p0 = processes[0]
        p1 = processes[1]
        self.assertEqual(p0.pico_id, "p19")
        self.assertEqual(p0.producing_process_id, p1)
        self.assertEqual(p1.pico_id, "p18")
        self.assertFalse(p1.producing_process_id)
        self.assertEqual(
            len(workflow.process_ids.attr_ids), 2, "Expected to have 2 process attrs."
        )
        self.assertEqual(
            workflow.process_ids.attr_ids.filtered(lambda a: a.type == "produce").name,
            "A 101",
        )
        self.assertEqual(
            workflow.process_ids.attr_ids.filtered(lambda a: a.type == "consume").name,
            "A 102",
        )

        # This change added a process, but should not have invalidated this BoM
        workflow.validate_bom_setup()
        activities = self._new_workflow_activities(workflow)
        self.assertFalse(activities)

        del response_data["workflow"]["processes"][1]
        workflow = self.env["pico.workflow"].process_pico_data(response_data)
        self.assertEqual(len(workflow.version_ids), 1, "Expected to have one version")
        self.assertEqual(
            workflow.version_ids.pico_id, "v12", "Expected version to be equal"
        )
        self.assertEqual(len(workflow.process_ids), 1, "Expected to have one process")
        self.assertEqual(
            workflow.process_ids.pico_id, "p19", "Expected process to be equal"
        )

        # This deleted (archived) the original process, therefor the BoM is now invalid
        workflow.validate_bom_setup()
        activities = self._new_workflow_activities(workflow)
        self.assertTrue(activities)

        response_data["workflow"]["processes"] = [
            {"id": "p20"},
            {"id": "p21"},
            {"id": "p22"},
            {"id": "p23"},
        ]
        workflow = self.env["pico.workflow"].process_pico_data(response_data)
        self.assertEqual(len(workflow.version_ids), 1, "Expected to have one version")
        self.assertEqual(
            workflow.version_ids.pico_id, "v12", "Expected version to be equal"
        )
        self.assertEqual(
            len(workflow.process_ids), 4, "Expected to have four processes"
        )

        response_data["id"] = "v13"
        workflow = self.env["pico.workflow"].process_pico_data(response_data)
        self.assertEqual(len(workflow.version_ids), 1, "Expected to have one versions")
        self.assertEqual(
            workflow.version_ids.pico_id, "v13", "Expected version to be equal"
        )
        self.assertEqual(
            len(workflow.process_ids), 4, "Expected to have four processes"
        )

    def test_pico_api(self):
        parameters = self.env["ir.config_parameter"].sudo()
        parameters.set_param("pico.url", None)
        with self.assertRaises(ValidationError):
            pico_api(self.env)
        parameters.set_param("pico.url", "http://test:9000")
        api = pico_api(self.env)
        res = api.create_work_order("test", "test")
        self.assertTrue(isinstance(res, dict))

    def test_mrp(self):
        self.assertFalse(
            self.product.bom_ids.pico_workflow_id.pico_id, "Expect no Pico Workflow set"
        )

        workflow = (
            self.env["pico.workflow"]
            .with_user(self.admin_user)
            .create({"name": "Test Flow", "pico_id": "w156"})
        )
        workflow.write(
            {
                "process_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Test Process",
                            "pico_id": "370",
                            "attr_ids": [
                                (
                                    0,
                                    0,
                                    {"pico_id": "a1", "name": "A1", "type": "produce"},
                                ),
                                (
                                    0,
                                    0,
                                    {"pico_id": "a2", "name": "A2", "type": "consume"},
                                ),
                            ],
                        },
                    )
                ],
                "version_ids": [(0, 0, {"pico_id": "v12"})],
            }
        )

        v11 = workflow.version_ids.create(
            {"active": False, "pico_id": "v11", "workflow_id": workflow.id}
        )

        self._product_add_workflow(workflow)
        self.assertEqual(
            self.product.bom_ids.pico_process_id.pico_id,
            "370",
            "Expect Pico Process set",
        )

        mo = self.env["mrp.production"].create(
            {
                "product_id": self.product.id,
                "bom_id": self.product.bom_ids.id,
                "product_uom_id": self.product.uom_id.id,
            }
        )
        self.assertEqual(mo.state, "draft")
        # we have 1 inactive and 1 active version, but we will have pre-assigned the active one
        self.assertEqual(mo.pico_process_id, workflow.process_ids)

        mo._onchange_move_raw()

        mo.action_confirm()
        self.assertEqual(mo.state, "confirmed", "Expect mo to be in confirm state")
        # process created pico work order(s)
        self.assertTrue(mo.pico_work_order_ids)
        self.assertEqual(len(mo.pico_work_order_ids), 1)
        work_order = mo.pico_work_order_ids
        self.assertEqual(work_order.state, "running")
        self.assertFalse(
            work_order._workorder_should_consume_in_real_time()
        )  # should prefer to consume as 'set' of 1

        # The patched work order create process pattern in setUp()
        self.assertEqual(
            work_order.pico_id,
            "%s%s%s"
            % (
                work_order.process_id.pico_id,
                work_order.process_id.workflow_id.version_ids.pico_id,
                mo.name,
            ),
        )

        # simulate complete
        mo.pico_work_order_ids.pico_complete(
            {
                "id": "string",
                "attributes": [
                    # Finished Serial
                    {"id": "a1", "label": "A1", "value": "F101"},
                    # Consumed Serial
                    {"id": "a2", "label": "A2", "value": "C101"},
                ],
                "startedAt": "2020-10-01T10:40:50.043Z",
                "completedAt": "2020-10-02T10:40:50.043Z",
                "cycleTime": 0,
                "workflowId": "string",
                "processId": "string",
                "workOrderId": "string",
            }
        )

        self.assertEqual(mo.pico_work_order_ids.state, "done")
        self.assertEqual(
            mo.pico_work_order_ids.date_start, datetime(2020, 10, 1, 10, 40, 50)
        )
        self.assertEqual(
            mo.pico_work_order_ids.date_complete, datetime(2020, 10, 2, 10, 40, 50)
        )
        for sm in mo.move_raw_ids:
            self.assertEqual(sm.quantity_done, sm.product_uom_qty)
        self.assertEqual(mo.state, "done")
        self.assertEqual(mo.finished_move_line_ids.lot_id.name, "F101")
        self.assertEqual(mo.move_raw_ids.mapped("move_line_ids.lot_id.name"), ["C101"])

    def test_mrp_multi_process(self, reserve_inventory=False):
        self.assertFalse(
            self.product.bom_ids.pico_workflow_id.pico_id, "Expect no Pico Workflow set"
        )

        workflow = (
            self.env["pico.workflow"]
            .with_user(self.admin_user)
            .create({"name": "Test Flow", "pico_id": "w156"})
        )
        workflow.write(
            {
                "process_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Test Process",
                            "pico_id": "370",
                            "attr_ids": [
                                (
                                    0,
                                    0,
                                    {"pico_id": "a1", "name": "A1", "type": "produce"},
                                )
                            ],
                            "sequence": 2,
                        },
                    )
                ],
                "version_ids": [(0, 0, {"pico_id": "v12"})],
            }
        )
        process2 = workflow.process_ids
        process1 = process2.create(
            {
                "name": "Test Pre-Process",
                "pico_id": "369",
                "attr_ids": [
                    (0, 0, {"pico_id": "a2", "name": "A2", "type": "consume"})
                ],
                "sequence": 1,
                "producing_process_id": process2.id,
                "workflow_id": workflow.id,
            }
        )

        self._product_add_workflow(workflow)
        self.assertEqual(
            self.product.bom_ids.pico_process_id.pico_id,
            "370",
            "Expect Pico Process set",
        )

        mo = self.env["mrp.production"].create(
            {
                "product_id": self.product.id,
                "bom_id": self.product.bom_ids.id,
                "product_uom_id": self.product.uom_id.id,
                "product_qty": 1.0,
            }
        )
        self.assertEqual(mo.state, "draft")
        # we have 1 inactive and 1 active version, but we will have pre-assigned the active one
        self.assertEqual(mo.pico_process_id, workflow.process_ids.sorted("sequence")[1])

        mo._onchange_move_raw()
        mo.action_confirm()
        if reserve_inventory:
            mo.action_assign()
        self.assertEqual(mo.state, "confirmed", "Expect mo to be in confirm state")
        # process created pico work order(s)
        self.assertTrue(mo.pico_work_order_ids)

        work_order1 = mo.pico_work_order_ids.filtered(
            lambda w: w.process_id == process1
        )
        work_order2 = mo.pico_work_order_ids.filtered(
            lambda w: w.process_id == process2
        )
        self.assertTrue(work_order1)
        self.assertTrue(work_order2)
        self.assertEqual(work_order1.state, "running")
        self.assertTrue(work_order2.state, "running")
        self.assertTrue(work_order1._workorder_should_consume_in_real_time())

        # simulate complete of one work order
        work_order1.pico_complete(
            {
                "id": "string",
                "attributes": [
                    # Consumed Serial
                    {"id": "a2", "label": "A2", "value": "C101"}
                ],
                "startedAt": "2020-10-01T10:40:50.043Z",
                "completedAt": "2020-10-02T10:40:50.043Z",
                "cycleTime": 0,
                "workflowId": "string",
                "processId": "string",
                "workOrderId": "string",
            }
        )

        self.assertEqual(work_order1.state, "pending")
        self.assertEqual(work_order1.date_start, datetime(2020, 10, 1, 10, 40, 50))
        self.assertEqual(work_order1.date_complete, datetime(2020, 10, 2, 10, 40, 50))
        self.assertEqual(work_order2.state, "running")

        # because this MO was for 1.0 and all the lot/serial products are 1.0 qty,
        # finishing the first work order should have consumed the materials.
        self.assertEqual(mo.mapped("move_raw_ids.move_line_ids.qty_done"), [1.0])
        self.assertEqual(mo.mapped("move_raw_ids.move_line_ids.lot_id.name"), ["C101"])

        self.assertEqual(mo.state, "confirmed")  # not 'done'

        # simulate completion of second work order
        work_order2.with_context(skip_queue_job=True).pico_complete(
            {
                "id": "string",
                "attributes": [
                    # Finished Serial
                    {"id": "a1", "label": "A1", "value": "F101"}
                ],
                "startedAt": "2020-10-03T10:40:50.043Z",
                "completedAt": "2020-10-04T10:40:50.043Z",
                "cycleTime": 0,
                "workflowId": "string",
                "processId": "string",
                "workOrderId": "string",
            }
        )
        self.assertEqual(work_order1.state, "done")
        self.assertEqual(work_order2.state, "done")
        self.assertEqual(work_order2.date_start, datetime(2020, 10, 3, 10, 40, 50))
        self.assertEqual(work_order2.date_complete, datetime(2020, 10, 4, 10, 40, 50))

        self.assertEqual(mo.state, "done")
        self.assertEqual(
            mo.mapped("move_raw_ids.move_line_ids.qty_done"), [1.0], "We over consumed."
        )
        self.assertEqual(mo.mapped("move_raw_ids.move_line_ids.lot_id.name"), ["C101"])
        self.assertEqual(mo.finished_move_line_ids.lot_id.name, "F101")

    def test_mrp_multi_process_with_reserve(self):
        self.test_mrp_multi_process(reserve_inventory=True)

    def test_mrp_cancel(self):
        self.assertFalse(
            self.product.bom_ids.pico_workflow_id.pico_id, "Expect no Pico Workflow set"
        )

        workflow = (
            self.env["pico.workflow"]
            .with_user(self.admin_user)
            .create({"name": "Test Flow", "pico_id": "w156"})
        )
        workflow.write(
            {
                "process_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Test Process",
                            "pico_id": "370",
                            "attr_ids": [
                                (
                                    0,
                                    0,
                                    {"pico_id": "a1", "name": "A1", "type": "produce"},
                                )
                            ],
                            "sequence": 2,
                        },
                    )
                ],
                "version_ids": [(0, 0, {"pico_id": "v12"})],
            }
        )
        process2 = workflow.process_ids
        process1 = process2.create(
            {
                "name": "Test Pre-Process",
                "pico_id": "369",
                "attr_ids": [
                    (0, 0, {"pico_id": "a2", "name": "A2", "type": "consume"})
                ],
                "sequence": 1,
                "producing_process_id": process2.id,
                "workflow_id": workflow.id,
            }
        )

        self._product_add_workflow(workflow)
        self.assertEqual(
            self.product.bom_ids.pico_process_id.pico_id,
            "370",
            "Expect Pico Process set",
        )

        mo = self.env["mrp.production"].create(
            {
                "product_id": self.product.id,
                "bom_id": self.product.bom_ids.id,
                "product_uom_id": self.product.uom_id.id,
                "product_qty": 1.0,
            }
        )
        self.assertEqual(mo.state, "draft")
        # we have 1 inactive and 1 active version, but we will have pre-assigned the active one
        self.assertEqual(mo.pico_process_id, workflow.process_ids.sorted("sequence")[1])

        mo._onchange_move_raw()
        mo.action_confirm()
        self.assertEqual(mo.state, "confirmed", "Expect mo to be in confirm state")
        # process created pico work order(s)
        self.assertTrue(mo.pico_work_order_ids)

        work_order1 = mo.pico_work_order_ids.filtered(
            lambda w: w.process_id == process1
        )
        work_order2 = mo.pico_work_order_ids.filtered(
            lambda w: w.process_id == process2
        )
        self.assertTrue(work_order1)
        self.assertTrue(work_order2)
        mo.action_cancel()
        self.assertEqual(len(mo.pico_work_order_ids), 0)
