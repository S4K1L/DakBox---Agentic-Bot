import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../brand/icons.dart';
import '../brand/theme.dart';
import '../core/api.dart';
import '../core/format.dart';
import '../core/state.dart';
import '../widgets/kit.dart';

Future<T?> _dialog<T>(BuildContext context, Widget d) => showDialog<T>(context: context, barrierColor: Colors.black.withValues(alpha: .45), builder: (_) => d);

class _Box extends StatelessWidget {
  const _Box({required this.icon, required this.title, this.tag, required this.children});
  final IconData icon;
  final String title;
  final Widget? tag;
  final List<Widget> children;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(color: c.surface, border: Border.all(color: c.line), borderRadius: BorderRadius.circular(14)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [Icon(icon, size: 18, color: c.text2), const SizedBox(width: 8), Expanded(child: Text(title, style: TypeX.ui(14, w: FontWeight.w800, color: c.text))), if (tag != null) tag!]),
        const Gap(8),
        ...children,
      ]),
    );
  }
}

class _Shell extends StatelessWidget {
  const _Shell({required this.title, required this.children, this.width = 500});
  final String title;
  final List<Widget> children;
  final double width;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Dialog(
      backgroundColor: Colors.transparent, insetPadding: const EdgeInsets.all(20),
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: width, maxHeight: 760),
        child: Panel(radius: 24, child: SingleChildScrollView(padding: const EdgeInsets.all(24), child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [Expanded(child: Text(title, style: TypeX.display(20, color: c.text))), DkIconButton(PhosphorIconsBold.x, size: 32, onPressed: () => Navigator.pop(context))]),
          const Gap(14),
          ...children,
        ]))),
      ),
    );
  }
}

class _Note extends StatelessWidget {
  const _Note(this.text, {this.tone = 'warn'});
  final String text, tone;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final col = tone == 'danger' ? c.danger : (tone == 'ok' ? c.ok : c.warn);
    final bg = tone == 'danger' ? c.dangerSoft : (tone == 'ok' ? c.okSoft : c.warnSoft);
    return Container(margin: const EdgeInsets.only(bottom: 12), padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(12)), child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Icon(tone == 'ok' ? PhosphorIconsFill.checkCircle : PhosphorIconsFill.warningCircle, size: 18, color: col), const SizedBox(width: 10), Expanded(child: Text(text, style: TypeX.ui(12.5, w: FontWeight.w600, color: c.text, h: 1.45)))]));
  }
}

String payTone(String s) => switch (s) { 'paid' => 'ok', 'pending' || 'created' || 'review' => 'warn', 'failed' || 'cancelled' || 'mismatch' || 'duplicate_paid' => 'danger', 'refunded' || 'partially_refunded' => 'accent', _ => '' };

// ====================================================================== SHIPPING
class ShippingBox extends StatefulWidget {
  const ShippingBox({super.key, required this.o});
  final J o;
  @override
  State<ShippingBox> createState() => _ShippingBoxState();
}

class _ShippingBoxState extends State<ShippingBox> {
  bool open = false, busy = false;
  List<J> rates = [];
  int cod = 0;
  String? rate;

