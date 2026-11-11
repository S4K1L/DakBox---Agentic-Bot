import 'package:flutter/material.dart';
import '../brand/icons.dart';
import 'package:provider/provider.dart';
import '../brand/theme.dart';
import '../core/api.dart';
import '../core/format.dart';
import '../core/state.dart';
import '../widgets/kit.dart';
import '../widgets/page.dart';
import 'order_actions.dart';

String payTone(String s) => s == 'Paid' ? 'ok' : (s == 'Pending' ? 'warn' : (s == 'Failed' ? 'danger' : ''));
String fulTone(String s) => s == 'Delivered' ? 'ok' : (s == 'Unfulfilled' ? 'warn' : (s == 'Cancelled' ? '' : (s == 'Returned' ? 'danger' : 'accent')));

class OrdersScreen extends StatelessWidget {
  const OrdersScreen({super.key});
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final rows = s.visibleOrders;
    final sel = s.orders.where((o) => o['number'] == s.orderNo).toList();
    int cnt(bool Function(J) f) => s.orders.where(f).length;
    return MasterDetail(
      hasSelection: sel.isNotEmpty,
      onBack: () => s.selectOrder(null),
      detailWidth: 460,
      master: Panel(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          PageHeader(
            title: 'Orders',
            subtitle: Row(mainAxisSize: MainAxisSize.min, children: [Text('${plural(s.toShip, 'order')} to ship today', style: TypeX.ui(13.5, color: c.text3)), const SizedBox(width: 8), const Tag('Sample data', tone: 'warn', small: true)]),
            actions: [SearchBox(hint: 'Search orders', width: 220, onChanged: s.setOrderQuery), DkButton('Sync', icon: PhosphorIconsRegular.arrowsClockwise, onPressed: () => s.loadOrders().then((_) => s.toast('Orders are up to date')))],
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(24, 0, 24, 14),
            child: Row(children: [
              StatTile(value: '${s.toShip}', label: 'To ship', icon: PhosphorIconsRegular.package, tone: 'warn', active: s.orderTab == 'unful', onTap: () => s.setOrderTab('unful')),
              const SizedBox(width: 8),
              StatTile(value: '${cnt((o) => o['fulfillment'] == 'In transit')}', label: 'In transit', icon: PhosphorIconsRegular.truck, active: s.orderTab == 'transit', onTap: () => s.setOrderTab('transit')),
              const SizedBox(width: 8),
              StatTile(value: '${cnt((o) => o['payment']['status'] == 'Pending' && o['fulfillment'] != 'Cancelled' && !((o['payment']['method'] as String?) ?? '').toLowerCase().contains('cash on delivery'))}', label: 'Unpaid online', icon: PhosphorIconsRegular.creditCard, tone: 'danger', active: s.orderTab == 'issue', onTap: () => s.setOrderTab('issue')),
              const SizedBox(width: 8),
              StatTile(value: taka(s.orders.where((o) => o['fulfillment'] != 'Cancelled').fold<num>(0, (a, o) => a + ((o['cod'] ?? 0) as num))), label: 'Cash to collect', icon: PhosphorIconsRegular.handCoins, tone: 'ok'),
            ]),
          ),
          UnderTabs(value: s.orderTab, onChanged: s.setOrderTab, tabs: [
            ('all', 'All', s.orders.length),
            ('unful', 'To ship', cnt((o) => o['fulfillment'] == 'Unfulfilled')),
            ('transit', 'In transit', cnt((o) => o['fulfillment'] == 'In transit')),
            ('done', 'Delivered', cnt((o) => o['fulfillment'] == 'Delivered')),
            ('issue', 'Issues', cnt((o) => o['returnRequested'] == true || o['payment']['status'] == 'Failed' || o['payment']['status'] == 'Pending')),
          ]),
          Expanded(
            child: rows.isEmpty
                ? const Empty('No orders match this view', icon: PhosphorIconsDuotone.shoppingBag)
                : ListView.builder(padding: const EdgeInsets.fromLTRB(14, 12, 14, 14), itemCount: rows.length, itemBuilder: (_, i) => Reveal(delay: i * 30, child: _OrderRow(o: rows[i], selected: rows[i]['number'] == s.orderNo))),
          ),
        ]),
      ),
      detail: sel.isEmpty ? const Panel(child: Empty('Select an order', body: 'Items, payment, courier tracking and messages appear here.', icon: PhosphorIconsDuotone.shoppingBag)) : _OrderDetail(key: ValueKey(sel.first['number']), o: sel.first),
    );
  }
}

