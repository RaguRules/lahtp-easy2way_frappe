# Contributors. see license.txt
import frappe, json
import random
from easy2way.easy2way.doctype.sms_center.sms_center import send_sms
from frappe.utils import cint
from easy2way.easy2way.auth import get_cart_items, add_to_cart

@frappe.whitelist(allow_guest=True)
def get(mobile_no=None):
	def generate_otp():
		otp = ''.join(["{}".format(random.randint(0, 9)) for i in range(0, otp_length)])
		return {"id": key, "otp": otp, "timestamp": str(frappe.utils.get_datetime().utcnow())}

	if not mobile_no:
		mobile_no = frappe.form_dict.get("mobile_no")
		if not mobile_no:
			frappe.throw("NOMOBILE", exc=LookupError)

	u = frappe.db.get_value("User", {"mobile_no": mobile_no}, "name")

	if not u:
		frappe.throw("USERNOTFOUND", exc=LookupError)

	key = mobile_no + "_otp"
	otp_length = 6 # 6 digit OTP
	rs = frappe.cache()

	if rs.get_value(key) and otp_not_expired(rs.get_value(key)): # check if an otp is already being generated
		otp_json = rs.get_value(key)
	else:
		otp_json = generate_otp()
		rs.set_value(key, otp_json)

	#Your Easy2Way Shop OTP is 888888. This will be valid only for 5 mins. Please do not share this OTP with anyone else over Phone or Messages.
	#sendsms
	msg = 'Your Easy2Way Shop OTP is ' + str(otp_json.get("otp")) + '. This will be valid only for 5 mins. Please do not share this OTP with anyone else over Phone or Messages.'
	send_sms([mobile_no], msg)

	return "OTPGENERATED:{0}".format(otp_json.get("otp")) # MUST DISABLE IN PRODUCTION!!

@frappe.whitelist(allow_guest=True)
def authenticate(otp=None, mobile_no=None, client_id=None, user_uid=None):
	if not otp:
		otp = frappe.form_dict.get("otp")
		if not otp:
			frappe.throw("NOOTP")

	if not mobile_no:
		mobile_no = frappe.form_dict.get("mobile_no")
		if not mobile_no:
			frappe.throw("NOMOBILENO")

	if not client_id:
		client_id = frappe.form_dict.get("client_id")
		if not client_id:
			frappe.throw("NOCLIENTID")

	rs = frappe.cache()
	otp_json = rs.get_value("{0}_otp".format(mobile_no))

	if otp_json is None or otp_json.get("otp") != otp:
		frappe.throw("OTPNOTFOUND")

	if otp_json is not None and not otp_not_expired(otp_json):
		frappe.throw("OTPEXPIRED")

	otoken = create_bearer_token(mobile_no, client_id)

	out = {
		"access_token": otoken.access_token,
		"refresh_token": otoken.refresh_token,
		"expires_in": otoken.expires_in,
		"scope": otoken.scopes
	}

	# Delete consumed otp
	rs.delete_key(mobile_no + "_otp")

	if user_uid:
		cache_cart_items = []
		user = frappe.get_value("User",{"mobile_no": mobile_no},["name"])
		cache_cart_items = get_cart_items(user_uid)["cart_items"]
		if len(cache_cart_items) > 0:
			for cci in cache_cart_items:
				frappe.session.user = user
				m = add_to_cart(cci.get("item_code"), cci.get("qty"), cci.get("package_variation"), cci.get("uom"), cci.get("weight_per_unit"))
				frappe.msgprint(m)

		frappe.cache().delete_key(user_uid)
	frappe.local.response = frappe._dict(out)

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
	if otp_json is None:
		return False
	diff = frappe.utils.get_datetime().utcnow() - frappe.utils.get_datetime(otp_json.get("timestamp"))
	if int(diff.seconds) / 60 >= 10:
		flag = False

	return flag