  @override
  Widget build(BuildContext context) {
    final o = widget.o;
    final c = context.c;
    final s = context.read<AppState>();
    final canManage = s.can('orders.manage');
    final courier = o['courier'] as J?;
    final cancelled = o['fulfillment'] == 'Cancelled';
    final no = o['number'] as String;
    final pay = o['payment'] as J;
    if (courier != null) {
      final demo = courier['demo'] == true;
      final trackable = !demo && courier['consignment_id'] != null;
      return _Box(icon: PhosphorIconsRegular.truck, title: courier['name'] as String, tag: Tag(demo ? 'Demo label' : (o['fulfillment'] == 'Delivered' ? 'Delivered' : (o['fulfillment'] == 'Returned' ? 'Returned' : 'In transit')), tone: demo ? 'ai' : (o['fulfillment'] == 'Delivered' ? 'ok' : (o['fulfillment'] == 'Returned' ? 'danger' : 'accent')), small: true), children: [
        if (demo) const _Note('Demo booking: nothing was sent to a real courier.', tone: 'warn'),
        Kv('Tracking', (courier['track'] ?? '—') as String, mono: true),
        if (!demo && courier['cod'] != null) Kv('Cash to collect', taka(courier['cod'] as num)),
        Kv('Recipient', '${(o['ship'] as Map?)?['name'] ?? ''} · ${(o['ship'] as Map?)?['phone'] ?? ''}'),
        Kv('Ship to', o['address'] as String?),
        for (final sc in (o['scans'] as List).cast<J>().take(5))
          Padding(padding: const EdgeInsets.only(top: 6), child: Row(children: [Container(width: 24, height: 24, decoration: BoxDecoration(color: c.sunken, borderRadius: BorderRadius.circular(7)), child: Icon(PhosphorIconsRegular.mapPin, size: 13, color: c.text2)), const SizedBox(width: 10), Expanded(child: Text(sc['x'] as String, style: TypeX.ui(13, w: FontWeight.w600, color: c.text))), Text(dateTime(sc['t'] as String?), style: TypeX.ui(11.5, color: c.text3))])),
        if (trackable && canManage) Padding(padding: const EdgeInsets.only(top: 10), child: Align(alignment: Alignment.centerLeft, child: DkButton(busy ? 'Asking the courier…' : 'Refresh tracking', icon: PhosphorIconsRegular.arrowsClockwise, small: true, onPressed: busy ? null : () async {
          setState(() => busy = true);
          final r = await s.trackOrder(no);
          if (!mounted) return;
          setState(() => busy = false);
          s.toast((r['error'] ?? r['message'] ?? 'Done') as String, error: r['error'] != null);
        }))),
      ]);
    }
    if (cancelled) return _Box(icon: PhosphorIconsRegular.truck, title: 'Shipping', tag: const Tag('Cancelled', small: true), children: [Text('This order was cancelled before shipping.', style: TypeX.ui(13, color: c.text3))]);
    final blocked = pay['status'] == 'Failed' || (pay['status'] == 'Pending' && !((pay['method'] as String?) ?? '').toLowerCase().contains('cash on delivery'));
    return _Box(icon: PhosphorIconsRegular.truck, title: 'Shipping', tag: const Tag('Not shipped', tone: 'warn', small: true), children: [
      Kv('Recipient', '${(o['ship'] as Map?)?['name'] ?? ''} · ${(o['ship'] as Map?)?['phone'] ?? ''}'),
      Kv('Ship to', o['address'] as String?),
      if (blocked) Text('Payment must be received before a parcel is booked.', style: TypeX.ui(13, color: c.text3))
      else if (!open) Padding(padding: const EdgeInsets.only(top: 6), child: Align(alignment: Alignment.centerLeft, child: DkButton(busy ? 'Loading…' : 'Book a courier', icon: PhosphorIconsRegular.truck, kind: BtnKind.primary, small: true, onPressed: !canManage || busy ? null : () async {
        setState(() => busy = true);
        final r = await s.orderRates(no);
        if (!mounted) return;
        if (r['error'] != null) { setState(() => busy = false); s.toast(r['error'] as String, error: true); return; }
        setState(() { busy = false; rates = (r['rates'] as List).cast<J>(); cod = (r['cod'] as num).toInt(); rate = rates.first['id'] as String; open = true; });
      })))
      else ...[
        const Gap(6),
        if (rates.first['demo'] == true) const _Note('No courier is connected, so this only creates a demo label inside Dakbox. Connect one under Connections, Couriers to book real parcels.'),
        for (final r in rates) _Rate(r: r, on: rate == r['id'], onTap: () => setState(() => rate = r['id'] as String)),
        const Gap(6),
        Row(children: [
          DkButton(rates.first['demo'] == true ? 'Create demo label' : 'Review booking', icon: PhosphorIconsBold.check, kind: BtnKind.primary, small: true, onPressed: () async {
            final r = rates.firstWhere((x) => x['id'] == rate);
            if (r['live'] == true) {
              final done = await _dialog<bool>(context, _ConfirmBooking(o: o, rate: r, cod: cod));
              if (done == true && mounted) setState(() => open = false);
            } else {
              final res = await s.shipOrder(no, rate!, null);
              if (!mounted) return;
              s.toast((res['error'] ?? 'Demo label created') as String, error: res['error'] != null);
              if (res['error'] == null) setState(() => open = false);
            }
          }),
          const SizedBox(width: 6),
          DkButton('Cancel', kind: BtnKind.ghost, small: true, onPressed: () => setState(() => open = false)),
        ]),
      ],
    ]);
  }
}

