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
from easy2way.easy2way.doctype.sms_center.sms_center import send_sms
from frappe.utils.nestedset import get_descendants_of
from frappe.utils.nestedset import get_ancestors_of


@frappe.whitelist()
def verify_password(password):
	frappe.local.login_manager.check_password(frappe.session.user, password)

@frappe.whitelist(allow_guest=True)
def get_user_data():
	if frappe.session.user and frappe.session.user != "Guest":
		user = frappe.get_doc("User", frappe.session.user)
		return {
			"full_name": user.full_name,
			"mobile_no": user.mobile_no,
			"user_id": user.name,
			"username": user.username,
			"language": user.language,
			"enabled": user.enabled
		}
	else:
		return {}


@frappe.whitelist(allow_guest=True)
def sign_up(full_name, mobile_no, resend=False):
	def generate_otp():
		otp = ''.join(["{}".format(random.randint(0, 9)) for i in range(0, otp_length)])
		return {"id": key, "otp": otp, "timestamp": str(frappe.utils.get_datetime().utcnow())}

	message = ""
	try:
		u = frappe.get_doc('User', {"mobile_no": mobile_no})
		if u.enabled == 0: #Resend OTP
			import random
			hash = random.getrandbits(128)
			hash = "%032x" % hash

			hash1 = random.getrandbits(128)
			hash1 = "%032x" % hash1

			key = mobile_no + "_otp"
			otp_length = 6 # 6 digit OTP
			rs = frappe.cache()
			if rs.get_value(key) and otp_not_expired(rs.get_value(key)): # check if an otp is already being generated
				otp_json = rs.get_value(key)
			else:
				otp_json = generate_otp()
				rs.set_value(key, otp_json)

			#sendsms
			msg = 'Your Easy2Way Shop OTP is ' + str(otp_json.get("otp")) + '. This will be valid only for 5 mins. Please do not share this OTP with anyone else over Phone or Messages.'
			send_sms([mobile_no], msg)
			message = "Resend OTP Success. OTP RESENT:{0}".format(otp_json.get("otp")) # MUST DISABLE IN PRODUCTION!!
		else: # Already enabled.
			message = "Already Registered. You can login now."

	except: #Signup Process
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

		#sendsms
		msg = 'Your Easy2Way Shop OTP is ' + str(otp_json.get("otp")) + '. This will be valid only for 5 mins. Please do not share this OTP with anyone else over Phone or Messages.'
		send_sms([mobile_no], msg)

		message = "Registered Succefully & OTPGENERATED:{0}".format(otp_json.get("otp")) # MUST DISABLE IN PRODUCTION!!
	return message

@frappe.whitelist(allow_guest=True)
def verify_otp_signup(mobile_no, otp, client_id, user_uid=None):
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

				if user_uid:
					user = frappe.get_value("User",{"mobile_no": mobile_no},["name"])
					cache_cart_items = get_cart_items(user_uid)["cart_items"]
					if len(cache_cart_items) > 0:
						for cci in cache_cart_items:
							frappe.session.user = user
							m = add_to_cart(cci.get("item_code"), cci.get("qty"), cci.get("package_variation"), cci.get("uom"), cci.get("weight_per_unit"))
							frappe.msgprint(m)
					frappe.cache().delete_key(user_uid)

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
	otoken.expires_in = 3600
	otoken.save(ignore_permissions=True)
	frappe.db.commit()

	return otoken

def otp_not_expired(otp_json):
	flag = True
	diff = frappe.utils.get_datetime().utcnow() - frappe.utils.get_datetime(otp_json.get("timestamp"))
	if int(diff.seconds) / 60 >= 10:
		flag = False

	return flag

@frappe.whitelist(allow_guest=True)
def get_item(name):
	name = name.replace("'", "")
	item = frappe.db.sql(""" SELECT item_code,item_name,description, stock_uom, item_group, image,brand
										FROM `tabItem`
										WHERE name='%s' """%name,as_dict=1)[0]
	ancestors = get_ancestors_of('Item Group', item.item_group)
	attachments = get_attachments("Item", item.item_code)
	item_details = frappe.db.sql(""" SELECT id.package_variation,id.uom,id.weight_per_unit,id.actual_price,id.selling_price,id.item_image
								FROM `tabE2W Item Detail` id
								WHERE id.parent='%s' ORDER BY id.selling_price DESC """%item.item_code,as_dict=1)

	if frappe.session.user and frappe.session.user != "Guest":
		for itemd in item_details:
			qty = get_item_qty_in_cart(item.item_code, itemd["package_variation"], itemd["weight_per_unit"])
			if qty:
				item_details[item_details.index(itemd)]["cart_quantity"] = qty
	item.update({
		"options": item_details,
		"images": attachments,
		"ancestors": ancestors
	})
	return item

