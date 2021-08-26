from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming   import make_autoname

def customer_autoname(doc, method):
	doc.name = doc.account_manager
