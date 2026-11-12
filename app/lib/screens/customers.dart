import 'package:flutter/material.dart';
import '../brand/icons.dart';
import 'package:provider/provider.dart';
import '../brand/theme.dart';
import '../core/api.dart';
import '../core/format.dart';
import '../core/state.dart';
import '../widgets/kit.dart';
import '../widgets/page.dart';

class CustomersScreen extends StatefulWidget {
  const CustomersScreen({super.key});
  @override
  State<CustomersScreen> createState() => _CustomersScreenState();
}

class _CustomersScreenState extends State<CustomersScreen> {
  String tab = 'all';

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final all = s.customers;
    bool has(J x, String t) => (x['tags'] as List).contains(t);
    bool match(J x) => switch (tab) {
          'repeat' => (x['orders'] as int) >= 2,
          'cart' => has(x, 'Cart open'),
          'chat' => has(x, 'Chat order'),
          'new' => (x['orders'] as int) == 0,
          _ => true,
        };
    final q = s.customerQuery.toLowerCase();
    final rows = all.where((x) => match(x) && (q.isEmpty || '${x['name']} ${x['area'] ?? ''}'.toLowerCase().contains(q))).toList();
    final repeat = all.where((x) => (x['orders'] as int) >= 2).length;
    final revenue = all.fold<num>(0, (t, x) => t + (x['spent'] as num));
    final carts = all.where((x) => has(x, 'Cart open')).length;
    final wide = MediaQuery.of(context).size.width > 1000;
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        PageHeader(
          title: 'Customers',
          subtitle: Row(mainAxisSize: MainAxisSize.min, children: [Text('Everyone who has chatted or ordered', style: TypeX.ui(13.5, color: c.text3)), const SizedBox(width: 8), const Tag('Sample data', tone: 'warn', small: true)]),
          actions: [SearchBox(hint: 'Search name or area', width: 240, onChanged: s.setCustomerQuery)],
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(24, 0, 24, 14),
          child: Row(children: [
            StatTile(value: '${all.length}', label: 'Customers', icon: PhosphorIconsRegular.users, active: tab == 'all', onTap: () => setState(() => tab = 'all')),
            const SizedBox(width: 8),
            StatTile(value: '$repeat', label: 'Repeat buyers', icon: PhosphorIconsRegular.arrowCounterClockwise, tone: 'ok', active: tab == 'repeat', onTap: () => setState(() => tab = 'repeat')),
            const SizedBox(width: 8),
            StatTile(value: '$carts', label: 'Open carts', icon: PhosphorIconsRegular.shoppingCart, tone: 'warn', active: tab == 'cart', onTap: () => setState(() => tab = 'cart')),
            const SizedBox(width: 8),
            StatTile(value: taka(revenue), label: 'Lifetime revenue', icon: PhosphorIconsRegular.coins),
          ]),
        ),
        UnderTabs(value: tab, onChanged: (v) => setState(() => tab = v), tabs: [
          ('all', 'All', all.length),
          ('repeat', 'Repeat buyers', repeat),
          ('cart', 'Open cart', carts),
          ('chat', 'Ordered in chat', all.where((x) => has(x, 'Chat order')).length),
          ('new', 'No orders yet', all.where((x) => (x['orders'] as int) == 0).length),
        ]),
        if (wide)
          Container(
            padding: const EdgeInsets.fromLTRB(26, 9, 26, 9), decoration: BoxDecoration(color: c.surface2, border: Border(bottom: BorderSide(color: c.line))),
            child: Row(children: [
              const Expanded(flex: 4, child: Label('Customer')), const SizedBox(width: 60, child: Label('Orders')), const SizedBox(width: 110, child: Label('Spent')), const SizedBox(width: 100, child: Label('Last order')), const Expanded(flex: 3, child: Label('Tags')), const SizedBox(width: 144),
            ]),
          ),
        Expanded(
          child: rows.isEmpty
              ? const Empty('No customers match', icon: PhosphorIconsDuotone.users)
              : ListView.separated(
                  padding: const EdgeInsets.fromLTRB(14, 6, 14, 14), itemCount: rows.length,
                  separatorBuilder: (_, __) => Container(height: 1, margin: const EdgeInsets.symmetric(horizontal: 12), color: c.line),
                  itemBuilder: (_, i) => _Row(x: rows[i], wide: wide),
                ),
        ),
      ]),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.x, required this.wide});
  final J x;
  final bool wide;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.read<AppState>();
    final tags = (x['tags'] as List).cast<String>();
    final id = x['conversationId'] as String?;
    final who = Row(children: [
      Avatar(name: x['name'] as String, hue: x['hue'] as num, size: 42, channel: x['channel'] as String?),
      const SizedBox(width: 12),
      Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(x['name'] as String, style: TypeX.ui(14.5, w: FontWeight.w800, color: c.text), maxLines: 1, overflow: TextOverflow.ellipsis),
        Text('${channelName(x['channel'] as String?)}${x['area'] != null ? ' · ${x['area']}' : ''}${x['phone'] != null ? ' · ${x['phone']}' : ''}', style: TypeX.ui(12, color: c.text3), maxLines: 1, overflow: TextOverflow.ellipsis),
      ])),
    ]);
    final erasable = s.role == 'owner' && x['id'] != null;
    final menu = erasable
        ? PopupMenuButton<String>(
            tooltip: 'More', color: c.surface, icon: Icon(PhosphorIconsRegular.dotsThreeVertical, size: 18, color: c.text3), padding: EdgeInsets.zero,
            onSelected: (_) => showDialog<void>(context: context, barrierColor: Colors.black.withValues(alpha: .45), builder: (_) => _EraseDialog(id: x['id'] as String, name: x['name'] as String)),
            itemBuilder: (_) => [PopupMenuItem<String>(value: 'erase', child: Row(children: [Icon(PhosphorIconsRegular.eyeSlash, size: 18, color: c.danger), const SizedBox(width: 10), Text('Erase personal data…', style: TypeX.ui(13.5, w: FontWeight.w600, color: c.danger))]))],
          )
        : const SizedBox(width: 40);
    final open = SizedBox(width: 144, child: Row(mainAxisAlignment: MainAxisAlignment.end, children: [if (id != null) DkButton('Open chat', small: true, onPressed: () { s.setSection(Section.inbox); s.selectConversation(id); }), SizedBox(width: 40, child: menu)]));
    return Hover(
      builder: (_, h, __) => AnimatedContainer(
        duration: const Duration(milliseconds: 130), padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
        decoration: BoxDecoration(color: h ? c.surface2 : c.surface2.withValues(alpha: 0), borderRadius: BorderRadius.circular(14)),
        child: wide
            ? Row(children: [
                Expanded(flex: 4, child: who),
                SizedBox(width: 60, child: Text('${x['orders']}', style: TypeX.mono(13.5, w: FontWeight.w700, color: (x['orders'] as int) == 0 ? c.text3 : c.text))),
                SizedBox(width: 110, child: Text((x['spent'] as num) > 0 ? taka(x['spent'] as num) : '—', style: TypeX.mono(13.5, color: (x['spent'] as num) > 0 ? c.text : c.text3))),
                SizedBox(width: 100, child: Text(x['lastOrder'] == null ? '—' : shortDate(x['lastOrder'] as String?), style: TypeX.ui(13, color: c.text2))),
                Expanded(flex: 3, child: Wrap(spacing: 5, runSpacing: 4, children: [for (final t in tags.take(3)) Tag(t, small: true)])),
                open,
              ])
            : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                who, const SizedBox(height: 10),
                Row(children: [Text('${x['orders']} orders · ${taka(x['spent'] as num)}', style: TypeX.mono(12.5, color: c.text2)), const Spacer(), if (id != null) DkButton('Open chat', small: true, onPressed: () { s.setSection(Section.inbox); s.selectConversation(id); }), if (erasable) SizedBox(width: 40, child: menu)]),
                if (tags.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 8), child: Wrap(spacing: 5, runSpacing: 4, children: [for (final t in tags) Tag(t, small: true)])),
              ]),
      ),
    );
  }
}


