# -*- coding: utf-8 -*-
# Copyright (C) 2013 Therp BV (<http://therp.nl>).
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
{
    "name": "Delete all company data",
    "version": "10.0.1.0.0",
    "author": "Ermanno Gnan, Odoo Community Association (OCA)",
    "license": "AGPL-3",
    "category": "base",
    "depends": [
        'base',
        'mail',
    ],
    "data": [
        'views/delete_all_company_data_wizard_view.xml',
        'views/menu.xml',
    ],
    "qweb": [
    ],
    'installable': True,
}
