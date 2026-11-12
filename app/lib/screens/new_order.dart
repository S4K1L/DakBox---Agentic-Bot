import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../brand/icons.dart';
import '../brand/theme.dart';
import '../core/api.dart';
import '../core/format.dart';
import '../core/state.dart';
import '../widgets/kit.dart';

/// Staff build an order from a cart: from scratch (Orders, New order) or from a conversation's cart (Inbox, customer panel).
Future<void> showNewOrder(BuildContext context, {J? conv}) =>
    showDialog<void>(context: context, barrierColor: Colors.black.withValues(alpha: .45), builder: (_) => Theme(data: Theme.of(context), child: _NewOrder(conv: conv)));

class _NewOrder extends StatefulWidget {
  const _NewOrder({this.conv});
  final J? conv;
  @override
  State<_NewOrder> createState() => _NewOrderState();
}

class _NewOrderState extends State<_NewOrder> {
  final search = TextEditingController();
  final who = TextEditingController();
  final name = TextEditingController();
  final phone = TextEditingController();
  final address = TextEditingController();
  final shipText = TextEditingController();
  final Map<String, int> qty = {};         // sku -> quantity, in the order they were added
  String zone = 'dhaka';
  bool zoneTouched = false, manualShip = false, busy = false, quoting = false;
  String method = 'cod';
  String? customerId, error;
  J? quote;
  int _qid = 0;

  bool get fromChat => widget.conv != null;

  @override
  void initState() {
    super.initState();
    final c = widget.conv;
    if (c != null) {
      customerId = (c['customer'] as J)['id'] as String;
      name.text = (c['customer'] as J)['name'] as String;
      for (final l in (c['cart'] as List).cast<J>()) { qty[l['sku'] as String] = (l['qty'] as num).toInt(); }
      final area = ((c['customer'] as J)['area'] ?? '') as String;
      if (area.toLowerCase().contains('dhaka')) { zone = 'dhaka'; } else if (area.isNotEmpty) { zone = 'out'; }
    }
    address.addListener(_guessZone);
    final st = context.read<AppState>();
    st.loadProducts();                          // fresh stock, and the lists exist even if Products was never opened
    if (st.customers.isEmpty) st.loadCustomers();
    WidgetsBinding.instance.addPostFrameCallback((_) => _requote());
  }

  @override
  void dispose() { for (final t in [search, who, name, phone, address, shipText]) { t.dispose(); } super.dispose(); }

  void _guessZone() {
    if (zoneTouched) return;
    final a = address.text.toLowerCase();
    if (a.length < 6) return;
    final z = (a.contains('dhaka') || a.contains('ঢাকা')) ? 'dhaka' : 'out';
    if (z != zone) { setState(() => zone = z); _requote(); }
  }

  int? get ship => manualShip ? int.tryParse(shipText.text.trim()) : null;

  Future<void> _requote() async {
    final id = ++_qid;
    if (qty.isEmpty) { setState(() { quote = null; quoting = false; }); return; }
    setState(() => quoting = true);
    final q = await context.read<AppState>().quoteOrder([for (final e in qty.entries) {'sku': e.key, 'qty': e.value}], zone, ship);
    if (!mounted || id != _qid) return;
    setState(() { quoting = false; quote = q['error'] != null ? null : q; if (q['error'] != null) error = q['error'] as String; });
  }

  void _add(J p) {
    final sku = p['sku'] as String;
    final n = (qty[sku] ?? 0) + 1;
    if (n > (p['stock'] as int)) return;
    setState(() { qty[sku] = n; error = null; });
    _requote();
  }

  void _step(String sku, int d) {
    final n = (qty[sku] ?? 0) + d;
    setState(() { if (n <= 0) { qty.remove(sku); } else { qty[sku] = n; } error = null; });
    _requote();
  }

