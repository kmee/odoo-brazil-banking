# -*- coding: utf-8 -*-
# Copyright 2016 KMEE - Luiz Felipe do Divino <luiz.divino@kmee.com.br>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from __future__ import with_statement, unicode_literals

import logging

from openerp import api
from openerp.addons.report_py3o.py3o_parser import py3o_report_extender

_logger = logging.getLogger(__name__)
try:
    from pybrasil import valor, data

except ImportError:
    _logger.info('Cannot import pybrasil')


@api.cr_uid_id_context
@py3o_report_extender('l10n_br_financial_payment_order.py3o_gps')
def extender_gps(pool, cr, uid, local_context, context):

    if local_context.get('active_id'):

        gps = pool['financial.move'].\
            gera_gps(cr, uid, local_context.get('active_ids'))

        vals = {'gps': [gps]}
        local_context.update(vals)