class _Rate extends StatelessWidget {
  const _Rate({required this.r, required this.on, required this.onTap});
  final J r;
  final bool on;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Hover(
      onTap: onTap,
      builder: (_, h, __) => AnimatedContainer(
        duration: const Duration(milliseconds: 140), margin: const EdgeInsets.only(bottom: 8), padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: on ? c.primarySoft : c.surface, borderRadius: BorderRadius.circular(12), border: Border.all(color: on ? c.primary : (h ? c.line2 : c.line), width: on ? 1.5 : 1)),
        child: Row(children: [
          Container(width: 18, height: 18, decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: on ? c.primary : c.line2, width: on ? 5.5 : 2))),
          const SizedBox(width: 12),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Row(children: [Text(r['name'] as String, style: TypeX.ui(14, w: FontWeight.w800, color: c.text)), const SizedBox(width: 8), Tag(r['live'] == true ? 'Live' : 'Demo', tone: r['live'] == true ? 'accent' : 'ai', small: true)]), Text(((r['window'] as String?) ?? '').isEmpty ? (r['note'] as String? ?? '') : '${r['window']} · ${r['note']}', style: TypeX.ui(12, color: c.text3, h: 1.35))])),
          Text(taka(r['price'] as num), style: TypeX.mono(13.5, w: FontWeight.w700, color: c.text)),
        ]),
      ),
    );
  }
}

class _ConfirmBooking extends StatefulWidget {
  const _ConfirmBooking({required this.o, required this.rate, required this.cod});
  final J o, rate;
  final int cod;
  @override
  State<_ConfirmBooking> createState() => _ConfirmBookingState();
}

class _ConfirmBookingState extends State<_ConfirmBooking> {
  bool busy = false;
  String? error;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.read<AppState>();
    final o = widget.o;
    final cust = o['customer'] as J;
    return _Shell(title: 'Confirm the booking', children: [
      Text('This creates a real parcel with ${widget.rate['name']}. Check these details; they cannot be changed afterwards from here.', style: TypeX.ui(13, color: c.text3, h: 1.5)),
      const Gap(14),
      if (error != null) _Note(error!, tone: 'danger'),
      Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(color: c.sunken, borderRadius: BorderRadius.circular(14)),
        child: Column(children: [
          Kv('Order', o['number'] as String, mono: true),
          Kv('Recipient', cust['name'] as String),
          Kv('Address', o['address'] as String?),
          Kv('Courier', '${widget.rate['name']} · ${taka(widget.rate['price'] as num)} delivery'),
        ]),
      ),
      const Gap(14),
      Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(gradient: widget.cod > 0 ? c.hero : null, color: widget.cod > 0 ? null : c.okSoft, borderRadius: BorderRadius.circular(16)),
        child: Row(children: [
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(widget.cod > 0 ? 'THE COURIER WILL COLLECT' : 'NOTHING TO COLLECT', style: TypeX.ui(11, w: FontWeight.w800, color: widget.cod > 0 ? Colors.white70 : c.ok, ls: 1)),
            const SizedBox(height: 4),
            Text(widget.cod > 0 ? taka(widget.cod) : 'Prepaid', style: TypeX.display(30, color: widget.cod > 0 ? Colors.white : c.ok, ls: -.02)),
          ])),
          Icon(widget.cod > 0 ? PhosphorIconsFill.handCoins : PhosphorIconsFill.checkCircle, size: 34, color: widget.cod > 0 ? Colors.white54 : c.ok),
        ]),
      ),
      const Gap(22),
      Row(mainAxisAlignment: MainAxisAlignment.end, children: [
        DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context, false)),
        const Gap(8),
        DkButton(busy ? 'Booking…' : 'Book parcel', icon: PhosphorIconsBold.check, kind: BtnKind.primary, onPressed: busy ? null : () async {
          setState(() { busy = true; error = null; });
          final r = await s.shipOrder(o['number'] as String, widget.rate['id'] as String, widget.cod);
          if (!mounted) return;
          if (r['error'] != null) { setState(() { busy = false; error = r['error'] as String; }); } else { Navigator.pop(context, true); s.toast('Parcel booked. Tracking ${r['tracking']}'); }
        }),
      ]),
    ]);
  }
}

