"""Demo data: the Northwind Outdoor store from the prototype. Run `python -m app.seed --reset` to rebuild."""
from __future__ import annotations

import sys

from . import db
from .agent.tools import DEFAULT_SETTINGS
from .db import ago, dumps

H = lambda n: n * 60  # noqa: E731
D = lambda n: n * 1440  # noqa: E731


def seed_if_empty() -> None:
    if db.get("SELECT COUNT(*) AS n FROM channels")["n"] == 0:
        seed()


def seed() -> None:
    for t in ("agent_runs", "alerts", "approvals", "messages", "conversations", "sms_messages", "payment_refunds", "payments", "orders", "identities", "customers", "products", "channels", "policies", "settings", "integrations", "webhook_log"):
        db.run(f"DELETE FROM {t}")

    with db.tx():
        # ---------------------------------------------------------------- channels
        def ch(id_, kind, name, handle, status, health, alert, last_min):
            db.run("INSERT INTO channels(id,kind,name,handle,status,health,alert,last_message_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   [id_, kind, name, handle, status, dumps(health), alert, ago(last_min), ago(D(90))])

        ch("ch_ms", "ms", "Facebook Page", "Northwind Outdoor", "ok", [["Webhook", "Receiving", "ok"], ["Permissions", "5 of 5 granted", "ok"], ["Connected by", "Farhana Akter", ""]], None, 2)
        ch("ch_wa", "wa", "WhatsApp Business", "+880 1XXX-XXXXXX", "ok", [["Webhook", "Receiving", "ok"], ["Number", "Registered for Cloud API", "ok"], ["Payment method", "On file with Meta", "ok"]], None, 4)
        ch("ch_ig", "ig", "Instagram", "@northwind.outdoor", "warn", [["Webhook", "Receiving", "ok"], ["Permissions", "2 of 2 granted", "ok"], ["Access token", "Expires in 6 days", "warn"]],
           "The access token expires in 6 days. Reconnect before then so messages keep arriving.", 11)
        ch("ch_web", "web", "Web chat", "northwind.example", "ok", [["Widget", "Installed", "ok"], ["Languages", "বাংলা, English", ""]], None, 3)
        ch("ch_ms2", "ms", "Facebook Page", "Trail Club Dhaka", "danger", [["Webhook", "Switched off", "danger"], ["Permissions", "5 of 5 granted", "ok"], ["Connected by", "Farhana Akter", ""]],
           "Meta switched the webhook off after repeated delivery failures. Messages are not arriving. Reconnect to fix it.", D(1))

        # ---------------------------------------------------------------- products (sample catalog)
        def prod(id_, sku, name, variant, price, stock, sold, art, desc, kw):
            db.run("INSERT INTO products(id,sku,name,variant,price,stock,sold30,art,description,keywords) VALUES(?,?,?,?,?,?,?,?,?,?)", [id_, sku, name, variant, price, stock, sold, art, desc, kw])

        prod("bottle", "NW-TB2-NVY", "Trail Bottle 2L", "Navy", 1450, 6, 38, "bottle", "Insulated stainless steel, keeps drinks cold for 24 hours. Leak-proof lid. 2 litre.", "bottle botol বোতল water flask trail")
        prod("tent", "NW-RL3-ORG", "Ridgeline 3 Tent", "Orange, 3 person", 14500, 3, 9, "tent", "Fits 3 adults, weighs 3.4 kg. Waterproof rainfly with 3000 mm rating and taped seams. Sets up in about 10 minutes.", "tent tabu তাঁবু ridgeline camping 3 person waterproof")
        prod("boot", "NW-RB-BRN-9", "Ridge Boot", "Brown, size 9", 6900, 41, 22, "boot", "Leather hiking boot with grippy outsole. Waterproof membrane. True to size.", "boot boots shoe shoes juta জুতা hiking ridge")
        prod("jacket", "NW-AS-GRN-M", "Alpine Shell Jacket", "Green, M", 8500, 0, 15, "jacket", "Lightweight windproof and waterproof shell with a packable hood.", "jacket jaket জ্যাকেট alpine shell rain")

        # ---------------------------------------------------------------- policies
        for k, t, b in [
            ("returns", "Returns policy 2.1", "Damaged or wrong items can be returned or replaced within 7 days of delivery. Unworn items can be returned within 7 days; a return courier charge of ৳100 applies for change-of-mind returns. Refunds go back to the original payment method after a teammate approves."),
            ("exchange", "Exchange policy 3.2", "Unworn items can be exchanged for another size within 7 days of delivery, subject to stock."),
            ("pricing", "Pricing policy 1.4", "Price matches are considered for identical items from authorized sellers, with a link as proof. Maximum adjustment ৳1,000. Only a teammate can approve a price match."),
            ("shipping", "Shipping policy 4.0", "We ship with Steadfast, Pathao, RedX and Paperfly. Inside Dhaka usually 1 day (৳60 to ৳70). Outside Dhaka 2 to 4 days (৳110 to ৳130). Orders confirmed before 3 pm ship the same day."),
            ("payment", "Payment policy 5.1", "Cash on delivery in all districts, confirmed by phone before booking. bKash, Nagad and cards are paid through official payment links only. Staff never ask for a PIN, OTP or card number."),
        ]:
            db.run("INSERT INTO policies(key,title,body) VALUES(?,?,?)", [k, t, b])

        # ---------------------------------------------------------------- customers
        def cust(id_, name, phone, lang, area, verified, tags, hue, ext, kind, age_days):
            db.run("INSERT INTO customers(id,name,phone,lang,area,verified,tags,hue,external_id,channel_kind,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   [id_, name, phone, lang, area, verified, dumps(tags), hue, ext, kind, ago(D(age_days))])

        cust("c_nusrat", "Nusrat Jahan", "+8801712340042", "bn", "Dhanmondi, Dhaka", "otp", ["Returning", "Outdoor"], 168, "ms_nusrat", "ms", 600)
        cust("c_rakib", "Rakib Hasan", "+8801812340007", "bl", "Agrabad, Chattogram", "phone", ["Returning"], 330, "8801812340007", "wa", 300)
        cust("c_sadia", "Sadia Rahman", None, "bl", "Sylhet", "none", ["Prospect"], 32, "ms_sadia", "ms", 0)
        cust("c_tahmid", "Tahmid Islam", "+8801911340081", "bl", "Mirpur, Dhaka", "phone", ["Return request"], 18, "8801911340081", "wa", 150)
        cust("c_imran", "Imran Khan", None, "en", "Rajshahi", "none", ["Restock alert"], 215, "ig_imran", "ig", 0)
        cust("c_guest", "Guest 8831", None, "bl", "Unknown", "none", [], 200, "web_8831", "web", 0)
        cust("c_mahin", "Mahin Chowdhury", "+8801612340011", "en", "Uttara, Dhaka", "none", ["bKash"], 260, "web_mahin", "web", 30)
        cust("c_nabila", "Nabila Khan", "+8801512340099", "bn", "Sylhet", "none", ["Cash on delivery"], 300, "ig_nabila", "ig", 20)
        cust("c_mou", "Mou Akter", "+8801312340055", "bn", "Banani, Dhaka", "none", ["Payment failed"], 200, "ms_mou", "ms", 40)
        cust("c_sumon", "Sumon Ahmed", "+8801912340033", "en", "Rajshahi", "none", [], 90, "web_sumon", "web", 25)

        db.run("INSERT OR IGNORE INTO identities(kind, external_id, customer_id) SELECT channel_kind, external_id, id FROM customers WHERE external_id IS NOT NULL")

        # ---------------------------------------------------------------- orders
        def line(sku, qty):
            p = db.get("SELECT * FROM products WHERE sku=?", [sku])
            return {"sku": sku, "name": p["name"], "variant": p["variant"], "price": p["price"], "qty": qty}

        def order(no, cust_id, kind, age_min, items, ship, zone, addr, pay, ful, stage, times, courier=None, scans=(), log=(), ret=False):
            db.run(
                "INSERT INTO orders(id,number,customer_id,channel_kind,items,shipping,zone,address,pay_status,pay_method,pay_ref,fulfillment,stage,times,courier,scans,log,return_requested,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [no, no, cust_id, kind, dumps([line(s, q) for s, q in items]), ship, zone, addr, pay[0], pay[1], pay[2], ful, stage, dumps([ago(m) for m in times]),
                 dumps(courier) if courier else None, dumps([{"x": x, "t": ago(m)} for x, m in scans]), dumps([{"c": c, "x": x, "s": s, "t": ago(m)} for c, x, s, m in log]), 1 if ret else 0, ago(age_min)])

        order("#1044", "c_mahin", "web", 95, [("NW-RL3-ORG", 1), ("NW-TB2-NVY", 2)], 0, "dhaka", "House 14, Road 7, Uttara Sector 4, Dhaka 1230", ("Paid", "bKash 01712-XXXXXX", "BK8A2F91XQ"), "Unfulfilled", 1, [95, 95],
              log=[("sms", "অর্ডার #1044 পেয়েছি। ধন্যবাদ!", "Delivered", 95)])
        order("#1043", "c_nabila", "ig", 160, [("NW-RB-BRN-9", 1)], 130, "out", "Zindabazar, Sylhet 3100", ("Pending", "Cash on delivery", ""), "Unfulfilled", 0, [160],
              log=[("sms", "অর্ডার #1043 পেয়েছি। ফোনে কনফার্ম করা হবে।", "Delivered", 160)])
        order("#1042", "c_rakib", "wa", D(2) + 60, [("NW-RB-BRN-9", 1)], 130, "out", "Agrabad, Chattogram 4100", ("Paid", "Nagad 01812-XXXXXX", "NG2K77PQ41"), "In transit", 3,
              [D(2) + 60, D(2) + 60, D(2) - 180, D(1) + 30], {"name": "Steadfast", "track": "SF-26110841", "eta": "Tomorrow"},
              [("Left Dhaka hub for Chattogram", D(1) + 30), ("Picked up from Northwind", D(2) - 240), ("Parcel created", D(2) - 180)],
              [("wa", "Shipped, with tracking link", "Delivered", D(2) - 180), ("sms", "আপনার অর্ডার #1042 শিপ হয়েছে। ট্র্যাকিং: SF-26110841", "Delivered", D(2) - 180)])
        order("#1041", "c_tahmid", "wa", D(10), [("NW-TB2-NVY", 1)], 70, "dhaka", "Section 10, Mirpur, Dhaka 1216", ("Paid", "Card via SSLCommerz", "SSL-4F20A9"), "Delivered", 5,
              [D(10), D(10), D(9), D(9) - 120, D(6), D(6) - 160], {"name": "Pathao", "track": "PT-87740192", "eta": "Delivered"}, [("Delivered to customer", D(6) - 160)],
              [("wa", "Return update (template)", "Sent", D(3)), ("sms", "আপনার অর্ডার ডেলিভারি হয়েছে। ধন্যবাদ!", "Delivered", D(6) - 160)], ret=True)
        order("#1038", "c_nusrat", "ms", D(14), [("NW-TB2-NVY", 3)], 70, "dhaka", "Road 5, Dhanmondi, Dhaka 1209", ("Paid", "Cash on delivery (collected)", ""), "Delivered", 5,
              [D(14), D(9), D(13), D(13) - 90, D(9) - 200, D(9) - 150], {"name": "Steadfast", "track": "SF-26102217", "eta": "Delivered"}, [("Delivered, cash collected", D(9) - 150)],
              [("sms", "আপনার অর্ডার ডেলিভারি হয়েছে। ধন্যবাদ!", "Delivered", D(9) - 150)])
        order("#1036", "c_sumon", "web", D(16), [("NW-RL3-ORG", 1)], 130, "out", "Rajshahi Sadar, Rajshahi 6000", ("Refunded", "bKash 01912-XXXXXX", "BK7C19D2LM"), "Cancelled", 1, [D(16), D(16)],
              log=[("sms", "আপনার ৳14,630 রিফান্ড করা হয়েছে।", "Delivered", D(15))])
        order("#1035", "c_mou", "ms", D(17), [("NW-AS-GRN-M", 1)], 70, "dhaka", "Banani, Dhaka 1213", ("Failed", "Card via SSLCommerz", ""), "Unfulfilled", 0, [D(17)],
              log=[("sms", "পেমেন্ট হয়নি। আবার চেষ্টা করতে লিংকে যান।", "Delivered", D(17))])
        order("#1029", "c_nabila", "ig", D(8), [("NW-RB-BRN-9", 1)], 130, "out", "Zindabazar, Sylhet 3100", ("Paid", "bKash 01512-XXXXXX", "BK3D00AA21"), "Delivered", 5,
              [D(8), D(8), D(7), D(7) - 100, D(5), D(4) + 100], {"name": "Pathao", "track": "PT-87711900", "eta": "Delivered"}, [("Delivered to customer", D(4) + 100)])
        order("#0977", "c_nusrat", "ms", D(90), [("NW-TB2-NVY", 2)], 0, "dhaka", "Road 5, Dhanmondi, Dhaka 1209", ("Paid", "bKash 01712-XXXXXX", "BK1100AA09"), "Delivered", 5,
              [D(90), D(90), D(89), D(89), D(88), D(88)], {"name": "Steadfast", "track": "SF-25081120", "eta": "Delivered"})

        # ---------------------------------------------------------------- conversations
        def conv(id_, cust_id, chan, mode, preview, last_min, *, status="open", unread=0, handoff=None, window=None, summary=None, pending=None):
            if window is None:
                win = ago(-22 * 60)
            elif window == 0:
                win = ago(60)
            else:
                win = ago(-window)
            db.run(
                "INSERT INTO conversations(id,customer_id,channel_id,mode,status,unread,preview,last_message_at,handoff_reason,window_expires_at,summary,pending,cart,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [id_, cust_id, chan, mode, status, unread, preview, ago(last_min), handoff, win, summary, dumps(pending) if pending else None, "[]", ago(last_min + 30)])

        def msg(cid, role, mins, text, *, tr=None, author=None, meta=None, delivery=None):
            db.run("INSERT INTO messages(conversation_id,role,author,text,translation,meta,delivery,created_at) VALUES(?,?,?,?,?,?,?,?)", [cid, role, author, text, tr, dumps(meta) if meta else None, delivery, ago(mins)])

        def ev(cid, mins, icon, label, detail=None, tone=None):
            msg(cid, "event", mins, label, meta={"icon": icon, "detail": detail, "tone": tone})

        conv("cv_nusrat", "c_nusrat", "ch_ms", "hybrid", "একটা কার্টে দিয়ে দিন প্লিজ", 3, unread=1,
             summary="Nusrat writes in Bangla and wants the Trail Bottle 2L in navy. It is in stock (6 left). She asked to add one to her cart, and the reply is waiting for your approval.",
             pending={"text": "জি আপু, ১টি ট্রেইল বোতল ২ লিটার (নেভি) কার্টে যোগ করেছি। সাবটোটাল ৳১,৪৫০। ক্যাশ অন ডেলিভারি নাকি বিকাশে পেমেন্ট করবেন?",
                      "translation": "Added 1 Trail Bottle 2L (navy) to your cart. Subtotal ৳1,450. Will you pay by cash on delivery or bKash?",
                      "actions": [{"tool": "add_to_cart", "input": {"sku": "NW-TB2-NVY", "qty": 1}}], "productSku": "NW-TB2-NVY", "createdAt": ago(2)})
        msg("cv_nusrat", "customer", 5, "আসসালামু আলাইকুম, নেভি ব্লু রঙের ২ লিটারের ট্রেইল বোতল আছে?", tr="Assalamu alaikum, do you have the 2L Trail Bottle in navy blue?", author="Nusrat Jahan")
        ev("cv_nusrat", 4.8, "search", "Searched the catalog", "search_products · 3 results · 142 ms")
        msg("cv_nusrat", "assistant", 4.5, "ওয়ালাইকুম আসসালাম আপু! জি, ট্রেইল বোতল ২ লিটার নেভি রঙে আছে। এখন স্টকে ৬টি আছে।", tr="Wa alaikum assalam! Yes, the 2L Trail Bottle is available in navy. 6 in stock.", author="Assistant", meta={"product": "NW-TB2-NVY"}, delivery="Sent")
        msg("cv_nusrat", "customer", 3, "একটা কার্টে দিয়ে দিন প্লিজ", tr="Please add one to my cart", author="Nusrat Jahan")
        ev("cv_nusrat", 2.5, "cart", "Prepared a cart change", "add_to_cart · waiting for approval")

        conv("cv_rakib", "c_rakib", "ch_wa", "agent", "thik ache, thanks bhai", 12, status="resolved", window=23 * 60,
             summary="Rakib wrote in Banglish asking where order #1042 is. The assistant found it in transit with Steadfast and sent the tracking link, also in Banglish. Resolved.")
        msg("cv_rakib", "customer", 15, "bhai amar order ta kothay? order #1042", tr="Bro, where is my order? Order #1042", author="Rakib Hasan")
        ev("cv_rakib", 14.8, "truck", "Looked up order #1042", "get_order_status · verified by phone · 96 ms")
        msg("cv_rakib", "assistant", 14.5, "Assalamu alaikum Rakib bhai! Apnar order #1042 gotokal Steadfast e pathano hoyeche. Ajke ba kal Chattogram e pouchabe. Tracking: SF-26110841",
            tr="Hello Rakib! Your order #1042 was handed to Steadfast yesterday. It should reach Chattogram today or tomorrow. Tracking: SF-26110841", author="Assistant", delivery="Read")
        msg("cv_rakib", "customer", 12, "thik ache, thanks bhai", tr="OK, thanks bro", author="Rakib Hasan")
        ev("cv_rakib", 11.9, "check", "Resolved by the assistant", None, "ok")

        conv("cv_sadia", "c_sadia", "ch_ms", "agent", "Tent ta ki waterproof?", 28,
             summary="Sadia is comparing tents for three people and asked about delivery to Sylhet, then whether the tent is waterproof. The assistant is replying.")
        msg("cv_sadia", "customer", 31, "Ridgeline tent ta 3 jon er jonno thik hobe? Sylhet e delivery koto din lagbe?", tr="Is the Ridgeline tent okay for 3 people? How many days for delivery to Sylhet?", author="Sadia Rahman")
        ev("cv_sadia", 30.8, "search", "Searched the catalog", "search_products · 2 results · 131 ms")
        ev("cv_sadia", 30.7, "truck", "Estimated delivery to Sylhet", "estimate_delivery · Steadfast, Pathao · 210 ms")
        msg("cv_sadia", "assistant", 30, "Ridgeline 3 tent e 3 jon adult thakte parbe, weight 3.4 kg. Sylhet e Steadfast diye shadharonoto 2 theke 3 din lagbe, delivery charge ৳130.",
            tr="The Ridgeline 3 fits three adults and weighs 3.4 kg. Delivery to Sylhet with Steadfast usually takes 2 to 3 days; delivery charge ৳130.", author="Assistant", meta={"product": "NW-RL3-ORG"}, delivery="Delivered")
        msg("cv_sadia", "customer", 28, "Tent ta ki waterproof?", tr="Is the tent waterproof?", author="Sadia Rahman")

        conv("cv_tahmid", "c_tahmid", "ch_wa", "human", "Assalamu alaikum Tahmid bhai, ami Farhana...", D(1) + 60, window=0, handoff="refund request",
             summary="Tahmid reported a cracked lid on the Trail Bottle from order #1041 and asked for a refund. The return is waiting in Approvals. His 24-hour WhatsApp window has closed, so only an approved template can be sent.")
        msg("cv_tahmid", "customer", D(2) + 30, "bottle er lid ta 2 bar use korei vege gese", tr="The bottle lid cracked after just two uses", author="Tahmid Islam")
        ev("cv_tahmid", D(2) + 29, "book", "Checked the returns policy", "get_policy · returns · 74 ms")
        msg("cv_tahmid", "assistant", D(2) + 28, "Eta shunte kharap lagche Tahmid bhai. Delivery er 7 din er moddhe damaged product return ba replace kora jay. Apni refund nite chan naki replacement?",
            tr="Sorry to hear that. Damaged items can be returned or replaced within 7 days of delivery. Do you want a refund or a replacement?", author="Assistant", delivery="Read")
        msg("cv_tahmid", "customer", D(2) + 26, "refund chai", tr="I want a refund", author="Tahmid Islam")
        ev("cv_tahmid", D(2) + 25, "alert", "Handed to a person: refund request", "Refunds need approval · returns policy 2.1", "warn")
        msg("cv_tahmid", "human", D(1) + 60, "Assalamu alaikum Tahmid bhai, ami Farhana, Northwind theke. Lid er jonno dukkhito. Apnar #1041 order er return start korechi, approve hole janabo.",
            tr="Hello, I am Farhana from Northwind. Sorry about the lid. I have started a return for order #1041 and will let you know once it is approved.", author="Farhana", delivery="Delivered")

        conv("cv_imran", "c_imran", "ch_ig", "agent", "Done. I will message you on Instagram and by SMS...", 70,
             summary="Imran asked for the Alpine Shell Jacket in size M. It is out of stock. He asked to be told when it is back, and the assistant saved a restock alert.")
        msg("cv_imran", "customer", 73, "Hi, do you have the Alpine Shell Jacket in green, size M?", author="Imran Khan")
        ev("cv_imran", 72.8, "package", "Checked stock", "get_product · 0 in stock · 88 ms")
        msg("cv_imran", "assistant", 72, "Hi Imran! The Alpine Shell Jacket in green, size M is out of stock right now. I can tell you as soon as it is back. Would you like that?", author="Assistant", meta={"product": "NW-AS-GRN-M"}, delivery="Read")
        msg("cv_imran", "customer", 71, "Yes please, notify me", author="Imran Khan")
        ev("cv_imran", 70.8, "bell", "Saved a restock alert", "create_restock_alert · SKU NW-AS-GRN-M")
        msg("cv_imran", "assistant", 70, "Done. I will message you on Instagram and by SMS when it is back. Please share your mobile number for the SMS.", author="Assistant", delivery="Delivered")
        db.run("INSERT INTO alerts(product_id,customer_id,conversation_id,created_at) VALUES(?,?,?,?)", ["jacket", "c_imran", "cv_imran", ago(70)])

        conv("cv_guest", "c_guest", "ch_web", "agent", "dhonnobad", 90, status="resolved",
             summary="A visitor asked in Banglish whether shoes can be returned. The assistant answered from the returns policy. Resolved.")
        msg("cv_guest", "customer", 92, "shoe return korte parbo?", tr="Can I return shoes?", author="Guest 8831")
        ev("cv_guest", 91.8, "book", "Checked the returns policy", "get_policy · returns · 68 ms")
        msg("cv_guest", "assistant", 91.5, "Ji, na pora shoe delivery er 7 din er moddhe return kora jay. Return er courier charge ৳100 lagbe.", tr="Yes, unworn shoes can be returned within 7 days of delivery. A return courier charge of ৳100 applies.", author="Assistant", delivery="Delivered")
        msg("cv_guest", "customer", 90, "dhonnobad", tr="Thank you", author="Guest 8831")
        ev("cv_guest", 89.9, "check", "Resolved by the assistant", None, "ok")

        # ---------------------------------------------------------------- approvals
        def ap(type_, cust_id, conv_id, order_no, item, amount, reason, said, tr, policy, file, due_min):
            db.run("INSERT INTO approvals(type,customer_id,conversation_id,order_number,item,amount,reason,said,said_tr,policy,attachment,status,due_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   [type_, cust_id, conv_id, order_no, item, amount, reason, said, tr, policy, file, "pending", ago(-due_min), ago(D(1))])

        ap("Return", "c_tahmid", "cv_tahmid", "#1041", "Trail Bottle 2L, Navy", 1450, "Cracked lid after two uses", "bottle er lid ta 2 bar use korei vege gese. refund chai.", "The bottle lid cracked after just two uses. I want a refund.",
           "Returns policy 2.1: Damaged items can be returned or replaced within 7 days of delivery. Refunds go back to the original payment method.", "lid-crack.jpg · 214 KB", -240)
        ap("Exchange", "c_nabila", None, "#1029", "Ridge Boot, size 9 to 10", 0, "Size too small", "৯ সাইজটা একটু টাইট হচ্ছে। ১০ সাইজে এক্সচেঞ্জ করা যাবে?", "Size 9 is a bit tight. Can I exchange it for a 10?",
           "Exchange policy 3.2: Unworn items can be exchanged for another size within 7 days of delivery.", None, 300)
        ap("Price match", "c_sadia", "cv_sadia", "Cart", "Ridgeline 3 Tent", 600, "Another shop lists it at ৳13,900", "Onno shop e ei tent ta ৳13,900 e pachchi. Match korben?", "I am seeing this tent for ৳13,900 at another shop. Will you match it?",
           "Pricing policy 1.4: Price matches are considered for identical items from authorized sellers, with a link as proof. Maximum adjustment ৳1,000.", None, 1440)

        # ---------------------------------------------------------------- integrations
        for id_, grp, name, letter, st, note in [
            ("steadfast", "Couriers", "Steadfast", "S", "off", "Not connected."),
            ("pathao", "Couriers", "Pathao", "P", "off", "Not built."),
            ("redx", "Couriers", "RedX", "R", "off", "Not built."),
            ("paperfly", "Couriers", "Paperfly", "P", "off", "Not built."),
            ("ecourier", "Couriers", "eCourier", "E", "off", "Not built."),
            ("bkash", "Payments", "bKash", "b", "off", "Not connected."),
            ("sslcommerz", "Payments", "SSLCOMMERZ", "S", "off", "Not connected."),
            ("cod", "Payments", "Cash on delivery", "C", "ok", "On in all districts. Confirmed by phone before booking."),
            ("aamarpay", "Payments", "aamarPay", "a", "off", "Not connected."),
            ("nagad", "Payments", "Nagad", "N", "off", "Not built."),
            ("sslwireless", "SMS", "SSL Wireless (ISMS Plus)", "S", "off", "Not connected."),
            ("alphasms", "SMS", "Alpha SMS", "A", "off", "Not connected."),
            ("gp", "SMS", "Grameenphone Corporate Messaging", "G", "off", "Not built."),
            ("banglalink", "SMS", "Banglalink / Robi corporate SMS", "R", "off", "Not built."),
            ("woo", "Store", "WooCommerce", "W", "ok", "Catalog, stock and orders synced 2 min ago."),
            ("shopify", "Store", "Shopify", "S", "off", "Not connected."),
            ("chatorders", "Store", "Orders taken in chat", "C", "ok", "For pages without a website. The assistant saves orders here."),
        ]:
            db.run("INSERT INTO integrations(id,grp,name,letter,status,note) VALUES(?,?,?,?,?,?)", [id_, grp, name, letter, st, note])

        db.set_setting("agent", DEFAULT_SETTINGS)
        db.set_setting("notifications", [
            {"e": "Order placed", "sms": 1, "wa": 0, "em": 0}, {"e": "Payment failed", "sms": 1, "wa": 0, "em": 0}, {"e": "Shipped", "sms": 1, "wa": 1, "em": 0},
            {"e": "Out for delivery", "sms": 1, "wa": 0, "em": 0}, {"e": "Delivered", "sms": 1, "wa": 0, "em": 1}, {"e": "Refund issued", "sms": 1, "wa": 0, "em": 1},
        ])
        db.set_setting("insights_history", {
            "handled": [34, 36, 35, 39, 41, 40, 44, 46, 45, 49, 52, 51, 55, 58],
            "reasons": [["Refund or complaint", 41], ["Asked for a person", 27], ["Request outside policy", 18], ["Low confidence", 14]],
            "kpis": {"handled": 58, "firstReply": 6, "rating": 4.6, "handoff": 31, "revenue": 843160, "chatOrders": 214, "aov": 3940, "conversion": 9.2},
        })


if __name__ == "__main__":
    if "--reset" in sys.argv:
        seed()
        print("Seeded demo data.")
    else:
        seed_if_empty()
        print("Seed checked.")
