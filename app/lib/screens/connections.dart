import 'package:flutter/material.dart';
import '../brand/icons.dart';
import 'package:provider/provider.dart';
import '../brand/theme.dart';
import '../core/api.dart';
import '../core/state.dart';
import '../widgets/kit.dart';
import '../widgets/page.dart';
import 'channels.dart';
import 'catalog_ui.dart';
import 'guide_ui.dart';
import 'providers_ui.dart';
import 'sms_ui.dart';
import 'inbox.dart' show showSimulator;

class ConnectionsScreen extends StatefulWidget {
  const ConnectionsScreen({super.key});
  @override
  State<ConnectionsScreen> createState() => _ConnectionsScreenState();
}

class _ConnectionsScreenState extends State<ConnectionsScreen> {
  String tab = 'channels';
  @override
  void initState() {
    super.initState();
    context.read<AppState>().loadConnections();
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    int n(String g) => g == 'Store' ? s.catalogSources.length : (g == 'Couriers' || g == 'Payments' || g == 'SMS') ? s.providers.where((p) => p['group'] == g && p['live'] == true && p['status'] == 'ok').length : s.integrations.where((i) => i['grp'] == g && i['status'] == 'ok').length;
    final issues = s.channels.where((x) => x['status'] != 'ok').length;
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        PageHeader(
          title: 'Connections',
          subtitle: Text('Where customers reach you, and the couriers, payments and SMS the assistant and your team use.', style: TypeX.ui(13.5, color: c.text3)),
          actions: [if (s.can('simulate')) DkButton('Simulate a message', icon: PhosphorIconsRegular.chatCircleDots, onPressed: () => showSimulator(context))],
        ),
        Padding(padding: const EdgeInsets.fromLTRB(24, 14, 24, 0), child: const HowToConnect(title: 'How connections work, and what you need', steps: overviewGuide)),
        UnderTabs(value: tab, onChanged: (v) => setState(() => tab = v), tabs: [
          ('channels', 'Channels', s.channels.length),
          ('Couriers', 'Couriers', n('Couriers')),
          ('Payments', 'Payments', n('Payments')),
          ('SMS', 'SMS', n('SMS')),
          ('Store', 'Store', n('Store')),
          ('notify', 'Notifications', null),
        ]),
        if (issues > 0 && tab == 'channels')
          Container(
            margin: const EdgeInsets.fromLTRB(24, 16, 24, 0), padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: c.warnSoft, borderRadius: BorderRadius.circular(12)),
            child: Row(children: [Icon(PhosphorIconsFill.warningCircle, size: 18, color: c.warn), const SizedBox(width: 10), Expanded(child: Text('$issues of ${s.channels.length} channels need attention. Messages may not be arriving.', style: TypeX.ui(13, w: FontWeight.w600, color: c.text)))]),
          ),
        Expanded(child: tab == 'channels' ? const ChannelsTab() : (tab == 'notify' ? const _Notifications() : (tab == 'Couriers' || tab == 'Payments' ? ProviderGrid(group: tab) : tab == 'SMS' ? ProviderGrid(group: 'SMS', footer: const SmsPanel()) : _Providers(group: tab)))),
      ]),
    );
  }
}

// ---------------------------------------------------------------- providers
class _Providers extends StatelessWidget {
  const _Providers({required this.group});
  final String group;
  static const info = {
    'Couriers': 'Book parcels, collect cash on delivery and follow status. The assistant reads tracking from these when customers ask where an order is.',
    'Payments': 'Cash on delivery stays the default in Bangladesh. Mobile wallets and cards are offered as payment links. The assistant never sees a PIN, OTP or card number.',
    'Store': 'Where your products come from, and how orders reach Dakbox.',
  };
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final items = s.integrations.where((i) => i['grp'] == group && i['id'] != 'woo' && i['id'] != 'shopify').toList();
    return LayoutBuilder(builder: (context, box) {
      final cols = (box.maxWidth / 320).floor().clamp(1, 3);
      final cw = (box.maxWidth - 48 - 14 * (cols - 1)) / cols;
      return ListView(padding: const EdgeInsets.all(24), children: [
        Text(info[group] ?? '', style: TypeX.ui(13.5, color: c.text2, h: 1.5)),
        const Gap(10),
        if (group == 'Store') ...[const CatalogPanel(), const Gap(8), Label('Other ways orders and products arrive'), const Gap(10)],
        Wrap(spacing: 14, runSpacing: 14, children: [
          for (var i = 0; i < items.length; i++)
            SizedBox(width: cw, child: Reveal(delay: i * 40, child: _Provider(p: items[i]))),
        ]),
      ]);
    });
  }
}