// ====================================================================== PAYMENT
class PaymentBox extends StatelessWidget {
  const PaymentBox({super.key, required this.o});
  final J o;
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final pay = o['payment'] as J;
    final st = pay['status'] as String;
    final payments = (o['payments'] as List).cast<J>();
    final canManage = s.can('orders.manage'), canRefund = s.can('orders.refund');
    final no = o['number'] as String;
    final tone = st == 'Paid' ? 'ok' : (st == 'Pending' ? 'warn' : (st == 'Failed' ? 'danger' : ''));
    final canLink = (st == 'Pending' || st == 'Failed') && canManage;
    return _Box(icon: PhosphorIconsRegular.creditCard, title: 'Payment', tag: Tag(st, tone: tone, small: true), children: [
      Kv('Method', pay['method'] as String?),
      if (o['cod'] != null && (o['cod'] as num) > 0) Kv('Collect on delivery', taka(o['cod'] as num)),
      if ((pay['ref'] as String?)?.isNotEmpty ?? false) Kv('Reference', pay['ref'] as String, mono: true),
      for (final p in payments) _PaymentRow(p: p, order: o),
      const Gap(8),
      Wrap(spacing: 8, runSpacing: 8, children: [
        if (canLink) DkButton('Send payment link', icon: PhosphorIconsRegular.link, kind: st == 'Failed' || o['cod'] == 0 ? BtnKind.primary : BtnKind.secondary, small: true, onPressed: () => _dialog<void>(context, _LinkDialog(o: o))),
        if (canLink) DkButton('Mark as paid', small: true, onPressed: () => _dialog<void>(context, _MarkPaid(no: no))),
        if (st == 'Paid' && canRefund) DkButton('Refund', small: true, onPressed: () => _dialog<void>(context, _RefundDialog(o: o))),
      ]),
    ]);
  }
}

class _PaymentRow extends StatefulWidget {
  const _PaymentRow({required this.p, required this.order});
  final J p, order;
  @override
  State<_PaymentRow> createState() => _PaymentRowState();
}

class _PaymentRowState extends State<_PaymentRow> {
  bool busy = false;
  @override
  Widget build(BuildContext context) {
    final p = widget.p;
    final c = context.c;
    final s = context.read<AppState>();
    final status = p['status'] as String;
    final pending = status == 'pending' || status == 'created';
    final refunds = (p['refunds'] as List).cast<J>();
    return Container(
      margin: const EdgeInsets.only(top: 8), padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: c.sunken, borderRadius: BorderRadius.circular(12)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('${p['providerName']} · ${taka(p['amount'] as num)}', style: TypeX.ui(13, w: FontWeight.w800, color: c.text))),
          if (p['mode'] == 'sandbox') const Padding(padding: EdgeInsets.only(right: 6), child: Tag('Sandbox', tone: 'ai', small: true)),
          Tag(status.replaceAll('_', ' '), tone: payTone(status), small: true),
        ]),
        if ((p['trxId'] as String?)?.isNotEmpty ?? false) Padding(padding: const EdgeInsets.only(top: 4), child: Text('Transaction ${p['trxId']}', style: TypeX.mono(11.5, color: c.text3))),
        if ((p['note'] as String?)?.isNotEmpty ?? false) Padding(padding: const EdgeInsets.only(top: 6), child: Text(p['note'] as String, style: TypeX.ui(12, color: status == 'paid' ? c.text3 : c.warn, h: 1.4))),
        if (pending && s.can('orders.manage')) Padding(padding: const EdgeInsets.only(top: 8), child: Wrap(spacing: 6, children: [
          if (p['url'] != null) DkButton('Copy link', icon: PhosphorIconsRegular.copy, small: true, onPressed: () { Clipboard.setData(ClipboardData(text: p['url'] as String)); s.toast('Payment link copied'); }),
          DkButton(busy ? 'Asking…' : 'Check status', icon: PhosphorIconsRegular.arrowsClockwise, small: true, onPressed: busy ? null : () async {
            setState(() => busy = true);
            final r = await s.refreshPayment(p['id'] as String);
            if (!mounted) return;
            setState(() => busy = false);
            s.toast(r['error'] != null ? r['error'] as String : (r['outcome'] == 'paid' ? 'Payment confirmed' : 'Not paid yet'), error: r['error'] != null);
          }),
        ])),
        for (final r in refunds)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Row(children: [
              Icon(PhosphorIconsRegular.arrowUUpLeft, size: 14, color: c.text3), const SizedBox(width: 6),
              Expanded(child: Text('Refund ${taka(r['amount'] as num)}${r['manual'] == true ? ' (recorded)' : ''}', style: TypeX.ui(12.5, w: FontWeight.w600, color: c.text2))),
              Tag(r['status'] as String, tone: r['status'] == 'done' ? 'ok' : (r['status'] == 'failed' ? 'danger' : 'warn'), small: true),
              if ((r['status'] == 'processing' || r['status'] == 'unknown') && s.can('orders.refund')) Padding(padding: const EdgeInsets.only(left: 6), child: DkButton('Check', small: true, onPressed: () async {
                final res = await s.checkRefund(r['id'] as String);
                s.toast((res['error'] ?? res['message'] ?? (res['status'] == 'done' ? 'Refund confirmed' : 'Still ${res['status']}')) as String, error: res['error'] != null);
              })),
            ]),
          ),
      ]),
    );
  }
}

