# -*- coding: utf-8 -*-
# Copyright (c) 2021, Ninja and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document

class E2WHomeScreen(Document):
	def validate(self):
		typedoc = frappe.get_doc("E2W Home Screen View Type", {"name": self.type})
		if typedoc.grid_validation == "Minimum":
			if int(self.no_of_grids) > int(len(self.details)):
				frappe.throw("There should be a minimum"+ str(self.no_of_grids) + " rows in the Home Screen Details table.")
		elif typedoc.grid_validation == "Equal":
			if int(self.no_of_grids) != int(len(self.details)):
				frappe.throw("There should be a "+ str(self.no_of_grids) + " rows in the Home Screen Details table.")
		else:
			frappe.throw("Grid Validation Options unknown.")