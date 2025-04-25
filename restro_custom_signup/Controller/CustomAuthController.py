import sys
import os
import re
import logging
import werkzeug  # type: ignore
import odoo

from odoo import http, _, modules, SUPERUSER_ID,api
from odoo.http import request, Response
from odoo.addons.web.controllers.database import Database 
from odoo.tools import file_open
from odoo.service import db as dispatch_rpc
from .utils import (
    ensure_db,
    _get_login_redirect_url,
    is_user_internal,
)

_logger = logging.getLogger(__name__)
DBNAME_PATTERN = '^[a-zA-Z0-9][a-zA-Z0-9_-]+$'
SIGN_UP_REQUEST_PARAMS = {
    'db', 'login', 'debug', 'token', 'message', 'error', 'scope', 'mode',
    'redirect', 'redirect_hostname', 'email', 'name', 'partner_id',
    'password', 'confirm_password', 'city', 'country_id', 'lang', 'signup_email'
}
LOGIN_SUCCESSFUL_PARAMS = set()
CREDENTIAL_PARAMS = ['email', 'password', 'type']
master_pwd = "admin"
master_db = 'master_db'

class CustomDatabase(Database):

    class CustomAuth(http.Controller):

        @http.route('/web/database/selector', type='http', auth='none', website=True, csrf=False)
        def signup(self, **post):
            if request.httprequest.method == 'GET':
                return self._render_signup_template()

            email = post.get('email')
            password = post.get('password')
            phone_no = post.get('phone_no')
            db_name = post.get('db_name')

            _logger.info("Received signup POST: %s", post)

            if not email or not password or not phone_no or not db_name:
                return self.render_signup_page('signup', error="All fields are required.")

            if not phone_no.isdigit() or len(phone_no) != 10:
                return self.render_signup_page('signup', error="Phone number must be exactly 10 digits.")

            if not re.match(DBNAME_PATTERN, db_name):
                return self.render_signup_page('signup', error="Invalid database name format.")

            # Create master DB name ==> master_db if not exists

            existing_dbs = http.dispatch_rpc('db', 'list', [])
            if master_db not in existing_dbs:
                try:
                    _logger.info("Creating master DB: %s", master_db)
                    http.dispatch_rpc('db', 'create_database', [
                        master_pwd, master_db, False, 'en_US', 'admin', 'admin@example.com', 'US', ''
                    ])
                    _logger.info("Master DB created.")
                except Exception as e:
                    _logger.error("Failed to create master DB: %s", str(e))
                    return self.render_signup_page('signup', error="Could not create master DB.")

                # Installing the customuser module which contains master.user model ie table...........!!

                try:
                    registry_master = odoo.registry(master_db)
                    with registry_master.cursor() as cr:
                        env = api.Environment(cr, SUPERUSER_ID, {})
                        module_model = env['ir.module.module']
                        module = module_model.search([('name', '=', 'customuser')], limit=1)
                        if module and module.state != 'installed':
                            module.button_immediate_install()
                            _logger.info("customuser module installed in master_db.")
                except Exception as e:
                    _logger.error("Failed to install customuser in master_db: %s", str(e))
                    return self.render_signup_page('signup', error="Could not initialize master DB.")
                
            # Check for existing user and db_name in master_user table
            try:
                registry_master = odoo.registry(master_db)
                with registry_master.cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    master_user_model = env['master.user']
                    
                    # Checking for email.....
                    user_with_email = master_user_model.search([('email', '=', email)], limit=1)
                    
                    # Checking for db_name...
                    db_with_name = master_user_model.search([('db_name', '=', db_name)], limit=1)
                    
                    # If db_name exists, check if email is already associated with that db_name 2 conditions for that same and diffrent db_name
                    if db_with_name:
                        if user_with_email and user_with_email.db_name == db_name:
                            # If email is already with the same db_name, return error
                            return self.render_signup_page('signup', error=f"Database with this name and email '{email}' already exists.")
                        elif user_with_email and user_with_email.db_name != db_name:
                            # If email exists but is with a different db_name, return error
                            return self.render_signup_page('signup', error="Email is already associated with a different database.")
                    
                    # If email exists independently
                    if user_with_email:
                        return self.render_signup_page('signup', error=f"Email '{email}' already exists.")
                    
                    # Check if the phone number exists
                    if master_user_model.search([('phone_no', '=', phone_no)], limit=1):
                        return self.render_signup_page('signup', error="Phone number already exists.")

            except Exception as e:
                _logger.error("Failed to access master user model: %s", str(e))
                return self.render_signup_page('signup', error="Error checking existing users.")
            
            # if same db_name with different email id every time first need to check.................
            existing_dbs = http.dispatch_rpc('db', 'list', [])

            # Filter databases that start with the same name!!!!!!!!
            matching_dbs = [name for name in existing_dbs if name == db_name or name.startswith(f"{db_name}_")]

            if matching_dbs:
                suffix = 1
                while True:
                    new_db_name = f"{db_name}_{suffix:02d}"
                    if new_db_name not in existing_dbs:
                        db_name = new_db_name
                        break
                    suffix += 1


            # Create tenant DB (check if the database already exists)
            # if db_name in existing_dbs:
            #     return self.render_signup_page('signup', error="Database with this name already exists.")

            # continue proceeding with the databse creation for the user
             
            lang = request.httprequest.headers.get('Accept-Language', 'en_US').split(',')[0]
            country_code = request.httprequest.headers.get('CF-IPCountry', '') or 'US'

            try:
                _logger.info("Creating tenant DB: %s", db_name)
                http.dispatch_rpc('db', 'create_database', [
                    master_pwd, db_name, False, lang, password, email, country_code, ''
                ])
                _logger.info("Tenant DB '%s' created successfully.", db_name)
            except Exception as e:
                _logger.error("Failed to create tenant DB: %s", str(e))
                return self.render_signup_page('signup', error="Could not create user database.")

            # Inserting the credentials into master_user table
            try:
                registry_master = odoo.registry(master_db)
                with registry_master.cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    env['master.user'].create({
                        'email': email,
                        'password': password,
                        'db_name': db_name,
                        'phone_no': phone_no,
                    })

                    _logger.info("User inserted into master DB.")

            except Exception as e:
                _logger.error("Failed to insert user into master DB: %s", str(e))
                return self.render_signup_page('signup', error="Failed to save user info.")

            request.session.db = db_name
            return request.redirect('/web/login')

        def _render_signup_template(self, error=None):
            with file_open("restro_custom_signup/views/signup.qweb.html", "r") as fd:
                template = fd.read()
                if error:
                    error_html = f"<div class='alert alert-danger' id='error-message'>{error}</div>"
                    template = template.replace("<!--ERROR-->", error_html)
                return Response(template, content_type='text/html; charset=utf-8')

        def render_signup_page(self, page_name, error=None):
            return self._render_signup_template(error=error)

        def render_login_page(self, page_name, error=None):
            return self._render_login_template(error=error)

        def _render_login_template(self, error=None):
            with file_open("restro_custom_signup/views/login.qweb.html", "r") as fd:
                template = fd.read()
                if error:
                    error_html = f"<div class='alert alert-danger' id='error-message'>{error}</div>"
                    template = template.replace("<!--ERROR-->", error_html)
                return Response(template, content_type='text/html; charset=utf-8')


        @http.route('/web/login', type='http', auth='none', readonly=False, website=True, csrf=False)
        def web_login(self, redirect=None, **kw):
            if request.httprequest.method == 'GET':
                return self._render_login_template()

            def get_user_info_from_master(identifier):
                db = 'master_db'  # Master DB name
                try:
                    registry = odoo.registry(db)
                    with registry.cursor() as cr:
                        env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
                        user = env['master.user'].search([
                            '|',
                            ('email', '=', identifier),
                            ('phone_no', '=', identifier)
                        ], limit=1)
                        if user:
                            return {
                                'db_name': user.db_name,
                                'email': user.email
                            }
                except Exception as e:
                    _logger.error("Error checking master DB %s: %s", db, str(e))
                return None

            ensure_db()
            request.params['login_success'] = False
            values = {k: v for k, v in request.params.items() if k in SIGN_UP_REQUEST_PARAMS}
            values['redirect'] = redirect or '/odoo'

            try:
                values['databases'] = http.db_list()
            except odoo.exceptions.AccessDenied:
                values['databases'] = None

            if request.httprequest.method == 'POST':
                try:
                    identifier = request.params.get('email', '').strip()
                    password = request.params.get('password', '').strip()

                    _logger.info("🔍 Login POST: Received identifier: %s, Password: %s", identifier, password)

                    if not identifier or not password:
                        return self.render_login_page('login', error="Email/Phone and Password are required!")

                    user_info = get_user_info_from_master(identifier)

                    if not user_info:
                        return self.render_login_page('login', error="No account found with this email/phone!")

                    db_name = user_info['db_name']
                    actual_login = user_info['email']

                    _logger.info("👉👉 Derived DB name: %s", db_name)
                    available_dbs = dispatch_rpc.list_dbs()
                    _logger.info("☝️☝️ Available databases: %s", available_dbs)

                    if db_name not in available_dbs:
                        return self.render_login_page('login', error="Invalid database associated with this account!")

                    credential = {
                        'login': actual_login,
                        'password': password,
                        'type': 'password'
                    }

                    auth_info = request.session.authenticate(db_name, credential)  

                    _logger.info("✔️✔️ Authentication result: %s", auth_info)

                    if auth_info:
                        request.params['login_success'] = True
                        return request.redirect('/odoo')
                    else:
                        return self.render_login_page('login', error="Wrong login/password")

                except odoo.exceptions.AccessDenied:
                    return self.render_login_page('login', error="Wrong login/password")

                except Exception as e:
                    _logger.error("Unexpected error during login: %s", str(e))
                    return self.render_login_page('login', error="An unexpected error occurred. Please try again.")

            response = request.render('custom._render_login_template', values)
            response.headers['Cache-Control'] = 'no-cache'
            response.headers['X-Frame-Options'] = 'SAMEORIGIN'
            response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
            return response