class _LinkDialog extends StatefulWidget {
  const _LinkDialog({required this.o});
  final J o;
  @override
  State<_LinkDialog> createState() => _LinkDialogState();
}

class _LinkDialogState extends State<_LinkDialog> {
  String? provider;
  bool chat = true, busy = false;
  String? error;
  J? done;
  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    final live = s.liveProviders;
    provider ??= live.isEmpty ? null : live.first['id'] as String;
    final o = widget.o;
    final hasChat = o['conversationId'] != null;
    if (done != null) {
      final url = done!['url'] as String;
      return _Shell(title: 'Payment link ready', children: [
        _Note(done!['sent'] == true ? 'Sent to ${(o['customer'] as J)['name']} in the conversation.' : ((done!['notSentReason'] as String?) ?? 'Not sent. Copy the link and send it yourself.'), tone: done!['sent'] == true ? 'ok' : 'warn'),
        if (done!['reused'] == true) const _Note('This order already had an open link, so the same one was used.', tone: 'ok'),
        Hover(
          onTap: () { Clipboard.setData(ClipboardData(text: url)); s.toast('Copied'); },
          builder: (_, h, __) => Container(padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: c.sunken, borderRadius: BorderRadius.circular(12), border: Border.all(color: h ? c.primary : c.line)), child: Row(children: [Expanded(child: SelectableText(url, style: TypeX.mono(12, color: c.text))), Icon(PhosphorIconsRegular.copy, size: 16, color: c.text3)])),
        ),
        const Gap(16),
        Align(alignment: Alignment.centerRight, child: DkButton('Done', kind: BtnKind.primary, onPressed: () => Navigator.pop(context))),
      ]);
    }
    return _Shell(title: 'Send a payment link', children: [
      Text('${taka(((o['total']) as num))} for order ${o['number']}. The order is marked paid only after the provider confirms the payment to Dakbox.', style: TypeX.ui(13, color: c.text3, h: 1.5)),
      const Gap(14),
      if (error != null) _Note(error!, tone: 'danger'),
      if (live.isEmpty) ...[
        const _Note('No payment provider is connected. Connect SSLCOMMERZ, bKash or aamarPay first.'),
        Align(alignment: Alignment.centerLeft, child: DkButton('Open Connections', onPressed: () { Navigator.pop(context); s.setSection(Section.connections); })),
      ] else ...[
        Text('Provider', style: TypeX.ui(12.5, w: FontWeight.w700, color: c.text2)),
        const Gap(6),
        Seg<String>(items: [for (final p in live) (p['id'] as String, p['name'] as String)], value: provider!, onChanged: (v) => setState(() => provider = v), small: true),
        if (live.firstWhere((p) => p['id'] == provider)['mode'] == 'sandbox') const Padding(padding: EdgeInsets.only(top: 10), child: Tag('Sandbox: no real money moves', tone: 'ai', small: true)),
        const Gap(14),
        Row(children: [Expanded(child: Text(hasChat ? 'Send the link in the customer’s chat' : 'This customer has no conversation yet', style: TypeX.ui(13.5, w: FontWeight.w600, color: c.text))), DkSwitch(value: chat && hasChat, onChanged: hasChat ? (v) => setState(() => chat = v) : null)]),
        const Gap(22),
        Row(mainAxisAlignment: MainAxisAlignment.end, children: [
          DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
          const Gap(8),
          DkButton(busy ? 'Creating…' : 'Create link', icon: PhosphorIconsBold.link, kind: BtnKind.primary, onPressed: busy ? null : () async {
            setState(() { busy = true; error = null; });
            final r = await s.createPaymentLink(o['number'] as String, provider!, chat && hasChat);
            if (!mounted) return;
            if (r['error'] != null) { setState(() { busy = false; error = r['error'] as String; }); } else { setState(() { busy = false; done = r; }); }
          }),
        ]),
      ],
    ]);
  }
}