class _EraseDialog extends StatefulWidget {
  const _EraseDialog({required this.id, required this.name});
  final String id, name;
  @override
  State<_EraseDialog> createState() => _EraseDialogState();
}

class _EraseDialogState extends State<_EraseDialog> {
  bool busy = false;
  String? error;
  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    return Dialog(
      backgroundColor: Colors.transparent, insetPadding: const EdgeInsets.all(20),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 460),
        child: Panel(radius: 24, child: Padding(padding: const EdgeInsets.all(24), child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Erase ${widget.name}’s personal data?', style: TypeX.display(20, color: c.text)),
          const Gap(8),
          Text('Their name, phone number, address and the words of their messages are removed for good, here and in your SMS log. Orders and amounts stay in your books under an anonymous customer. This cannot be undone.', style: TypeX.ui(13.5, color: c.text2, h: 1.5)),
          if (error != null) Container(margin: const EdgeInsets.only(top: 12), padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: c.dangerSoft, borderRadius: BorderRadius.circular(12)), child: Text(error!, style: TypeX.ui(13, w: FontWeight.w600, color: c.text))),
          const Gap(20),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
            const Gap(8),
            DkButton(busy ? 'Erasing…' : 'Erase for good', kind: BtnKind.primary, onPressed: busy ? null : () async {
              setState(() { busy = true; error = null; });
              final r = await s.eraseCustomer(widget.id);
              if (!context.mounted) return;
              if (r['error'] != null) { setState(() { busy = false; error = r['error'] as String; }); return; }
              Navigator.pop(context);
              s.toast('Personal data erased.');
              s.loadCustomers();
            }),
          ]),
        ]))),
      ),
    );
  }
}
