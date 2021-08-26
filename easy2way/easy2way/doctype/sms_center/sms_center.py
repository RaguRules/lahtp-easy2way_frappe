# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe
import binascii
import os
import base64
import datetime
import string

from frappe.utils import cstr, nowdate
from frappe import msgprint, _
from frappe.model.document import Document

class SMSCenter(Document):
	def create_receiver_list(self):
		rec_list = list()
		if self.send_to == "All Contacts":
			rec = frappe.get_all("Persons", fields=["mobile_no"])
			for d in rec:
				rec_list.append(d['mobile_no'])
		# if self.send_to == "By Group":
		# 	group = frappe.get_doc('Group', self.group)
		# 	for member in group.person_list:
		# 		person = frappe.get_doc('Persons', member.person)
		# 		rec_list.append(person.mobile_no)

		self.receiver_list = "\n".join(list(set(rec_list))) #To ensure only unique numbers come out.

	def get_receiver_nos(self):
		receiver_nos = []
		if self.receiver_list:
			for d in self.receiver_list.split('\n'):
				receiver_no = d
				if '-' in d:
					receiver_no = receiver_no.split('-')[1]
				if receiver_no.strip():
					receiver_nos.append(cstr(receiver_no).strip())
		else:
			msgprint(_("Receiver List is empty. Please create Receiver List"))

		return receiver_nos

	def send_sms(self):
		sms_enabled = frappe.db.get_single_value('SMS Center', 'sms_enable')
		if sms_enabled:
			if(len(self.message) > 480):
				frappe.throw(_("Message length exceeds 480 characters and cannot be processed"))
			receiver_list = []
			if not self.message:
				msgprint(_("Please enter message before sending"))
			else:
				receiver_list = self.get_receiver_nos()
			if receiver_list:
				log = send_sms(receiver_list, cstr(self.message.encode('utf-8')))
				delist = '<br>'.join(receiver_list)
				msgprint(_("Message: <br><b>"+self.message.replace('\n', '<br>')+"</b><br><br>Queued for sending to the following "+str(len(receiver_list))+" recipient(s):<br><br>"+delist+"<br><br> Click here to know delivery status &nbsp; <span><a class='btn btn-primary btn-sm' target='_blank' href='http://95.111.196.14/desk#Form/SMS Log/"+log.name+"'>View "+log.name+"</a></span>"))
				return log
		else:
			frappe.throw(_("SMS Sending has been disabled. You cannot send SMS. Enable it before continuing."))

def ascify(str):
	import string
	return filter(lambda x: x in string.printable, str)

def validate_receiver_nos(receiver_list):
	validated_receiver_list = []
	for d in receiver_list:
		# remove invalid character
		for x in [' ', '+', '-', '(', ')']:
			d = d.replace(x, '')

		validated_receiver_list.append(d)

	if not validated_receiver_list:
		throw(_("Please enter valid mobile nos"))

	return validated_receiver_list


def get_sender_name():
	"returns name as SMS sender"
	sender_name = 'ETOWSP'
	if len(sender_name) > 6 and \
			frappe.db.get_default("country") == "India":
		throw("""As per TRAI rule, sender name must be exactly 6 characters.
			Kindly change sender name in Setup --> Global Defaults.
			Note: Hyphen, space, numeric digit, special characters are not allowed.""")
	return sender_name

@frappe.whitelist()
def get_contact_number(contact_name, value, key):
	"returns mobile number of the contact"
	number = frappe.db.sql("""select mobile_no, phone from tabContact where name=%s and %s=%s""" %
		('%s', frappe.db.escape(key), '%s'), (contact_name, value))
	return number and (number[0][0] or number[0][1]) or ''

@frappe.whitelist()
def send_sms(receiver_list, msg, sender_name = '', dialog = '', justlog=''):
	import json
	if isinstance(receiver_list, str):
		receiver_list = json.loads(receiver_list)
		if not isinstance(receiver_list, list):
			receiver_list = [receiver_list]

	receiver_list = validate_receiver_nos(receiver_list)

	arg = {
		'receiver_list' : receiver_list,
		'message'		: msg,
		'sender_name'	: sender_name or get_sender_name(),
		'show_dialog'	: dialog,
		'justlog'	: justlog
	}

	return send_via_gateway(arg)

def send_via_gateway(arg):
	customID = binascii.hexlify(os.urandom(16))
	args = {'msg': arg.get('message')}
	success_list = []
	for d in arg.get('receiver_list'):
		args['phone'] = d
		if not arg.get('justlog'):
			status = send_request(args, customID)
			if status >= 200 and status < 300:
				success_list.append(d)
		else:
			success_list.append(d)

	if len(success_list) > 0 and arg.get('show_dialog'):
		args.update(arg)
		frappe.msgprint(_("SMS sent to following numbers: {0}").format("\n" + "\n".join(success_list)))
		return create_sms_log(args, success_list, customID)

	elif len(success_list) > 0:
		args.update(arg)
		return create_sms_log(args, success_list, customID)

def send_request(params, customID):
	sms_enabled = frappe.db.get_single_value('SMS Center', 'sms_enable')
	if sms_enabled:
		# nums = filter(lambda x: x in string.printable, params.get('phone'))
		# msg = filter(lambda x: x in string.printable, params.get('msg'))
		nums = params.get('phone')
		msg = params.get('msg')
		sample_string_bytes = msg.encode("ascii")   
		base64_bytes = base64.b64encode(sample_string_bytes) 
		base64_string = base64_bytes.decode("ascii") 
		os.system("sendsms "+str(nums)+" \""+str(base64_string)+"\" ")
		return 200
	else:
		return 500

# Create SMS Log
# =========================================================
def create_sms_log(args, sent_to, customID):
	sl = frappe.new_doc('SMS Log')
	sl.sender_name = args['sender_name']
	sl.sent_on = nowdate()
	sl.message = args['message']
	sl.no_of_requested_sms = len(args['receiver_list'])
	sl.no_of_sent_sms = len(sent_to)
	sl.flags.ignore_permissions = True
	sl.custom_id = customID
	for number in args['receiver_list']:
		sl.append('delivery_log', {'number': number, 'status': 'Q', 'reason': 'Messaged sent and is en route.', 'datetime': datetime.datetime.now() +datetime.timedelta(hours=5, minutes=30)})
	sl.save()
	return sl