@frappe.whitelist(allow_guest=True)
def get_items(category):
	if category:
		child_categories = []
		child_categories = get_descendants_of('Item Group', category, ignore_permissions=True)
		child_categories.append(category)
		item_list = frappe.get_list("Item",{"item_group": ["in", child_categories],"disabled": 0},["item_code","item_name","description", "stock_uom", "item_group", "image","brand"])
		image_list = []
		for item in item_list:
			ancestors = get_ancestors_of('Item Group', item.item_group)
			attachments = get_attachments("Item", item.item_code)
			item_details = frappe.db.sql(""" SELECT id.package_variation,id.uom,id.weight_per_unit,id.actual_price,id.selling_price,id.item_image
										FROM `tabE2W Item Detail` id
										WHERE id.parent='%s' ORDER BY id.selling_price DESC"""%item.item_code,as_dict=1)

			if frappe.session.user and frappe.session.user != "Guest":
				for itemd in item_details:
					qty = get_item_qty_in_cart(item.item_code, itemd["package_variation"], itemd["weight_per_unit"])
					if qty:
						item_details[item_details.index(itemd)]["cart_quantity"] = qty
			item.update({
				"options": item_details,
				"images": attachments,
				"ancestors": ancestors
			})
		for item in item_list:
			for group in item.ancestors:
				if("Hidden" in group or "hidden" in group):
					del item_list[item_list.index(item)]
		return item_list

@frappe.whitelist(allow_guest=True)
def get_cart_items(user_uid=None):
	# user = frappe.session.user
	# user = ""
	cart_list = None
	if frappe.session.user and frappe.session.user != "Guest":
		cart_list = frappe.get_list("E2W Cart",{"owner": frappe.session.user,"status": "Pending","docstatus":1,"qty":[">",0]},["item_code","item_name","description","qty","item_image","package_variation","uom","weight_per_unit","rate", "creation"], order_by="creation desc")
	else:
		if user_uid:
			cart_list = frappe.cache().get_value(user_uid)
	if cart_list:
		for item in cart_list:
			item_details = frappe.db.sql(""" SELECT id.package_variation,id.weight_per_unit,id.actual_price,id.selling_price,id.item_image,id.parent, id.uom
										FROM `tabE2W Item Detail` id
										WHERE id.parent='%s' """%item.get("item_code"),as_dict=1)
			i = frappe.get_doc("Item", {"item_code": item.get("item_code")})
			for itemd in item_details:
				if itemd.package_variation == item.get("package_variation") and itemd.parent == item.get("item_code") and itemd.weight_per_unit == float(item.get("weight_per_unit")):
					cart_list[cart_list.index(item)]["selling_price"] = itemd.selling_price
					cart_list[cart_list.index(item)]["actual_price"] = itemd.actual_price
					# cart_list[cart_list.index(item)]["stock_uom"] = i.stock_uom
					cart_list[cart_list.index(item)]["item_total_selling_price"] = itemd.selling_price * float(item.get("qty"))
					cart_list[cart_list.index(item)]["item_total_actual_price"] = itemd.actual_price * float(item.get("qty"))
					cart_list[cart_list.index(item)]["item_total_saved_price"] = (itemd.actual_price * float(item.get("qty"))) - (itemd.selling_price * float(item.get("qty")))
					# cart_list[cart_list.index(item)]["package_variation"] = itemd.package_variation
		total_price = 0
		saved_price = 0
		actual_price = 0
		for item in cart_list:
			total_price = float(total_price) + float(item["selling_price"]) * float(item["qty"])
			actual_price = float(actual_price) + float(item["actual_price"]) * float(item["qty"])

		saved_price = actual_price - total_price

		return {
			"cart_items": cart_list,
			"total_price": total_price,
			"saved_price": saved_price,
			"actual_price": actual_price
		}
	else:
		return {
			"cart_items": {},
			"actual_price": 0,
			"total_price": 0,
			"saved_price": 0
		}
			# return value
		# return {"error": "User not logged in"}

