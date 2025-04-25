from odoo import models, fields, api
import datetime
 
class MasterUser(models.Model):
    _name = 'master.user'
    _description = 'Master User Data'
 
    s_no = fields.Integer(string='S.No', readonly=True, default=lambda self: self._get_next_serial())
    email = fields.Char(string='Email', required=True, unique=True)
    password = fields.Char(string='Password', required=True)
    db_name = fields.Char(string="Database Name")
    phone_no = fields.Char(string="Phone NUmber")
    created_at = fields.Datetime(string='Created At', default=datetime.datetime.now())
    updated_at = fields.Datetime(string='Updated At', default=datetime.datetime.now())
 
    @api.model
    def _get_next_serial(self):
        last_record = self.search([], order="id desc", limit=1)
        return last_record.s_no + 1 if last_record else 1
 