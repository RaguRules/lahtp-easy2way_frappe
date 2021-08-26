from __future__ import unicode_literals, print_function
import frappe
from frappe.model.document import Document
from frappe.utils import cint, has_gravatar, format_datetime, now_datetime, get_formatted_email,today
from frappe import throw, msgprint, _
from frappe.utils.password import update_password as _update_password
from frappe.desk.notifications import clear_notifications
from frappe.utils.user import get_system_managers
import frappe.permissions
import frappe.share
import re, ast
from frappe.website.utils import is_signup_enabled
from frappe.utils.background_jobs import enqueue
from random import randint
from frappe.utils.password import update_password
import frappe.utils.data as utils
from frappe.desk.form.load import get_attachments
import json


@frappe.whitelist()
def verify_password(password):
	frappe.local.login_manager.check_password(frappe.session.user, password)

@frappe.whitelist(allow_guest=True)
def sign_up(full_name, mobile_no):
	def generate_otp():
		otp = ''.join(["{}".format(random.randint(0, 9)) for i in range(0, otp_length)])
		return {"id": key, "otp": otp, "timestamp": str(frappe.utils.get_datetime().utcnow())}

	message = ""
	if not frappe.db.exists("User", {"mobile_no": mobile_no}):
		if frappe.db.sql("""select count(*) from tabUser where
			HOUR(TIMEDIFF(CURRENT_TIMESTAMP, TIMESTAMP(modified)))=1""")[0][0] > 1000:
			return {'status': 0, 'message': _("Too many users signed up recently, so the registration is disabled. Please try back in an hour")}

		import random
		hash = random.getrandbits(128)
		hash = "%032x" % hash

		hash1 = random.getrandbits(128)
		hash1 = "%032x" % hash1

		key = mobile_no + "_otp"
		otp_length = 6 # 6 digit OTP
		rs = frappe.cache()

		user = frappe.get_doc({
			"doctype":"User",
			"email": "e2wuser_{0}@server.local".format(hash),
			"first_name": full_name,
			"enabled": 0,
			"mobile_no": mobile_no,
			"new_password": hash1,
			'user_type': 'System User',
			"send_welcome_email": 0
		})
		user.flags.ignore_permissions = True
		user.insert()

		u = frappe.get_doc('User', {"mobile_no": mobile_no})
		u.append('roles',{
			"doctype": "Has Role",
			"role":"Customer"
		})
		# u.role_profile_name = 'Owner'
		u.flags.ignore_permissions = True
		u.save(ignore_permissions=True)
		#create customer
		cust = frappe.new_doc("Customer")
		cust.update({
			"customer_name": full_name,
			"customer_type": "Individual",
			"gender": "Prefer not to say",
			"customer_group": "Individual",
			"default_currency": "INR",
			"account_manager": user.name
		})
		cust.flags.ignore_mandatory=True
		cust.save(ignore_permissions=True)
		if rs.get_value(key) and otp_not_expired(rs.get_value(key)): # check if an otp is already being generated
			otp_json = rs.get_value(key)
		else:
			otp_json = generate_otp()
			rs.set_value(key, otp_json)

		"""
		FIRE SMS FOR OTP
			"{0} is your OTP for AgriNext. Do not share OTP with anybody. Thanks.".format(otp_json.get("otp"))
		"""
		message = "Registered Succefully & OTPGENERATED:{0}".format(otp_json.get("otp")) # MUST DISABLE IN PRODUCTION!!
	else:
		message = "Already Registered"
	return message

@frappe.whitelist(allow_guest=True)
def verify_otp_signup(mobile_no, otp, client_id):
	if mobile_no=="Administrator":
		return {'status': 2, 'message': _("Not allowed")}

	try:
		user = frappe.get_doc("User", {"mobile_no": mobile_no})
		if user.enabled:
			return {'status': 0, 'message': _("User is already enabled.")}
		else:
			rs = frappe.cache()
			otp_json = rs.get_value("{0}_otp".format(mobile_no))
			if otp_json is None or otp_json.get("otp") != otp:
				return {'status': -1, 'message': _("OTP does not exist. Contact support.")}
			elif otp_not_expired(otp_json):
				user.enabled = 1
				user.flags.ignore_permissions = True
				user.save(ignore_permissions=True)
				rs.delete_key(mobile_no + "_otp")

				otoken = create_bearer_token(mobile_no, client_id)
				out = {
					'status': 1,
					'message': _("Verification successful."),
					"access_token": otoken.access_token,
					"refresh_token": otoken.refresh_token,
					"expires_in": otoken.expires_in,
					"scope": otoken.scopes
				}

				# Delete consumed otp
				rs.delete_key(mobile_no + "_otp")

				frappe.local.response = frappe._dict(out)
			else:
				return {'status': 2, 'message': _("OTP Invalid or Expired. Please try again.")}
	except frappe.DoesNotExistError:
		return {'status': 3, 'message': _("User does not exist")}