class _Provider extends StatelessWidget {
  const _Provider({required this.p});
  final J p;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.read<AppState>();
    final on = p['status'] == 'ok';
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(18), border: Border.all(color: on ? c.primaryLine : c.line)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Container(width: 38, height: 38, alignment: Alignment.center, decoration: BoxDecoration(gradient: on ? c.brand : null, color: on ? null : c.sunken, borderRadius: BorderRadius.circular(11)), child: Text(p['letter'] as String, style: TypeX.display(17, color: on ? Colors.white : c.text2, ls: 0))),
          const SizedBox(width: 12),
          Expanded(child: Text(p['name'] as String, style: TypeX.ui(14.5, w: FontWeight.w800, color: c.text), maxLines: 2)),
          Tag(on ? 'Connected' : 'Not connected', tone: on ? 'ok' : '', dot: true, small: true),
        ]),
        const Gap(12),
        Text(p['note'] as String, style: TypeX.ui(12.5, color: c.text3, h: 1.45)),
        const Gap(14),
        DkButton(on ? 'Disconnect' : 'Connect', kind: on ? BtnKind.ghost : BtnKind.soft, small: true, onPressed: s.can('connections.write') ? () => s.setIntegration(p['id'] as String, !on) : null),
      ]),
    );
  }
}

// ---------------------------------------------------------------- notifications
class _Notifications extends StatelessWidget {
  const _Notifications();
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    Widget head(String t) => SizedBox(width: 64, child: Center(child: Text(t, style: TypeX.ui(12, w: FontWeight.w800, color: c.text3))));
    return ListView(padding: const EdgeInsets.all(24), children: [
      const HowToConnect(title: 'How notifications work', steps: ['Connect an SMS provider first (Connections, SMS). Without one, order updates are listed as Not sent.', 'Tick the SMS box on the events you want texted. WhatsApp and Email boxes are demo only for now.', 'Automatic SMS wait until 08:00 during quiet hours; limits and quiet hours are under Connections, SMS.']),
      const HowToConnect(title: 'How notifications work', steps: notificationsGuide),
      Text('When this happens, tell the customer by', style: TypeX.display(17, color: c.text)),
      const Gap(4),
      Text('Automatic SMS wait until 08:00 Bangladesh time during quiet hours (set under Connections, SMS). Dakbox only sends order updates, never promotions: promotional SMS follow BTRC rules, so confirm them with your SMS provider before sending any. Order placed and Out for delivery have no trigger yet: orders are not created in Dakbox, and no courier status maps to out for delivery.', style: TypeX.ui(13, color: c.text3, h: 1.5)),
      const Gap(16),
      Container(
        decoration: BoxDecoration(border: Border.all(color: c.line), borderRadius: BorderRadius.circular(16)),
        clipBehavior: Clip.antiAlias,
        child: Column(children: [
          Container(color: c.surface2, padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10), child: Row(children: [const Expanded(child: SizedBox()), head('SMS'), head('WhatsApp'), head('Email')])),
          for (var i = 0; i < s.notifications.length; i++)
            Container(
              decoration: BoxDecoration(border: Border(top: BorderSide(color: c.line))), padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              child: Row(children: [
                Expanded(child: Text(s.notifications[i]['e'] as String, style: TypeX.ui(14, w: FontWeight.w600, color: c.text))),
                for (final k in ['sms', 'wa', 'em']) SizedBox(width: 64, child: Center(child: DkSwitch(value: (s.notifications[i][k] ?? 0) == 1, onChanged: !s.can('connections.write') ? null : (v) { s.notifications[i][k] = v ? 1 : 0; s.saveNotifications(); s.touch(); }))),
              ]),
            ),
        ]),
      ),
    ]);
  }
}
