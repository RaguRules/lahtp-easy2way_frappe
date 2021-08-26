// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on('SMS Center', {
    onload: function(frm) {
        frm.disable_save();
        $.extend(frm.cscript, {
            message: function() {
                var total_characters = this.frm.doc.message.length;
                var total_msg = 1;

                if (total_characters > 160) {
                    total_msg = cint(total_characters / 160);
                    total_msg = (total_characters % 160 == 0 ? total_msg : total_msg + 1);
                }

                this.frm.set_value("total_characters", total_characters);
                this.frm.set_value("total_messages", this.frm.doc.message ? total_msg : 0);
            }
        });
    },
    sms_enable: function(frm) {
        frm.save();
    }
});