class _OrderRow extends StatelessWidget {
  const _OrderRow({required this.o, required this.selected});
  final J o;
  final bool selected;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.read<AppState>();
    final cust = o['customer'] as J;
    final pay = o['payment']['status'] as String;
    final ful = o['fulfillment'] as String;
    final items = (o['items'] as List).cast<J>();
    final units = items.fold<int>(0, (a, i) => a + (i['qty'] as int));
    final first = items.isEmpty ? '' : '${items.first['qty']} × ${items.first['name']}${items.length > 1 ? '  +${items.length - 1} more' : ''}';
    final accent = ful == 'Delivered' ? c.ok : (ful == 'Cancelled' || ful == 'Returned' ? c.text3 : (pay == 'Failed' ? c.danger : (ful == 'Unfulfilled' ? c.warn : c.primary)));
    return Hover(
      onTap: () => s.selectOrder(o['number'] as String),
      builder: (_, h, __) => AnimatedContainer(
        duration: const Duration(milliseconds: 140), margin: const EdgeInsets.only(bottom: 8),
        decoration: BoxDecoration(color: selected ? c.primarySoft : (h ? c.surface2 : c.surface), borderRadius: BorderRadius.circular(16), border: Border.all(color: selected ? c.primary : (h ? c.line2 : c.line), width: selected ? 1.4 : 1)),
        clipBehavior: Clip.antiAlias,
        child: IntrinsicHeight(
          child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Container(width: 4, color: accent),
            Expanded(child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 13, 14, 13),
              child: Row(children: [
                Avatar(name: cust['name'] as String, hue: cust['hue'] as num, size: 42, channel: o['channel'] as String?),
                const SizedBox(width: 12),
                Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    Flexible(child: Text(cust['name'] as String, style: TypeX.ui(14.5, w: FontWeight.w800, color: c.text), maxLines: 1, overflow: TextOverflow.ellipsis)),
                    if (o['source'] == 'chat') Padding(padding: const EdgeInsets.only(left: 6), child: Icon(PhosphorIconsFill.sparkle, size: 12, color: c.primary)),
                  ]),
                  const SizedBox(height: 2),
                  Text('${o['number']} · ${dateTime(o['createdAt'] as String?)}', style: TypeX.mono(11.5, color: c.text3), maxLines: 1, overflow: TextOverflow.ellipsis),
                  if (first.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 3), child: Text(first, style: TypeX.ui(12.5, color: c.text2), maxLines: 1, overflow: TextOverflow.ellipsis)),
                  const SizedBox(height: 7),
                  Wrap(spacing: 6, runSpacing: 4, children: [Tag(pay, tone: payTone(pay), dot: true, small: true), Tag(ful, tone: fulTone(ful), dot: true, small: true), if (o['returnRequested'] == true) const Tag('Return', tone: 'danger', small: true)]),
                ])),
                const SizedBox(width: 10),
                Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                  Text(taka(o['total'] as num), style: TypeX.display(16, color: c.text, ls: 0)),
                  const SizedBox(height: 3),
                  Text(plural(units, 'item'), style: TypeX.ui(11.5, color: c.text3)),
                ]),
              ]),
            )),
          ]),
        ),
      ),
    );
  }
}