@frappe.whitelist(allow_guest=True)
def get_search_items(text, category=None):
	filters={
		'item_name': ['like', '%{}%'.format(text)],
		"disabled": 0
	}
	if category:
		child_categories = get_descendants_of('Item Group', category, ignore_permissions=True)
		child_categories.append(category)
		filters.update({
			"item_group": ["in",child_categories]
		})
	if text:
		item_list = frappe.get_list("Item",filters=filters,fields=["item_code","item_name","description", "stock_uom", "item_group","image","brand"])
		for item in item_list:
			ancestors = get_ancestors_of('Item Group', item.item_group)
			attachments = get_attachments("Item", item.item_code)
			item_details = frappe.db.sql(""" SELECT id.package_variation,id.uom,id.weight_per_unit,id.actual_price,id.selling_price,id.item_image
										FROM `tabE2W Item Detail` id
										WHERE id.parent='%s' """%item.item_code,as_dict=1)
			if frappe.session.user and frappe.session.user != "Guest":
				for itemd in item_details:
					qty = get_item_qty_in_cart(item.item_code, itemd["package_variation"], itemd["weight_per_unit"])
					if qty:
						item_details[item_details.index(itemd)]["cart_quantity"] = qty
			item.update({
				"options": item_details,
				"images": attachments,
				"ancestors": ancestors
			})
		for item in item_list:
			for group in item.ancestors:
				if("Hidden" in group or "hidden" in group):
					del item_list[item_list.index(item)]

		return item_list

