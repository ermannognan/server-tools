# -*- coding: utf-8 -*-
###############################################################################
#    License, author and contributors information in:                         #
#    __manifest__.py file at the root folder of this module.                  #
###############################################################################

import logging
from odoo import api, fields
from odoo.osv import osv
from odoo.exceptions import UserError
from odoo.tools.translate import _

logger = logging.getLogger(__name__)

STATES = [
    ('start', 'Start'),
    ('checked', 'Checked'),
    ('done', 'Done'),
]


class DeleteAllCompanyDataWizard(osv.TransientModel):
    _name = "delete.all.company.data.wizard"

    test = fields.Boolean(string="Test", default=True)
    company_id = fields.Many2one('res.company', 'Company', default=False)
    to_ignore_models = fields.Many2many(
        comodel_name="ir.model",
        relation="delete_all_company_data_wizard_model_rel",
        column1="wizard_id", column2="model_id", string="Ignore models")
    state = fields.Selection(
        string="State", selection=STATES, required=True, default='start')
    message = fields.Html(string="Message", default='', readonly=True)

    @api.multi
    def proceed(self):
        wizard = self[0]
        wizard_company = wizard.company_id.sudo()
        wizard_company_id = wizard.company_id.id
        admin_company_id = self.sudo().env.user.company_id.id
        lookup = {'res_company': [wizard_company_id]}
        lookup_constraints = {}
        log_prefix = 'EXECUTING %s for company %s: ' % (
            self._name, wizard.company_id.name)
        if wizard_company == self.sudo().env.user.company_id:
            error = _('Cannot delete the superuser company!')
            logger.error(log_prefix + error)
            raise UserError(error)
        start_models = self.sudo().env['ir.model'].search([
                ('model', '!=', self._name),
                ('model', 'not in', [m.model for m in wizard.to_ignore_models]),
        ])
        rel_name = 'res.company'

        def update_lookup(models, relation_model_name, relation_ids):
            if isinstance(relation_ids, (int, long)):
                relation_ids = [relation_ids]
            for model in models:
                logger.info(log_prefix + _('start processing %s') % model.model)
                try:
                    obj = self.sudo().env[model.model]
                except Exception:
                    logger.warning(
                        log_prefix + _(
                            'The model "%s" is declared but not available') %
                        model.model)
                if obj._abstract:
                    continue
                field_names = []
                for field in model.field_id:
                    if field.ttype == 'many2one' and \
                            field.relation == relation_model_name:
                        field_names.append(field.name)
                if field_names:
                    i = _(
                        'matching external company references for the following'
                        ' fields\n')
                    logger.info(log_prefix + i + ',\n'.join(field_names))
                    domain = ['|' for r in range(len(field_names) - 1)]
                    check_domain = list(domain)
                    for field_name in field_names:
                        domain.append((field_name, 'in', relation_ids))
                        if relation_model_name == 'res.company':
                            check_domain.append((field_name, '=', admin_company_id))
                    records = obj.search(domain)
                    if relation_model_name == 'res.company':
                        check_records = obj.search(check_domain)
                        if records & check_records:
                            if wizard.test:
                                wizard.to_ignore_models += model
                            else:
                                error = _(
                                    'The model "%s" has a no valid search '
                                    'field for company m2o field!') % (
                                    model.model)
                                logger.error(log_prefix + error)
                                raise UserError(error)
                    lookup[obj._table] = records.ids
                    i = _('found %d records for model %s') % (
                        len(records), model.model)
                    logger.info(log_prefix + i)
                else:
                    i = _(
                        'no company field found for model %s, this field will '
                        'be ignored!') % model.model
                    logger.info(log_prefix + i)

        update_lookup(start_models, rel_name, wizard_company_id)
        obj_to_delete_models_count = len(lookup.keys())
        obj_deleted_models_count = 0
        obj_deleted_records_count = 0
        savepoint = '%s_%d' % (self._name.replace('.', '_'), wizard.id)
        if wizard.test:
            info = 'delete test started using savepoint "%s".' % savepoint
            logger.info(log_prefix + info)
            self.env.cr.execute('SAVEPOINT %s' % savepoint)
        while lookup:
            keys = lookup.keys()
            remain_tables = len(keys)
            info = _('------------------------ %d tables left!') % remain_tables
            logger.info(log_prefix + info)
            for k in keys:
                model_savepoint = savepoint + '_' + k
                record_ids = lookup[k]
                try:
                    deleted_count = len(record_ids)
                    if not deleted_count:
                        del(lookup[k])
                        continue
                    self.env.cr.execute('SAVEPOINT %s' % model_savepoint)
                    self.env.cr.execute(
                        'ALTER TABLE %s DISABLE TRIGGER USER' % k
                    )
                    query = 'DELETE FROM %s WHERE id IN' % k
                    query += ' %s'
                    self.env.cr.execute(query, (tuple(record_ids),))
                    self.env.cr.execute(
                        'ALTER TABLE %s ENABLE TRIGGER USER' % k
                    )
                    del(lookup[k])
                    obj_deleted_models_count += 1
                    obj_deleted_records_count += deleted_count
                    info = _('deleted successfully %s records for table %s') % (
                        deleted_count, k)
                    logger.info(log_prefix + info)
                    self.env.cr.execute(
                        'RELEASE SAVEPOINT %s' % model_savepoint)
                except Exception as e:
                    s = e.pgerror
                    if 'violates foreign key constraint' in s:
                        table_name = \
                            s[s.find('"')+1:s.find(
                                '" violates foreign key constraint')]
                        trigger_name = s[s.find(
                            'violates foreign key constraint "')+33:s.find(
                            '" on table "')]
                        constraint_table_name = s[s.find(
                            '" on table "')+12:s.find(
                            '"\n')]
                        if not table_name or not trigger_name or \
                                not constraint_table_name:
                            raise UserError("HELP ME!")
                        lookup_constraints.setdefault(
                            constraint_table_name, set()).add(trigger_name)
                        self.env.cr.execute(
                            'ALTER TABLE %s DISABLE TRIGGER %s' % (
                                constraint_table_name, trigger_name))
                        if not lookup.get(table_name):
                            model_name = constraint_table_name.replace('_', '.')
                            update_lookup(self.sudo().env['ir.model'].search(
                                [('model', '=', model_name)]
                            ), k.replace('_', '.'), record_ids)
                    warning = _(
                        'the table %s will be processed later: %s') % (
                        k, e.message)
                    logger.warning(log_prefix + warning)
                    self.env.cr.execute(
                        'ROLLBACK TO SAVEPOINT %s' % model_savepoint)
        message = []
        if wizard.test:
            self.env.cr.execute('ROLLBACK TO SAVEPOINT %s' % savepoint)
            info = _('delete test completed with rollback to savepoint "%s".'
                     ) % savepoint
            logger.info(log_prefix + info)
            wizard.state = 'checked'
            message.append(_('<h3>Test operation completed</h3>'))
            message.append(
                _('<p>Run again this wizard to apply following changes.</p>'))
        else:
            for table in lookup_constraints.keys():
                for trigger in lookup_constraints[table]:
                    self.env.cr.execute(
                        'ALTER TABLE %s ENABLE TRIGGER %s' % (table, trigger))
            self.env.cr.commit()
            wizard.state = 'done'
            wizard.company_id = False
            info = _('delete process completed successfully.')
            logger.info(log_prefix + info)
            message.append('<h3>Operation completed</h3>')
        message.append('<p>')
        message.append(
            _('Models to delete: %d.<br/>') % obj_to_delete_models_count)
        message.append(
            _('Models deleted: %d.<br/>') % obj_deleted_models_count)
        message.append(
            _('Records deleted: %d.<br/>') % obj_deleted_records_count)
        message.append('</p>')
        wizard.message = ''.join(message)
        return {
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': self._name,
            'res_id': wizard.id,
            'type': 'ir.actions.act_window',
            'target': 'new',
        }
