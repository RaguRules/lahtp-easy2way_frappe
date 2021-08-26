from __future__ import unicode_literals
from frappe import _

def get_data():
	return [
		{
			"label": _("Easy2Way"),
			"icon": "fa fa-star",
			"items": [
				{
					"type": "doctype",
					"name": "E2W Card",
					"description": _("E2W Cards."),
                    "route": "#List/E2W Card",
					"onboard": 1,
				},
			]
		},	
	]