@frappe.whitelist()
def get_recently_ordered_items():
	user = frappe.session.user
	customer = frappe.get_value("Customer",{"account_manager": user})
	if customer:
		order_list = frappe.db.sql(""" SELECT si.name,sii.item_code,sii.item_name,sii.package_variation,sii.qty,sii.rate,sii.amount,sii.description,sii.image,si.posting_date
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
def create_address_and_contact(full_name, address_line1, address_line2, city, state, postal_code ,mobile_no, is_shipping_address, is_primary_address):
	if frappe.session.user and frappe.session.user != "Guest":
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
			"phone": mobile_no,
			"is_shipping_address": int(is_shipping_address),
			"is_primary_address": int(is_primary_address),
			"owner": frappe.session.user
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
def edit_address(name, full_name, address_line1, address_line2, city, state, postal_code ,mobile_no, is_shipping_address, is_primary_address):
	if frappe.session.user and frappe.session.user != "Guest":
		address = frappe.get_doc("Address", {"name": name})
		address.update({
			"address_title": full_name,
			"address_line1": address_line1,
			"address_line2": address_line2,
			"city": city,
			"country": 'India',
			"state": state,
			"pincode": postal_code,
			"phone": mobile_no,
			"is_shipping_address": int(is_shipping_address),
			"is_primary_address": int(is_primary_address)
		})
		address.save(ignore_permissions=True)
		return address
	else:
		return {"error": "User not logged in"}

@frappe.whitelist()
def get_address_details():
	if frappe.session.user and frappe.session.user != "Guest":
		customer = frappe.get_value("Customer",{"account_manager": frappe.session.user})
		add_list = frappe.db.sql(""" SELECT `tabAddress`.name, address_title, address_line1, address_line2, city, state, country, pincode, phone, is_shipping_address, is_primary_address FROM `tabAddress` INNER JOIN `tabDynamic Link` ON `tabAddress`.name=`tabDynamic Link`.parent WHERE `tabDynamic Link`.link_doctype="Customer" and `tabDynamic Link`.link_name='%s' """ %customer,as_dict=1)
		return add_list
	else:
		return {"error": "User not logged in"}

@frappe.whitelist(allow_guest=True)
def add_to_cart(item_code, qty, package_variation, uom, weight_per_unit, user_uid=None):
	if frappe.session.user and frappe.session.user != "Guest":
		if not frappe.db.exists("E2W Item Detail",{"parent": item_code, "weight_per_unit": weight_per_unit}):
			return {"error": "Item/Item Specification doesn't exist"}
		cart_status = check_cart(item_code, qty, package_variation, uom, weight_per_unit)
		if cart_status == False and int(qty) >= 1:
			rate = frappe.db.sql(""" SELECT selling_price,item_image FROM `tabE2W Item Detail`
											WHERE parent='%s' and weight_per_unit='%s'
											"""%(item_code,weight_per_unit),as_dict=1)
			if len(rate) > 0:
				cart = frappe.new_doc("E2W Cart")
				cart.update({
					"item_code": item_code,
					"qty": qty,
					"package_variation": package_variation,
					"uom": uom,
					"weight_per_unit": weight_per_unit,
					"owner": frappe.session.user,
					"rate": rate[0].selling_price,
					"item_image": rate[0].item_image
				})
				#cart.flags.ignore_mandatory=True
				cart.save()
				cart.submit()
				return {"message": "Item added" }
			else:
				frappe.local.response['http_status_code'] = 404
				return {"error": "Item/Item Specification doesn't exist"}
		elif cart_status == False and int(qty) == 0:
			return {"message": "Item removed" }
		else:
			return {"message": "Quantity Updated" }
	else:
		if user_uid:
			key = user_uid
			rate = frappe.db.sql(""" SELECT id.selling_price,id.item_image,id.uom FROM `tabE2W Item Detail` id, `tabItem` i
											WHERE i.name='%s' and id.parent=i.name and id.weight_per_unit='%s'
											"""%(item_code,weight_per_unit),as_dict=1)
			status = False
			index = 0
			item_doc = frappe.get_doc("Item", item_code)
			if not frappe.cache().get_value(key):
				value = []
				value.append({
					"item_code": item_code,
					"item_name": item_doc.item_name,
					"description": item_doc.description,
					"qty": qty,
					"package_variation": package_variation,
					"uom": rate[0].uom,
					"weight_per_unit": weight_per_unit,
					"rate": rate[0].selling_price,
					"item_image": rate[0].item_image
				})
				message = "Item added"
			else:
				value = frappe.cache().get_value(key)
				for v in value:
					if v.get("item_code") == item_code and v.get("package_variation") == package_variation and v.get("weight_per_unit") == weight_per_unit and v.get("uom") == uom:
						v.update({
							"qty": qty
						})
						status = True
				if status == False:
					value.append({
						"item_code": item_code,
						"item_name": item_doc.item_name,
						"description": item_doc.description,
						"qty": qty,
						"package_variation": package_variation,
						"uom": rate[0].uom,
						"weight_per_unit": weight_per_unit,
						"rate": rate[0].selling_price,
						"item_image": rate[0].item_image
					})
					message = "Item added"
				else:
					message = "Quantity Updated"

			frappe.cache().set_value(key, value)
			return {"message": message}
		else:
			return {
				"error": "UserUID is mandatory."
			}
		# return {"error": "User not logged in"}

def check_cart(item_code, qty, package_variation, uom, weight_per_unit):
	if frappe.session.user and frappe.session.user != "Guest":
		if frappe.db.exists("E2W Cart",{"item_code": item_code,"package_variation": package_variation,"uom": uom, "weight_per_unit": weight_per_unit,"status": "Pending","owner":frappe.session.user,"docstatus": 1}):
			cart = frappe.get_doc("E2W Cart",{"item_code": item_code,"package_variation": package_variation, "uom": uom ,"weight_per_unit": weight_per_unit,"status": "Pending","owner":frappe.session.user, "docstatus": 1})
			if int(qty) <= 0:
				cart.cancel()
				cart.delete()
				return False
			else:
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


def get_item_qty_in_cart(item_code, package_variation, weight_per_unit):
	if frappe.session.user and frappe.session.user != "Guest":
		if frappe.db.exists("E2W Cart",{"item_code": item_code,"package_variation": package_variation,"weight_per_unit": weight_per_unit,"status": "Pending","owner":frappe.session.user,"docstatus": 1}):
			cart = frappe.get_doc("E2W Cart",{"item_code": item_code,"package_variation": package_variation,"weight_per_unit": weight_per_unit,"status": "Pending","owner":frappe.session.user, "docstatus": 1})
			return cart.qty
		else:
			return False
	else:
		return False

@frappe.whitelist()
def checkout(address_name, items_list=None):
	if frappe.session.user and frappe.session.user != "Guest":
		if items_list:
			items_list = json.loads(items_list)
			for i in items_list:
				cart_status = add_to_cart(i.get("item_code"), i.get("qty"), i.get("package_variation"), i.get("uom"), i.get("weight_per_unit"))
				if cart_status != 'Added to cart':
					return cart_status
		items = get_cart_items()["cart_items"]
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
					rate = frappe.db.sql(""" SELECT selling_price,uom FROM `tabE2W Item Detail`
											WHERE parent='%s' and weight_per_unit='%s'
											"""%(item.name,i.get("weight_per_unit")),as_dict=1)

					if rate and frappe.db.exists("E2W Cart",{"item_code": i.get("item_code"),"package_variation":i.get("package_variation"),"uom": i.get("uom"),"weight_per_unit":i.get("weight_per_unit"),"qty": i.get("qty"),"status": "Pending","docstatus": 1,"owner":frappe.session.user}):
						cart_doc = frappe.get_doc("E2W Cart",{"item_code": i.get("item_code"),"package_variation":i.get("package_variation"),"uom": i.get("uom"),"weight_per_unit":i.get("weight_per_unit"),"qty": i.get("qty"),"status": "Pending","docstatus":1,"owner": frappe.session.user})
						#frappe.db.set_value("E2W Cart",cart_doc.name,"status", "Ordered")
						si_doc.append("items",{
								"item_code": i.get("item_code"),
								"item_name": item.item_name,
								"package_variation": i.get("package_variation"),
								"description": item.description,
								"qty": i.get("qty"),
								"uom": cart_doc.uom,
								"stock_uom": cart_doc.uom,
								"weight_per_unit": cart_doc.weight_per_unit,
								"image": item.image,
								"rate": float(rate[0].selling_price),
								"amount": float(rate[0].selling_price) * float(i.get("qty"))
						})
						cart_doc.cancel()
						cart_doc.delete()
				si_doc.flags.ignore_mandatory = True
				si_doc.save(ignore_permissions=True) #Need to be security tested
				si_doc.submit()
				msg = 'Hi there, Welcome to easy2way.shop. Your order on easy2way.shop has been successfully placed. Your order ID is {0}. Order value is {1} payable through cash on delivery. Thank you for shopping with easy2way.shop.'.format(si_doc.name, "INR " + str(si_doc.net_total))
				u = frappe.get_doc("User", {"name": frappe.session.user})
				send_sms([u.mobile_no], msg)
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
									WHERE enable=1 ORDER BY order_no""", as_dict=1)
	if cards_list:
		for c in cards_list:
			cards.append(c.card)
	return cards

