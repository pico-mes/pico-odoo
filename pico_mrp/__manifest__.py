{
    'name': 'Pico MES Integration',
    'author': "Hibou Corp.",
    'depends': [
        'mrp',
    ],
    'demo': [],
    'data': [
        'security/pico_security.xml',
        'security/ir.model.access.csv',
        'views/mrp_views.xml',
        'views/pico_menu.xml',
        'views/pico_workflow_view.xml',
    ],
    'auto_install': False,
    'installable': True,
}
