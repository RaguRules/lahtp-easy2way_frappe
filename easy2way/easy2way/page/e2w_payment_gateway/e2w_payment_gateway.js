frappe.pages['e2w-payment-gateway'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'E2W Payment Gateway',
		single_column: true
	});
    
	page.main.html(frappe.render_template("e2w_payment_gateway", {}));
    make_payment();
	// $('button').click( function (){ razorpay.createPayment(...) })
}

// frappe.provide("frappe.checkout");

function make_payment(ticket=null) {
    var options = {
        "name": "E2W Payment Gateway",
        "description": "E2W Payment Gateway",
        // "image": "<CHECKOUT MODAL LOGO>",
        "prefill": {
            "name": "Kutty",
            "email": "e2wuser_2f001d5fc3d5b4ada0ce26a6f1b5df8b@server.local",
            "contact": "9597705104"
        },
        "theme": {
            "color": "red"
        },
        "doctype": "Sales Invoice", // Mandatory
        "docname": "ACC-SINV-2021-00092" // Mandatory
    };

    razorpay = new frappe.checkout.razorpay(options)
    razorpay.on_open = () => {
        console.log("hello")
    }
    razorpay.on_success = () => {
        // SCRIPT TO RUN ON PAYMENT SUCCESS
    }
    razorpay.on_fail = () => {
        // SCRIPT TO RUN ON PAYMENT FAILURE
    }
    razorpay.init() // Creates the order and opens the modal
}
