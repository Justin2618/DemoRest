{
    'name': 'Master User',
    'version': '18.0',
    'category': 'Custom',
    'summary': 'Module to manage master user data for Restro..',
    'author': 'Process Drive',
    'website': 'https://www.processdrive.com',
    'depends': ['base','web','auth_signup'],
    'data': [
        'views/reset_password.xml',
        'security/ir.model.access.csv',
        ],
    'auto_install': True,
    'installable': True,
    'application': False,
}