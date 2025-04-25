import xmlrpc.client
from odoo import models, api, fields
from odoo.exceptions import UserError

# Remote (master) database connection
ODOO_URL = "http://localhost:8069"
MASTER_DB = "master_db"
MASTER_USER = "admin@example.com"
MASTER_PASS = "admin"


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        for user, vals in zip(users, vals_list):
            password = vals.get('password')
            if password:
                try:
                    user.send_credentials_to_master(password)
                except Exception as e:
                    raise UserError(f"Credential sync to master DB failed: {e}")
        return users

    def _change_password(self, new_passwd):
        for user in self:
            try:
                user.send_credentials_to_master(new_passwd)
            except Exception as e:
                raise UserError(f"Credential sync to master DB failed: {e}")
        return super()._change_password(new_passwd)

    def unlink(self):
        for user in self:
            try:
                user.delete_from_master()
            except Exception as e:
                raise UserError(f"Failed to delete from master DB: {e}")
        return super().unlink()

    def write(self, vals):
        old_data = {
            user.id: {
                'email': user.email,
                'db_name': user.env.cr.dbname
            }
            for user in self
        }

        res = super().write(vals)

        for user in self:
            try:
                user.update_credentials_in_master(vals, old_data.get(user.id))
            except Exception as e:
                raise UserError(f"Failed to update credentials in master DB: {e}")
        return res

    def send_credentials_to_master(self, raw_password):
        try:
            uid, models = self._connect_master()
            credential_data = {
                'email': self.email,
                'password': raw_password,
                'db_name': self.env.cr.dbname,
            }

            existing = models.execute_kw(
                MASTER_DB, uid, MASTER_PASS,
                'master.user', 'search',
                [[['email', '=', credential_data['email']], ['db_name', '=', credential_data['db_name']]]]
            )

            if not existing:
                models.execute_kw(
                    MASTER_DB, uid, MASTER_PASS,
                    'master.user', 'create',
                    [credential_data]
                )
        except Exception as e:
            raise UserError(f"XML-RPC Error: {str(e)}")

    def delete_from_master(self):
        try:
            uid, models = self._connect_master()
            domain = [
                ('email', '=', self.email),
                ('db_name', '=', self.env.cr.dbname)
            ]

            record_ids = models.execute_kw(
                MASTER_DB, uid, MASTER_PASS,
                'master.user', 'search',
                [domain]
            )

            if record_ids:
                models.execute_kw(
                    MASTER_DB, uid, MASTER_PASS,
                    'master.user', 'unlink',
                    [record_ids]
                )
        except Exception as e:
            raise UserError(f"Master DB delete error: {str(e)}")

    def update_credentials_in_master(self, vals, old_data):
        try:
            uid, models = self._connect_master()
            domain = [
                ('email', '=', old_data.get('email')),
                ('db_name', '=', old_data.get('db_name'))
            ]

            record_ids = models.execute_kw(
                MASTER_DB, uid, MASTER_PASS,
                'master.user', 'search',
                [domain]
            )

            if record_ids:
                update_vals = {}
                if 'email' in vals:
                    update_vals['email'] = vals['email']
                if 'password' in vals:
                    update_vals['password'] = vals['password']

                if update_vals:
                    models.execute_kw(
                        MASTER_DB, uid, MASTER_PASS,
                        'master.user', 'write',
                        [record_ids, update_vals]
                    )
        except Exception as e:
            raise UserError(f"Master DB update error: {str(e)}")

    def _connect_master(self):
        common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
        uid = common.authenticate(MASTER_DB, MASTER_USER, MASTER_PASS, {})
        if not uid:
            raise UserError("Authentication to master DB failed")
        models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
        return uid, models