class _OrderDetail extends StatefulWidget {
  const _OrderDetail({super.key, required this.o});
  final J o;
  @override
  State<_OrderDetail> createState() => _OrderDetailState();
}

class _OrderDetailState extends State<_OrderDetail> {
  String via = 'sms';

  static const steps = ['Placed', 'Paid', 'Packed', 'Shipped', 'Out for delivery', 'Delivered'];

  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    final o = widget.o;
    final cust = o['customer'] as J;
    final pay = o['payment'] as J;
    final stage = o['stage'] as int;
    final times = (o['times'] as List).cast<String>();
    final cancelled = o['fulfillment'] == 'Cancelled';
    final items = (o['items'] as List).cast<J>();
    final log = (o['log'] as List).cast<J>();
    final no = o['number'] as String;
    final phone = SinglePane.of(context);
    final canManage = s.can('orders.manage');

    return Panel(
      child: Column(children: [
        Container(
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 16), decoration: BoxDecoration(border: Border(bottom: BorderSide(color: c.line))),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              if (phone) ...[DkIconButton(PhosphorIconsBold.arrowLeft, onPressed: () => s.selectOrder(null)), const SizedBox(width: 6)],
              Text('Order ', style: TypeX.display(20, color: c.text)),
              Text(no, style: TypeX.mono(20, w: FontWeight.w800, color: c.primary)),
            ]),
            const Gap(8),
            Row(children: [ChannelIcon(kind: (o['channel'] ?? 'web') as String, size: 16), const SizedBox(width: 8), Text('${cust['name']} · ${dateTime(o['createdAt'] as String?)}', style: TypeX.ui(12.5, color: c.text3))]),
            const Gap(10),
            Wrap(spacing: 6, children: [Tag(pay['status'] as String, tone: payTone(pay['status'] as String), dot: true), Tag(o['fulfillment'] as String, tone: fulTone(o['fulfillment'] as String), dot: true), if (o['source'] == 'chat') Tag('Placed in chat', tone: 'ai', icon: PhosphorIconsFill.sparkle)]),
          ]),
        ),
        Expanded(
          child: Container(
            color: c.surface2,
            child: ListView(padding: const EdgeInsets.all(16), children: [
            _next(context, o, pay, cancelled),
            if (o['returnRequested'] == true) ...[
              Container(
                padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: c.warnSoft, borderRadius: BorderRadius.circular(12), border: Border.all(color: c.warn.withValues(alpha: .25))),
                child: Row(children: [Icon(PhosphorIconsFill.warningCircle, size: 18, color: c.warn), const SizedBox(width: 10), Expanded(child: Text.rich(TextSpan(children: [TextSpan(text: 'Return requested. ', style: TypeX.ui(13, w: FontWeight.w800, color: c.text)), TextSpan(text: 'Waiting in Approvals.', style: TypeX.ui(13, color: c.text2))]))), DkButton('Open', small: true, onPressed: () => s.setSection(Section.approvals))]),
              ),
              const Gap(12),
            ],
            SectionCard('Progress', icon: PhosphorIconsRegular.timer, child: Column(children: [
              for (var i = 0; i < steps.length; i++)
                _Step(
                  label: i == 1 && pay['status'] == 'Pending' ? 'Payment on delivery' : (i == 1 && pay['status'] == 'Failed' ? 'Payment failed' : steps[i]),
                  time: i < times.length ? dateTime(times[i]) : (cancelled ? '' : 'Waiting'),
                  done: i <= stage && !(cancelled && i > stage), now: i == stage, last: i == steps.length - 1,
                  failed: i == 1 && pay['status'] == 'Failed',
                ),
            ])),
            SectionCard('Items', icon: PhosphorIconsRegular.shoppingBag, trailing: Text(plural(items.fold<int>(0, (a, i) => a + (i['qty'] as int)), 'item'), style: TypeX.ui(11.5, w: FontWeight.w700, color: c.text3)), child: Column(children: [
              for (final it in items)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(children: [
                    ProductArt(kind: _artFor(it['sku'] as String), size: 46, radius: 11), const SizedBox(width: 12),
                    Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(it['name'] as String, style: TypeX.ui(14, w: FontWeight.w700, color: c.text)), Text('${it['variant']} · Qty ${it['qty']}', style: TypeX.ui(12, color: c.text3))])),
                    Text(taka((it['price'] as num) * (it['qty'] as num)), style: TypeX.mono(13, color: c.text)),
                  ]),
                ),
              const Gap(6), const Rule(), const Gap(8),
              _Sum('Subtotal', taka(o['subtotal'] as num)),
              _Sum('Shipping', (o['shipping'] as num) > 0 ? taka(o['shipping'] as num) : 'Free'),
              _Sum('Total', taka(o['total'] as num), bold: true),
            ])),
            Padding(padding: const EdgeInsets.only(bottom: 12), child: ShippingBox(o: o)),
            Padding(padding: const EdgeInsets.only(bottom: 12), child: PaymentBox(o: o)),
            SectionCard('Messages to the customer', icon: PhosphorIconsRegular.chatText, margin: EdgeInsets.zero, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (log.isEmpty) Text('Nothing sent yet.', style: TypeX.ui(13, color: c.text3)),
              for (final l in log)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Container(width: 30, height: 30, decoration: BoxDecoration(color: c.sunken, borderRadius: BorderRadius.circular(9)), child: Icon(l['c'] == 'wa' ? PhosphorIconsRegular.whatsappLogo : (l['c'] == 'email' ? PhosphorIconsRegular.envelopeSimple : PhosphorIconsRegular.chatText), size: 16, color: c.text2)),
                    const SizedBox(width: 10),
                    Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(l['x'] as String, style: (RegExp(r'[ঀ-৿]').hasMatch(l['x'] as String) ? TypeX.bn(13, w: FontWeight.w600, color: c.text) : TypeX.ui(13, w: FontWeight.w600, color: c.text))), Text('${l['c'] == 'sms' ? 'SMS' : l['c'] == 'wa' ? 'WhatsApp' : 'Email'} · ${l['s']}', style: TypeX.ui(11.5, color: c.text3))])),
                    Text(shortDate(l['t'] as String?), style: TypeX.ui(11.5, color: c.text3)),
                  ]),
                ),
              const Gap(8),
              Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
                Seg<String>(items: const [('sms', 'SMS (বাংলা)'), ('wa', 'WhatsApp'), ('email', 'Email')], value: via, onChanged: (v) => setState(() => via = v), small: true),
                DkButton('Send status update', icon: PhosphorIconsRegular.paperPlaneTilt, small: true, onPressed: !canManage ? null : () => s.orderAction(no, 'notify', success: via == 'sms' ? 'SMS handed to the provider' : 'Update sent', body: {'via': via})),
              ]),
            ])),
          ]),
          ),
        ),
        Container(
          padding: const EdgeInsets.all(14), decoration: BoxDecoration(color: c.surface2, border: Border(top: BorderSide(color: c.line))),
          child: Row(children: [
            if (o['conversationId'] != null) Expanded(child: DkButton('Open conversation', icon: PhosphorIconsRegular.chatCircleText, expand: true, onPressed: () { s.setSection(Section.inbox); s.selectConversation(o['conversationId'] as String); })),
            const SizedBox(width: 8),
            DkButton('Cancel order', kind: BtnKind.danger, onPressed: cancelled || stage >= 3 || !canManage ? null : () => s.orderAction(no, 'cancel', success: 'Order cancelled')),
          ]),
        ),
      ]),
    );
  }

  Widget _next(BuildContext context, J o, J pay, bool cancelled) {
    final cod = ((pay['method'] as String?) ?? '').toLowerCase().contains('cash on delivery');
    final ful = o['fulfillment'] as String;
    final ps = pay['status'] as String;
    if (cancelled) return const NextStep(title: 'Cancelled', body: 'This order was cancelled before shipping. Stock was returned for chat orders.', icon: PhosphorIconsFill.minusCircle, tone: '');
    if (ps == 'Failed') return const NextStep(title: 'Payment failed', body: 'Send a new payment link, or cancel the order.', icon: PhosphorIconsFill.warningCircle, tone: 'danger');
    if (ps == 'Refunded') return const NextStep(title: 'Refunded', body: 'The customer was refunded. Nothing more to do.', icon: PhosphorIconsFill.checkCircle, tone: '');
    if (ps == 'Pending' && !cod) return const NextStep(title: 'Waiting for payment', body: 'Send a payment link, or mark it paid once the customer has paid. A courier can be booked after that.', icon: PhosphorIconsFill.creditCard, tone: 'warn');
    if (ful == 'Unfulfilled') {
      return cod
          ? NextStep(title: 'Confirm by phone, then book a courier', body: 'Cash on delivery: the courier will collect ${taka((o['cod'] ?? o['total']) as num)} from the customer.', icon: PhosphorIconsFill.phone, tone: 'warn')
          : const NextStep(title: 'Ready to ship', body: 'Payment is confirmed. Book a courier below.', icon: PhosphorIconsFill.package, tone: 'ok');
    }
    if (ful == 'In transit') return const NextStep(title: 'With the courier', body: 'Press Refresh tracking to see the latest status. The customer is updated automatically.', icon: PhosphorIconsFill.truck);
    if (ful == 'Delivered') return const NextStep(title: 'Complete', body: 'Delivered and paid. Nothing more to do.', icon: PhosphorIconsFill.checkCircle, tone: 'ok');
    return const SizedBox.shrink();
  }

  String _artFor(String sku) => sku.contains('TB2') ? 'bottle' : (sku.contains('RL3') ? 'tent' : (sku.contains('RB') ? 'boot' : 'jacket'));
}