def create_bearer_token(mobile_no, client_id):
	otoken = frappe.new_doc("OAuth Bearer Token")
	otoken.access_token = frappe.generate_hash(length=30)
	otoken.refresh_token = frappe.generate_hash(length=30)
	otoken.user = frappe.db.get_value("User", {"mobile_no": mobile_no}, "name")
	otoken.scopes = "all"
	otoken.client = client_id
	otoken.redirect_uri = frappe.db.get_value("OAuth Client", client_id, "default_redirect_uri")
	otoken.expires_in = 604800
	otoken.save(ignore_permissions=True)
	frappe.db.commit()

	return otoken

@frappe.whitelist(allow_guest=True)
def resend_otp_signup(mobile_no):
	if user=="Administrator":
		return {'status': 2, 'message': _("Not allowed")}

	try:
		user = frappe.get_doc("User", {"mobile_no": mobile_no})
		if user.enabled:
			return {'status': 0, 'message': _("User is already enabled.")}
		else:
			# sms_template = str(frappe.db.get_single_value('SMS Templates', 'otp_verification_text'))
			# sms_text = sms_template.format(
			# 	name = user.full_name,
			# 	otp = str(user.otp)
			# )
			# send_sms([str(user.phone)], sms_text)
			return {'status': 1, 'message': _("OTP resent successfully")}
	except frappe.DoesNotExistError:
		return {'status': 3, 'message': _("User does not exist")}

def otp_not_expired(otp_json):
	flag = True
	diff = frappe.utils.get_datetime().utcnow() - frappe.utils.get_datetime(otp_json.get("timestamp"))
	if int(diff.seconds) / 60 >= 10:
		flag = False

	return flag

@frappe.whitelist(allow_guest=True)
def verify_otp(user, otp):
	if user=="Administrator":
		return {'status': 2, 'message': _("Not allowed")}

	try:
		user = frappe.get_doc("User", user)
		if user.enabled:
			return {'status': 0, 'message': _("User is already enabled.")}
		else:
			if str(user.otp) == str(otp) and user.otp_valid_till > utils.now_datetime():
				user.enabled = 1
				user.flags.ignore_permissions = True
				user.save(ignore_permissions=True)
				return {'status': 1, 'message': _("Verification successful. Please continue login.")}
			else:
				return {'status': 2, 'message': _("OTP Invalid or Expired. Please try again.")}
	except frappe.DoesNotExistError:
		return {'status': 3, 'message': _("User does not exist")}

@frappe.whitelist(allow_guest=True)
def resend_otp_signup(user):
	if user=="Administrator":
		return {'status': 2, 'message': _("Not allowed")}

	try:
		user = frappe.get_doc("User", user)
		if user.enabled:
			return {'status': 0, 'message': _("User is already enabled.")}
		else:
			# sms_template = str(frappe.db.get_single_value('SMS Templates', 'otp_verification_text'))
			# sms_text = sms_template.format(
			# 	name = user.full_name,
			# 	otp = str(user.otp)
			# )
			# send_sms([str(user.phone)], sms_text)
			return {'status': 1, 'message': _("OTP resent successfully")}
	except frappe.DoesNotExistError:
		return {'status': 3, 'message': _("User does not exist")}

@frappe.whitelist(allow_guest=True)
def get_items(category):
	if category:
		item_list = frappe.get_list("Item",{"item_group": category},["item_code","item_name","description", "stock_uom", "image"])
		image_list = []
		for item in item_list:
			attachments = get_attachments("Item", item.item_code)
			item_details = frappe.db.sql(""" SELECT id.pouch_or_pack,id.weight_per_unit,id.actual_price,id.selling_price,id.item_image
										FROM `tabE2W Item Detail` id
										WHERE id.parent='%s' """%item.item_code,as_dict=1)

			item.update({
				"options": item_details,
				"images": attachments
			})
		return item_list

@frappe.whitelist()
def get_cart_items():
	if frappe.session.user:
		cart_list = frappe.get_list("E2W Cart",{"owner": frappe.session.user,"status": "Pending","docstatus":1,"qty":[">",0]},["item_code","item_name","description","qty","item_image","pouch_or_pack","weight_per_unit"])
		return cart_list
	else:
		return {"error": "User not logged in"}

