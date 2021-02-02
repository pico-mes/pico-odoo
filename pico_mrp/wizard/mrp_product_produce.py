from odoo import models


class MrpProductProduce(models.TransientModel):
    _inherit = "mrp.product.produce"

    """
    Copy from mrp_subcontracting
    The 'new' lines are not accessible even via manually calling onchange for producing qty.
    """

    def _generate_produce_lines(self):
        """ When the wizard is called in backend, the onchange that create the
        produce lines is not trigger. This method generate them and is used with
        _record_production to appropriately set the lot_produced_id and
        appropriately create raw stock move lines.
        """
        line_values = []
        for wizard in self:
            moves = (wizard.move_raw_ids | wizard.move_finished_ids).filtered(
                lambda move: move.state not in ("done", "cancel")
            )
            for move in moves:
                qty_to_consume = wizard._prepare_component_quantity(
                    move, wizard.qty_producing
                )
                vals = wizard._generate_lines_values(move, qty_to_consume)
                line_values += vals
        self.env["mrp.product.produce.line"].create(line_values)