class _Step extends StatelessWidget {
  const _Step({required this.label, required this.time, required this.done, required this.now, required this.last, this.failed = false});
  final String label, time;
  final bool done, now, last, failed;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final col = failed ? c.danger : c.primary;
    return IntrinsicHeight(
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(width: 22, child: Column(children: [
          AnimatedContainer(
            duration: const Duration(milliseconds: 250), width: 20, height: 20,
            decoration: BoxDecoration(color: done ? col : c.surface, shape: BoxShape.circle, border: Border.all(color: done ? col : c.line2, width: 2), boxShadow: now ? [BoxShadow(color: col.withValues(alpha: .25), blurRadius: 0, spreadRadius: 4)] : null),
            child: done ? Icon(failed ? PhosphorIconsBold.x : PhosphorIconsBold.check, size: 11, color: Colors.white) : null,
          ),
          if (!last) Expanded(child: Container(width: 2, margin: const EdgeInsets.symmetric(vertical: 3), color: done ? col.withValues(alpha: .6) : c.line)),
        ])),
        const SizedBox(width: 12),
        Expanded(child: Padding(padding: EdgeInsets.only(bottom: last ? 0 : 14), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(label, style: TypeX.ui(13.5, w: done ? FontWeight.w700 : FontWeight.w600, color: done ? c.text : c.text3)), Text(time, style: TypeX.ui(12, color: c.text3))]))),
      ]),
    );
  }
}

class _Sum extends StatelessWidget {
  const _Sum(this.k, this.v, {this.bold = false});
  final String k, v;
  final bool bold;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Padding(padding: const EdgeInsets.symmetric(vertical: 3), child: Row(children: [Text(k, style: TypeX.ui(13.5, w: bold ? FontWeight.w800 : FontWeight.w500, color: bold ? c.text : c.text2)), const Spacer(), Text(v, style: bold ? TypeX.display(17, color: c.text, ls: 0) : TypeX.mono(13, color: c.text2))]));
  }
}
