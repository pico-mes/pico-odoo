{
    'name': 'Pico MES Integration',
    'author': "Hibou Corp.",
    'depends': [
        'mrp',
        'queue_job',
    ],
    'demo': [],
    'data': [
        'security/pico_security.xml',
        'security/ir.model.access.csv',
        'data/activity_data.xml',
        'views/mrp_views.xml',
        'views/pico_menu.xml',
        'views/pico_workflow_view.xml',
        'views/res_config_settings_views.xml',
    ],
    'auto_install': False,
    'installable': True,
    'application': True,
}