@frappe.whitelist(allow_guest=True)
def get_search_items(text):
	# if text:
	# 	item_list = frappe.db.sql(""" SELECT item_code,item_name,description,image
	# 								FROM `tabItem` WHERE item_name LIKE '%{0}%' """.format(text),as_dict=1)
	# 	return item_list

	if text:
		item_list = frappe.get_list("Item",filters={'item_name': ['like', '%{}%'.format(text)]},fields=["item_code","item_name","description", "stock_uom", "image"])
		for item in item_list:
			attachments = get_attachments("Item", item.item_code)
			item_details = frappe.db.sql(""" SELECT id.pouch_or_pack,id.weight_per_unit,id.actual_price,id.selling_price,id.item_image
										FROM `tabE2W Item Detail` id
										WHERE id.parent='%s' """%item.item_code,as_dict=1)
			item.update({
				"options": item_details,
				"images": attachments
			})
		return item_list

@frappe.whitelist()
def get_recently_ordered_items():
	user = frappe.session.user
	customer = frappe.get_value("Customer",{"account_manager": user})
	if customer:
		order_list = frappe.db.sql(""" SELECT si.name,sii.item_code,sii.item_name,sii.qty,sii.rate,sii.amount,sii.description,sii.image,si.posting_date
									FROM `tabSales Invoice` si, `tabSales Invoice Item` sii
									WHERE si.docstatus=1 and si.customer='%s' and sii.parent=si.name """%customer,as_dict=1)
		return order_list

@frappe.whitelist()
def get_my_orders():
	user = frappe.session.user
	customer = frappe.get_value("Customer",{"account_manager": user})
	if customer:
		orders = frappe.get_list("Sales Invoice", filters={"customer": customer}, fields=["*"])
		return orders
	else:
		return {"error": "Customer not found"}
	# if customer:
	# 	order_list = frappe.db.sql(""" SELECT si.name,sii.item_code,sii.item_name,sii.qty,sii.rate,sii.amount,sii.description,sii.image,si.posting_date
	# 								FROM `tabSales Invoice` si, `tabSales Invoice Item` sii
	# 								WHERE si.docstatus=1 and si.customer='%s' and sii.parent=si.name """%customer,as_dict=1)
	# 	return order_list

@frappe.whitelist()
def create_address_and_contact(full_name, address_line1, address_line2, city, state, postal_code ,mobile_no):
	if frappe.session.user:
		user = frappe.session.user
		customer = frappe.get_value("Customer",{"account_manager": user})
		contact = frappe.get_doc("Contact",{"user": user})
		contact.append("links",{
			"link_doctype": "Customer",
			"link_name": customer
		})
		contact.save(ignore_permissions=True)
		#create address
		add = frappe.new_doc("Address")
		add.update({
			"address_title": full_name,
			"address_line1": address_line1,
			"address_line2": address_line2,
			"city": city,
			"country": 'India',
			"state": state,
			"pincode": postal_code,
			"phone": mobile_no
		})
		add.append("links",{
				"link_doctype": "Customer",
				"link_name": customer
		})
		add.save(ignore_permissions=True)
		return {
			"name": add.name,
			"message": "Address updated successfully"
		}

@frappe.whitelist()
def get_address_details():
	if frappe.session.user:
		customer = frappe.get_value("Customer",{"account_manager": frappe.session.user})
		add_list = frappe.db.sql(""" SELECT `tabAddress`.name, address_title, address_line1, address_line2, city, state, country, pincode, phone FROM `tabAddress` INNER JOIN `tabDynamic Link` ON `tabAddress`.name=`tabDynamic Link`.parent WHERE `tabDynamic Link`.link_doctype="Customer" and `tabDynamic Link`.link_name='%s' """ %customer,as_dict=1)
		return add_list
	else:
		return {"error": "User not logged in"}

@frappe.whitelist()
def add_to_cart(item_code, qty, pouch_or_pack, weight_per_unit):
	if frappe.session.user:
		cart_status = check_cart(item_code, qty, pouch_or_pack, weight_per_unit)
		if cart_status == False:
			rate = frappe.db.sql(""" SELECT selling_price FROM `tabE2W Item Detail`
											WHERE parent='%s' and weight_per_unit='%s'
											"""%(item_code,weight_per_unit),as_dict=1)
			cart = frappe.new_doc("E2W Cart")
			cart.update({
				"item_code": item_code,
				"qty": qty,
				"pouch_or_pack": pouch_or_pack,
				"weight_per_unit": weight_per_unit,
				"owner": frappe.session.user,
				"rate": rate[0].selling_price
			})
			#cart.flags.ignore_mandatory=True
			cart.save()
			cart.submit()
			return "Added to cart"
		else:
			return "Quantity Updated"
	else:
		return {"error": "User not logged in"}