  Future<void> _create() async {
    setState(() { busy = true; error = null; });
    final s = context.read<AppState>();
    final r = await s.createOrder({
      'lines': [for (final e in qty.entries) {'sku': e.key, 'qty': e.value}], 'zone': zone, 'method': method,
      'name': name.text.trim().isEmpty ? null : name.text.trim(), 'phone': phone.text.trim().isEmpty ? null : phone.text.trim(), 'address': address.text.trim(),
      'customerId': widget.conv == null ? customerId : null, 'conversationId': widget.conv?['id'], 'shipping': ship,
    });
    if (!mounted) return;
    if (r['error'] != null) { setState(() { busy = false; error = r['error'] as String; }); return; }
    final no = r['order'] as String;
    Navigator.pop(context);
    s.setSection(Section.orders);
    s.selectOrder(no);
    s.toast(r['needsPaymentLink'] == true ? 'Order $no created. Send the payment link from the order' : 'Order $no created. Stock was reserved');
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Dialog(
      backgroundColor: Colors.transparent, insetPadding: const EdgeInsets.all(20),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 940, maxHeight: 760),
        child: Panel(
          radius: 24, shadow: true,
          child: LayoutBuilder(builder: (context, box) {
            final wide = box.maxWidth > 720;
            return Column(children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(24, 20, 20, 14),
                child: Row(children: [
                  Container(width: 36, height: 36, decoration: BoxDecoration(color: c.primarySoft, borderRadius: BorderRadius.circular(11)), child: Icon(PhosphorIconsBold.shoppingCartSimple, size: 18, color: c.primary)),
                  const SizedBox(width: 12),
                  Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('New order', style: TypeX.display(20, color: c.text)),
                    Text(fromChat ? 'From ${(widget.conv!['customer'] as J)['name']}’s cart. The cart is emptied when the order is created.' : 'Add products, then the customer and delivery. Stock is reserved when you create it.', style: TypeX.ui(12.5, color: c.text3)),
                  ])),
                  DkIconButton(PhosphorIconsBold.x, size: 32, onPressed: busy ? null : () => Navigator.pop(context)),
                ]),
              ),
              Container(height: 1, color: c.line),
              Expanded(
                child: wide
                    ? Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Expanded(child: SingleChildScrollView(padding: const EdgeInsets.all(24), child: _items(c))),
                        Container(width: 1, color: c.line),
                        Expanded(child: SingleChildScrollView(padding: const EdgeInsets.all(24), child: _details(c))),
                      ])
                    : SingleChildScrollView(padding: const EdgeInsets.all(20), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [_items(c), const Gap(22), _details(c)])),
              ),
              Container(height: 1, color: c.line),
              Padding(padding: const EdgeInsets.fromLTRB(24, 14, 24, 18), child: _footer(c)),
            ]);
          }),
        ),
      ),
    );
  }

  // ---------------------------------------------------------------- items
  Widget _items(DK c) {
    final s = context.watch<AppState>();
    final q = search.text.trim().toLowerCase();
    final results = s.products.where((p) => q.isEmpty || '${p['name']} ${p['variant']} ${p['sku']}'.toLowerCase().contains(q)).take(q.isEmpty ? 5 : 8).toList();
    final byQuote = {for (final l in ((quote?['lines'] as List?) ?? const []).cast<J>()) l['sku'] as String: l};
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Label('Items'),
      const Gap(8),
      DkField(controller: search, hint: 'Search products to add', onSubmitted: (_) {}),
      const Gap(8),
      ConstrainedBox(
        constraints: const BoxConstraints(maxHeight: 210),
        child: Container(
          decoration: BoxDecoration(border: Border.all(color: c.line), borderRadius: BorderRadius.circular(14)),
          clipBehavior: Clip.antiAlias,
          child: results.isEmpty
              ? Padding(padding: const EdgeInsets.all(14), child: Text('No product matches.', style: TypeX.ui(13, color: c.text3)))
              : ListView(shrinkWrap: true, children: [
                  for (var i = 0; i < results.length; i++) _pick(c, results[i], i),
                ]),
        ),
      ),
      const Gap(18),
      Row(children: [Label('In this order'), const Spacer(), if (quoting) SizedBox(width: 12, height: 12, child: CircularProgressIndicator(strokeWidth: 2, color: c.primary))]),
      const Gap(8),
      if (qty.isEmpty)
        Container(width: double.infinity, padding: const EdgeInsets.all(16), decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(14), border: Border.all(color: c.line)), child: Text('Nothing added yet. Pick a product above.', style: TypeX.ui(13, color: c.text3)))
      else
        Container(
          decoration: BoxDecoration(border: Border.all(color: c.line), borderRadius: BorderRadius.circular(14)),
          clipBehavior: Clip.antiAlias,
          child: Column(children: [
            for (final e in qty.entries.toList().asMap().entries) _line(c, e.key, e.value.key, e.value.value, byQuote[e.value.key]),
          ]),
        ),
    ]);
  }

  Widget _pick(DK c, J p, int i) {
    final out = (p['stock'] as int) == 0;
    final atMax = (qty[p['sku']] ?? 0) >= (p['stock'] as int);
    return Hover(
      onTap: out || atMax ? null : () => _add(p),
      builder: (_, h, __) => Container(
        decoration: BoxDecoration(color: h && !out && !atMax ? c.sunken : c.surface, border: i == 0 ? null : Border(top: BorderSide(color: c.line))), padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(children: [
          ProductPhoto(image: p['image'] as String?, kind: p['art'] as String?, size: 36, radius: 9),
          const SizedBox(width: 10),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(p['name'] as String, maxLines: 1, overflow: TextOverflow.ellipsis, style: TypeX.ui(13.5, w: FontWeight.w700, color: out ? c.text3 : c.text)),
            Text('${p['variant'] ?? ''}${p['variant'] != null ? ' · ' : ''}${out ? 'Out of stock' : '${p['stock']} in stock'}', maxLines: 1, overflow: TextOverflow.ellipsis, style: TypeX.ui(12, color: out ? c.danger : c.text3)),
          ])),
          Text(taka(p['price'] as num), style: TypeX.mono(12.5, color: c.text2)),
          const SizedBox(width: 8),
          Icon(PhosphorIconsBold.plus, size: 15, color: out || atMax ? c.text3 : c.primary),
        ]),
      ),
    );
  }

  Widget _line(DK c, int i, String sku, int n, J? ql) {
    final s = context.read<AppState>();
    final p = s.products.cast<J?>().firstWhere((x) => x!['sku'] == sku, orElse: () => null);
    final ok = ql == null || ql['ok'] == true;
    final price = (ql?['price'] ?? p?['price'] ?? 0) as num;
    return Container(
      decoration: BoxDecoration(color: ok ? c.surface : c.dangerSoft, border: i == 0 ? null : Border(top: BorderSide(color: c.line))), padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
      child: Row(children: [
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${p?['name'] ?? sku}${p?['variant'] != null ? ' · ${p!['variant']}' : ''}', maxLines: 1, overflow: TextOverflow.ellipsis, style: TypeX.ui(13.5, w: FontWeight.w700, color: c.text)),
          Text(ok ? '${taka(price)} each' : 'Only ${ql['stock']} in stock', style: TypeX.ui(12, color: ok ? c.text3 : c.danger, w: ok ? FontWeight.w400 : FontWeight.w700)),
        ])),
        DkIconButton(PhosphorIconsBold.minus, size: 28, onPressed: () => _step(sku, -1)),
        SizedBox(width: 26, child: Center(child: Text('$n', style: TypeX.mono(13.5, w: FontWeight.w800, color: c.text)))),
        DkIconButton(PhosphorIconsBold.plus, size: 28, onPressed: p != null && n >= (p['stock'] as int) ? null : () => _step(sku, 1)),
        SizedBox(width: 78, child: Text(taka(price * n), textAlign: TextAlign.right, style: TypeX.mono(12.5, w: FontWeight.w700, color: c.text))),
      ]),
    );
  }

  // ---------------------------------------------------------------- customer and delivery
  Widget _details(DK c) {
    final s = context.watch<AppState>();
    final methods = ((quote?['methods'] as List?) ?? const [{'id': 'cod', 'label': 'Cash on delivery'}]).cast<J>();
    final wq = who.text.trim().toLowerCase();
    final matches = wq.length < 2 || customerId != null ? <J>[] : s.customers.where((x) => '${x['name']} ${x['phone']}'.toLowerCase().contains(wq)).take(4).toList();
    final chosen = customerId == null ? null : s.customers.cast<J?>().firstWhere((x) => x!['id'] == customerId, orElse: () => widget.conv?['customer'] as J?);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Label('Customer'),
      const Gap(8),
      if (chosen != null)
        Container(
          padding: const EdgeInsets.fromLTRB(10, 8, 6, 8), decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(12), border: Border.all(color: c.line)),
          child: Row(children: [
            Avatar(name: chosen['name'] as String, hue: chosen['hue'] as num, size: 30),
            const SizedBox(width: 10),
            Expanded(child: Text('${chosen['name']}${chosen['phone'] != null ? '  ·  ${chosen['phone']}' : ''}', maxLines: 1, overflow: TextOverflow.ellipsis, style: TypeX.ui(13.5, w: FontWeight.w700, color: c.text))),
            if (!fromChat) DkIconButton(PhosphorIconsBold.x, size: 26, tooltip: 'Use someone else', onPressed: () => setState(() { customerId = null; who.clear(); })),
          ]),
        )
      else ...[
        DkField(controller: who, hint: 'Find an existing customer by name or number', onSubmitted: (_) {}),
        if (matches.isNotEmpty)
          Container(
            margin: const EdgeInsets.only(top: 6), decoration: BoxDecoration(border: Border.all(color: c.line), borderRadius: BorderRadius.circular(12)), clipBehavior: Clip.antiAlias,
            child: Column(children: [
              for (var i = 0; i < matches.length; i++)
                Hover(
                  onTap: () => setState(() { customerId = matches[i]['id'] as String; name.text = matches[i]['name'] as String; who.clear(); }),
                  builder: (_, h, __) => Container(width: double.infinity, color: h ? c.sunken : c.surface, padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9), decoration: i == 0 ? null : BoxDecoration(border: Border(top: BorderSide(color: c.line))), child: Text('${matches[i]['name']}  ·  ${matches[i]['phone'] ?? 'no number'}', style: TypeX.ui(13, w: FontWeight.w600, color: c.text))),
                ),
            ]),
          ),
        Padding(padding: const EdgeInsets.only(top: 6), child: Text('Not a customer yet? Fill in the name and phone below and Dakbox adds them.', style: TypeX.ui(12, color: c.text3))),
      ],
      const Gap(14),
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(child: DkField(controller: name, label: 'Name on the parcel')),
        const SizedBox(width: 10),
        Expanded(child: DkField(controller: phone, label: customerId != null ? 'Phone (saved one if empty)' : 'Phone', hint: '01712345678', mono: true)),
      ]),
      const Gap(12),
      DkField(controller: address, label: 'Delivery address', hint: 'House, road, area, district', maxLines: 3),
      const Gap(14),
      Label('Delivery area'),
      const Gap(8),
      Seg<String>(items: const [('dhaka', 'Inside Dhaka'), ('out', 'Outside Dhaka')], value: zone, small: true, onChanged: (v) { zoneTouched = true; setState(() => zone = v); _requote(); }),
      const Gap(16),
      Label('Payment'),
      const Gap(8),
      Wrap(spacing: 8, runSpacing: 8, children: [
        for (final m in methods)
          Hover(
            onTap: () => setState(() => method = m['id'] as String),
            builder: (_, h, __) => Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
              decoration: BoxDecoration(color: method == m['id'] ? c.primarySoft : c.surface, borderRadius: BorderRadius.circular(11), border: Border.all(color: method == m['id'] ? c.primary : (h ? c.line2 : c.line))),
              child: Text(m['label'] as String, style: TypeX.ui(13, w: FontWeight.w700, color: method == m['id'] ? c.primary : c.text2)),
            ),
          ),
      ]),
      Padding(padding: const EdgeInsets.only(top: 8), child: Text(method == 'cod' ? 'The courier collects cash. Confirm by phone before booking, as with any order.' : 'The order stays unpaid until the customer pays. Send the payment link from the order afterwards.', style: TypeX.ui(12, color: c.text3, h: 1.4))),
    ]);
  }

  // ---------------------------------------------------------------- totals and the button
  Widget _footer(DK c) {
    final q = quote;
    final problems = ((q?['problems'] as List?) ?? const []).cast<J>().where((p) => p['code'] != 'cart_empty').toList();
    final delivery = q?['delivery'] as num?;
    Widget row(String l, Widget v) => Padding(padding: const EdgeInsets.symmetric(vertical: 2), child: Row(children: [Text(l, style: TypeX.ui(13, color: c.text2)), const Spacer(), v]));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (error != null)
        Container(margin: const EdgeInsets.only(bottom: 10), padding: const EdgeInsets.all(10), width: double.infinity, decoration: BoxDecoration(color: c.dangerSoft, borderRadius: BorderRadius.circular(10)),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Icon(PhosphorIconsFill.warningCircle, size: 15, color: c.danger), const SizedBox(width: 8), Expanded(child: Text(error!, style: TypeX.ui(12.5, color: c.text, h: 1.4)))])),
      if (problems.isNotEmpty && error == null)
        Container(margin: const EdgeInsets.only(bottom: 10), padding: const EdgeInsets.all(10), width: double.infinity, decoration: BoxDecoration(color: c.warnSoft, borderRadius: BorderRadius.circular(10)),
            child: Text('${problems.map((p) => p['code'] == 'insufficient_stock' ? '${p['name']}: only ${p['in_stock']} in stock' : p['code'] == 'too_many_units' ? 'Too many units for one order' : 'A product is no longer available').join('. ')}.', style: TypeX.ui(12.5, color: c.text))),
      Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Expanded(
          child: Column(children: [
            row('Subtotal', Text(taka((q?['subtotal'] ?? 0) as num), style: TypeX.mono(13, color: c.text))),
            row('Delivery', Row(mainAxisSize: MainAxisSize.min, children: [
              if (manualShip)
                SizedBox(width: 86, child: TextField(controller: shipText, keyboardType: TextInputType.number, onChanged: (_) => _requote(), style: TypeX.mono(13, color: c.text), decoration: InputDecoration(isDense: true, prefixText: '৳', contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 7), border: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide(color: c.line2)))))
              else
                Text(delivery == null ? '—' : (delivery == 0 ? 'Free' : taka(delivery)), style: TypeX.mono(13, color: c.text)),
              const SizedBox(width: 6),
              Hover(
                onTap: () { setState(() { manualShip = !manualShip; if (manualShip) { shipText.text = '${(q?['autoDelivery'] ?? 0)}'; } }); _requote(); },
                builder: (_, h, __) => Text(manualShip ? 'Use standard' : 'Change', style: TypeX.ui(12, w: FontWeight.w700, color: h ? c.primaryHover : c.primary)),
              ),
            ])),
            row('Total', Text(taka((q?['total'] ?? 0) as num), style: TypeX.display(18, color: c.text))),
          ]),
        ),
        const SizedBox(width: 24),
        DkButton('Cancel', kind: BtnKind.ghost, onPressed: busy ? null : () => Navigator.pop(context)),
        const Gap(8),
        DkButton(busy ? 'Creating…' : 'Create order', icon: PhosphorIconsBold.check, kind: BtnKind.primary, onPressed: busy || qty.isEmpty || problems.isNotEmpty || quoting ? null : _create),
      ]),
    ]);
  }
}