@frappe.whitelist(allow_guest=True)
def get_scroll_text():
	st_list = []
	scroll_texts = frappe.db.sql(""" SELECT text FROM `tabE2W Scroll Text`
									WHERE enable=1 ORDER BY order_no""", as_dict=1)
	if scroll_texts:
		for st in scroll_texts:
			st_list.append(st.text)
	return st_list

@frappe.whitelist(allow_guest=True)
def get_item_groups():
	result = []
	parent_item_groups = frappe.get_list("Item Group",filters={"parent_item_group": "All Item Groups"},fields=["name", "is_group", "weightage"], order_by='weightage asc')
	for ig in parent_item_groups:
		child_item_groups = []
		if ig.is_group == 1:
			child_item_groups = frappe.db.sql(""" SELECT name as sub_category_name, weightage FROM `tabItem Group`
												WHERE parent_item_group='%s' ORDER BY weightage ASC """%ig.name, as_dict=1)
		result.append({
			"name": ig.name,
			"weightage": ig.weightage,
			"sub_categories": child_item_groups
		})
	return result


@frappe.whitelist(allow_guest=True)
def get_home_screen_details():
	hs_list = frappe.get_list("E2W Home Screen",{"enable": 1},["name","type","heading","heading_image"],order_by="order_no asc")
	for hs in hs_list:
		hs_details = frappe.db.sql(""" SELECT type,item_or_category,item_image FROM `tabE2W Home Screen Detail`
		 								WHERE parent='%s' ORDER BY idx asc """% (hs.name), as_dict=1)
		for hsd in hs_details:
			ancestors = []
			descendants = []
			if hsd.type == "Item Group":
				ancestors = get_ancestors_of("Item Group", hsd.item_or_category)
				descendants = get_descendants_of("Item Group", hsd.item_or_category, ignore_permissions=True)
			hsd.update({
				"ancestors": ancestors,
				"descendants": descendants
			})
		hs.update({
			"grid_details": hs_details
		})
	return hs_list

@frappe.whitelist(allow_guest=True)
def get_siblings(category):
	parent_item_group = frappe.get_value("Item Group",{"name": category},["parent_item_group"])
	siblings_list = frappe.db.sql(""" SELECT name FROM `tabItem Group`
										WHERE parent_item_group='%s' """%parent_item_group,as_dict=1)
	result = []
	for s in siblings_list:
		result.append(s.name)
	return result