def check_cart(item_code, qty, pouch_or_pack, weight_per_unit):
	if frappe.session.user:
		if frappe.db.exists("E2W Cart",{"item_code": item_code,"pouch_or_pack": pouch_or_pack,"weight_per_unit": weight_per_unit,"status": "Pending","owner":frappe.session.user,"docstatus": 1}):
			cart = frappe.get_doc("E2W Cart",{"item_code": item_code,"pouch_or_pack": pouch_or_pack,"weight_per_unit": weight_per_unit,"status": "Pending","owner":frappe.session.user, "docstatus": 1})
			cart.update({
				"qty": qty,
			})
			cart.flags.ignore_mandatory=True
			cart.save(ignore_permissions=True)
			return True
		else:
			return False
	else:
		return {"error": "User not logged in"}

@frappe.whitelist()
def checkout(address_name, items_list=None):
	if frappe.session.user:
		if items_list:
			items_list = json.loads(items_list)
			for i in items_list:
				add_to_cart(i.get("item_code"), i.get("qty"), i.get("pouch_or_pack"), i.get("weight_per_unit"))
		items = get_cart_items()
		if len(items) > 0:
			customer = frappe.get_value("Customer",{"account_manager": frappe.session.user},["name"])
			si_doc = frappe.new_doc("Sales Invoice")
			if (frappe.db.exists("Address", {"name": address_name})): #We also need to check if the address is linked to the customer.
				si_doc.update({
						"company": "Easy2Way",
						"customer": customer,
						"customer_address": address_name,
						"due_date": today(),
				})
				for i in items:
					item = frappe.get_doc("Item", i.get("item_code"))
					rate = frappe.db.sql(""" SELECT selling_price FROM `tabE2W Item Detail`
											WHERE parent='%s' and weight_per_unit='%s'
											"""%(item.name,i.get("weight_per_unit")),as_dict=1)

					if rate and frappe.db.exists("E2W Cart",{"item_code": i.get("item_code"),"pouch_or_pack":i.get("pouch_or_pack"),"weight_per_unit":i.get("weight_per_unit"),"qty": i.get("qty"),"status": "Pending","docstatus": 1,"owner":frappe.session.user}):
						cart_doc = frappe.get_doc("E2W Cart",{"item_code": i.get("item_code"),"pouch_or_pack":i.get("pouch_or_pack"),"weight_per_unit":i.get("weight_per_unit"),"qty": i.get("qty"),"status": "Pending","docstatus":1,"owner": frappe.session.user})
						frappe.db.set_value("E2W Cart",cart_doc.name,"status", "Ordered")

						si_doc.append("items",{
								"item_code": i.get("item_code"),
								"item_name": item.item_name,
								"description": item.description,
								"qty": i.get("qty"),
								"uom": item.stock_uom,
								"image": item.image,
								"rate": float(rate[0].selling_price),
								"amount": float(rate[0].selling_price) * float(i.get("qty"))
						})
				si_doc.flags.ignore_mandatory = True
				si_doc.save(ignore_permissions=True) #Need to be security tested
				si_doc.submit()
				return {
					"status": si_doc.status,
					"order_id": si_doc.name,
					"message": "Your order has been successfully placed."
				}
			else:
				return {
					"error": "Address doesn't exist."
				}
		else:
			return {"error": "Your cart is empty"}
	else:
		return {"error": "User not logged in"}

@frappe.whitelist(allow_guest=True)
def get_cards():
	cards = []
	cards_list = frappe.db.sql(""" SELECT card FROM `tabE2W Card` 
									WHERE enable=1 """, as_dict=1)
	if cards_list:
		for c in cards_list:
			cards.append(c.card)
	return cards

@frappe.whitelist(allow_guest=True)
def get_scroll_text():
	st_list = []
	scroll_texts = frappe.db.sql(""" SELECT text FROM `tabE2W Scroll Text` 
									WHERE enable=1 """, as_dict=1)
	if scroll_texts:
		for st in scroll_texts:
			st_list.append(st.text)
	return st_list