class _MarkPaid extends StatelessWidget {
  const _MarkPaid({required this.no});
  final String no;
  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    return _Shell(title: 'Mark $no as paid?', width: 440, children: [
      Text('Use this only when you have seen the money arrive outside a payment provider (cash, a bank transfer). Any open payment links for this order are closed, and this is recorded in the activity log.', style: TypeX.ui(13, color: c.text2, h: 1.5)),
      const Gap(22),
      Row(mainAxisAlignment: MainAxisAlignment.end, children: [
        DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
        const Gap(8),
        DkButton('Yes, mark as paid', kind: BtnKind.primary, onPressed: () async { Navigator.pop(context); await s.orderAction(no, 'mark-paid', success: 'Marked as paid'); }),
      ]),
    ]);
  }
}

class _RefundDialog extends StatefulWidget {
  const _RefundDialog({required this.o});
  final J o;
  @override
  State<_RefundDialog> createState() => _RefundDialogState();
}

class _RefundDialogState extends State<_RefundDialog> {
  late final J? pay = (widget.o['payments'] as List).cast<J>().where((p) => p['canRefund'] == true).cast<J?>().firstWhere((_) => true, orElse: () => null);
  late final amount = TextEditingController(text: '${pay != null ? (pay!['amount'] as num).toInt() - (pay!['refunded'] as num).toInt() : (widget.o['total'] as num).toInt()}');
  final reason = TextEditingController(text: 'Refund');
  bool manual = false, busy = false;
  String? error;
  J? result;
  @override
  void dispose() { amount.dispose(); reason.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    final o = widget.o;
    final provider = pay?['provider'] as String?;
    final noApi = provider == 'aamarpay';
    final sandbox = pay?['mode'] == 'sandbox';
    if (result != null) {
      final st = result!['status'] as String;
      return _Shell(title: st == 'done' ? 'Refund done' : (st == 'failed' ? 'Refund not done' : 'Refund not confirmed yet'), width: 460, children: [
        _Note((result!['message'] as String?) ?? (st == 'done' ? 'The refund was confirmed.' : 'The provider has not confirmed the refund yet.'), tone: st == 'done' ? 'ok' : (st == 'failed' ? 'danger' : 'warn')),
        if (st == 'processing' || st == 'unknown') Text('Dakbox does NOT count this as refunded yet. Use “Check” next to the refund on the order to ask the provider again. Do not send it a second time.', style: TypeX.ui(12.5, color: c.text2, h: 1.5)),
        const Gap(18),
        Align(alignment: Alignment.centerRight, child: DkButton('Done', kind: BtnKind.primary, onPressed: () => Navigator.pop(context))),
      ]);
    }
    return _Shell(title: 'Refund ${o['number']}', width: 480, children: [
      if (pay == null) const _Note('This order was not paid through a payment provider, so there is nothing to reverse online. This only records the refund.', tone: 'warn')
      else if (noApi) const _Note('aamarPay has no refund API. Refund the customer in the aamarPay merchant panel first, then record it here.', tone: 'warn')
      else if (!sandbox) const _Note('This sends real money back to the customer through the provider. It cannot be undone.', tone: 'danger')
      else const _Note('Sandbox payment: no real money moves.', tone: 'ok'),
      if (error != null) _Note(error!, tone: 'danger'),
      DkField(controller: amount, label: 'Amount (৳)', mono: true),
      const Gap(12),
      DkField(controller: reason, label: 'Reason'),
      if (pay != null && !noApi) ...[
        const Gap(14),
        Row(children: [Expanded(child: Text('I already refunded it outside Dakbox (only record it)', style: TypeX.ui(13, w: FontWeight.w600, color: c.text))), DkSwitch(value: manual, onChanged: (v) => setState(() => manual = v))]),
      ],
      const Gap(22),
      Row(mainAxisAlignment: MainAxisAlignment.end, children: [
        DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
        const Gap(8),
        DkButton(busy ? 'Working…' : (noApi || manual || pay == null ? 'Record refund' : 'Refund now'), icon: PhosphorIconsBold.arrowUUpLeft, kind: BtnKind.primary, onPressed: busy ? null : () async {
          final n = int.tryParse(amount.text.trim());
          if (n == null || n < 1) { setState(() => error = 'Enter the amount in whole taka.'); return; }
          setState(() { busy = true; error = null; });
          final r = await s.refundOrder(o['number'] as String, amount: n, reason: reason.text.trim().isEmpty ? 'Refund' : reason.text.trim(), manual: noApi || manual);
          if (!mounted) return;
          if (r['error'] != null) { setState(() { busy = false; error = r['error'] as String; }); } else { setState(() { busy = false; result = r; }); }
        }),
      ]),
    ]);
  }
}
