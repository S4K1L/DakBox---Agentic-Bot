import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../brand/icons.dart';
import '../brand/theme.dart';
import '../core/api.dart';
import '../core/format.dart';
import '../core/state.dart';
import '../widgets/kit.dart';
import 'guide_ui.dart';

Future<void> _dialog(BuildContext context, Widget d) => showDialog<void>(context: context, barrierColor: Colors.black.withValues(alpha: .45), builder: (_) => d);

class ProviderGrid extends StatelessWidget {
  const ProviderGrid({super.key, required this.group, this.footer});
  final String group;
  final Widget? footer;
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final items = s.providers.where((p) => p['group'] == group).toList();
    return LayoutBuilder(builder: (context, box) {
      final cols = (box.maxWidth / 340).floor().clamp(1, 3);
      final cw = (box.maxWidth - 48 - 14 * (cols - 1)) / cols;
      return ListView(padding: const EdgeInsets.all(24), children: [
        HowToConnect(title: 'How to connect ${group == 'Payments' ? 'a payment provider' : group == 'SMS' ? 'SMS' : 'a courier'}', steps: groupGuides[group] ?? const [], open: items.every((p) => p['live'] != true)),
        const Gap(2),
        if (items.isEmpty) Padding(padding: const EdgeInsets.all(24), child: Center(child: CircularProgressIndicator(color: c.primary, strokeWidth: 3))),
        Wrap(spacing: 14, runSpacing: 14, children: [for (var i = 0; i < items.length; i++) SizedBox(width: cw, child: Reveal(delay: i * 40, child: _Card(p: items[i])))]),
        if (footer != null) ...[const Gap(28), footer!],
      ]);
    });
  }
}

class _Card extends StatefulWidget {
  const _Card({required this.p});
  final J p;
  @override
  State<_Card> createState() => _CardState();
}

class _CardState extends State<_Card> {
  bool busy = false;

  @override
  Widget build(BuildContext context) {
    final p = widget.p;
    final c = context.c;
    final s = context.read<AppState>();
    final canWrite = s.can('connections.write');
    final supported = p['supported'] == true;
    final live = p['live'] == true;
    final ok = p['status'] == 'ok';
    final mode = p['mode'] as String?;
    final id = p['id'] as String;
    final err = p['lastError'] as String?;
    final builtIn = p['builtIn'] == true;
    final (label, tone) = builtIn ? ('Built in', 'ok') : !supported ? ('Not built', '') : (live ? (ok ? ('Connected', 'ok') : ('Needs attention', 'warn')) : ('Not connected', ''));
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(18), border: Border.all(color: live && ok ? c.primaryLine : (live ? c.warn.withValues(alpha: .5) : c.line))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Container(width: 40, height: 40, alignment: Alignment.center, decoration: BoxDecoration(gradient: live && ok ? c.brand : null, color: live && ok ? null : c.sunken, borderRadius: BorderRadius.circular(12)), child: Text(p['letter'] as String, style: TypeX.display(18, color: live && ok ? Colors.white : c.text2, ls: 0))),
          const SizedBox(width: 12),
          Expanded(child: Text(p['name'] as String, style: TypeX.ui(14.5, w: FontWeight.w800, color: c.text), maxLines: 2)),
          Tag(label, tone: tone, dot: true, small: true),
        ]),
        const Gap(10),
        Wrap(spacing: 6, runSpacing: 6, children: [
          if (supported && live && mode != null && (p['modes'] as List).isNotEmpty) Tag(mode == 'live' ? 'Live money' : 'Sandbox', tone: mode == 'live' ? 'accent' : 'ai', small: true),
          if (supported) Tag(p['officialDocs'] == true ? 'Built to official docs' : 'Docs unverified', tone: p['officialDocs'] == true ? 'ok' : 'warn', small: true),
          if (supported && p['kind'] == 'sms') Tag(p['hasReport'] == true ? 'Delivery reports' : 'No delivery reports', tone: p['hasReport'] == true ? 'ok' : 'warn', small: true),
        ]),
        const Gap(10),
        Text(builtIn ? 'Needs no setup. The courier collects the cash, and Dakbox marks the order paid when the parcel is delivered.' : supported ? (live ? 'Verified as ${p['verifiedName'] ?? id}.' : (p['kind'] == 'courier' ? 'Not connected. Orders can only get a demo label.' : p['kind'] == 'sms' ? 'Not connected. Order updates are shown as “Not sent”.' : 'Not connected. Payment links need a connected provider.')) : (p['notBuiltReason'] as String? ?? 'Not built.'), style: TypeX.ui(12.5, color: c.text3, h: 1.45)),
        if (err != null && supported) Container(margin: const EdgeInsets.only(top: 10), padding: const EdgeInsets.all(10), decoration: BoxDecoration(color: c.warnSoft, borderRadius: BorderRadius.circular(10)), child: Text(err, style: TypeX.ui(12, color: c.text2, h: 1.4))),
        if (supported && live && p['lastCheckAt'] != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text('Last checked ${relative(p['lastCheckAt'] as String?)}', style: TypeX.ui(11.5, color: c.text3))),
        if (supported && canWrite) ...[
          const Gap(14),
          Wrap(spacing: 8, runSpacing: 8, children: [
            if (p['guide'] != null) DkButton('How to connect', icon: PhosphorIconsRegular.lightbulb, small: true, kind: BtnKind.ghost, onPressed: () => _dialog(context, _GuideDialog(p: p))),
            if (!live) DkButton('Connect', icon: PhosphorIconsBold.plugsConnected, kind: BtnKind.soft, small: true, onPressed: () => _dialog(context, _ConnectDialog(p: p))),
            if (live) DkButton(busy ? 'Checking…' : 'Check now', icon: PhosphorIconsRegular.heartbeat, small: true, onPressed: busy ? null : () async {
              setState(() => busy = true);
              final r = await s.checkProvider(id);
              if (!mounted) return;
              setState(() => busy = false);
              s.toast((r['error'] ?? r['message']) as String, error: r['error'] != null || r['ok'] == false);
            }),
            if (live && p['kind'] == 'sms') DkButton('Send test SMS', icon: PhosphorIconsRegular.paperPlaneTilt, small: true, onPressed: () => _dialog(context, _TestSmsDialog(p: p))),
            if (live && (p['urls'] as List).isNotEmpty) DkButton('Setup URLs', small: true, onPressed: () => _dialog(context, _UrlsDialog(p: p))),
            if (live) DkButton('Reconnect', small: true, kind: BtnKind.ghost, onPressed: () => _dialog(context, _ConnectDialog(p: p))),
            if (live) DkButton('Disconnect', small: true, kind: BtnKind.danger, onPressed: () => _dialog(context, _DisconnectDialog(p: p))),
          ]),
        ],
      ]),
    );
  }
}

class _Shell extends StatelessWidget {
  const _Shell({required this.title, required this.children, this.width = 540});
  final String title;
  final List<Widget> children;
  final double width;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Dialog(
      backgroundColor: Colors.transparent, insetPadding: const EdgeInsets.all(20),
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: width, maxHeight: 780),
        child: Panel(radius: 24, child: SingleChildScrollView(padding: const EdgeInsets.all(24), child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [Expanded(child: Text(title, style: TypeX.display(21, color: c.text))), DkIconButton(PhosphorIconsBold.x, size: 32, onPressed: () => Navigator.pop(context))]),
          const Gap(14),
          ...children,
        ]))),
      ),
    );
  }
}

class _Banner extends StatelessWidget {
  const _Banner(this.text, {this.danger = false});
  final String text;
  final bool danger;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      margin: const EdgeInsets.only(bottom: 14), padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: danger ? c.dangerSoft : c.warnSoft, borderRadius: BorderRadius.circular(12), border: Border.all(color: (danger ? c.danger : c.warn).withValues(alpha: .25))),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Icon(PhosphorIconsFill.warningCircle, size: 18, color: danger ? c.danger : c.warn), const SizedBox(width: 10), Expanded(child: Text(text, style: TypeX.ui(12.5, w: FontWeight.w600, color: c.text, h: 1.45)))]),
    );
  }
}

class _ConnectDialog extends StatefulWidget {
  const _ConnectDialog({required this.p});
  final J p;
  @override
  State<_ConnectDialog> createState() => _ConnectDialogState();
}

class _ConnectDialogState extends State<_ConnectDialog> {
  late String mode = ((widget.p['modes'] as List).isEmpty ? 'live' : ((widget.p['mode'] as String?) ?? 'sandbox'));
  final Map<String, TextEditingController> ctl = {};
  String? error;
  bool busy = false;

  TextEditingController _c(String k, [String? init]) => ctl.putIfAbsent(k, () => TextEditingController(text: init ?? ''));

  @override
  void dispose() { for (final c in ctl.values) { c.dispose(); } super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final p = widget.p;
    final c = context.c;
    final s = context.read<AppState>();
    final modes = (p['modes'] as List).cast<String>();
    final fields = (p['fields'] as List).cast<J>();
    final cfgFields = (p['configFields'] as List).cast<J>();
    final extra = (p['extra'] as Map?) ?? {};
    final isPayment = p['kind'] == 'payment';
    return _Shell(title: 'Connect ${p['name']}', children: [
      if (p['guide'] != null) HowToConnect(steps: ((p['guide'] as Map)['steps'] as List).cast<String>(), where: (p['guide'] as Map)['where'] as String?),
      if (p['officialDocs'] != true) const _Banner('Dakbox could not read this provider’s official API documentation (it is only available to logged-in merchants). The connection is verified live, every booking needs your confirmation, and tracking re-checks with the courier. Still: book ONE test parcel first, and compare Dakbox’s requests with the docs in your dashboard.'),
      if (p['id'] == 'sslwireless') const _Banner('SSL Wireless only accepts requests from IP addresses you whitelist in the ISMS Plus portal. Whitelist this server first, or every send fails with a “blocked IP” message. Its documentation has no balance or status call, so connecting sends one real test SMS.'),
      if (p['id'] == 'alphasms') const _Banner('Dakbox checks the API key by reading your balance (nothing is sent). Alpha SMS documents delivery reports but not every status; Dakbox only shows “Delivered” when Alpha SMS says so.'),
      if (isPayment && mode == 'live') const _Banner('Live mode moves real money. Use sandbox first, and make sure your public https URL is set under Channels, Meta app (it is shared).', danger: true),
      if (error != null) _Banner(error!, danger: true),
      if (modes.isNotEmpty) ...[
        Text('Environment', style: TypeX.ui(12.5, w: FontWeight.w700, color: c.text2)),
        const Gap(6),
        Seg<String>(items: [for (final m in modes) (m, m == 'live' ? 'Live' : 'Sandbox')], value: mode, onChanged: (v) => setState(() => mode = v), small: true),
        const Gap(14),
      ],
      for (final f in fields) ...[
        DkField(controller: _c(f['key'] as String, f['secret'] == true ? null : (f['hint'] as String?)), label: f['label'] as String, obscure: f['secret'] == true, mono: f['secret'] != true),
        if ((f['help'] as String?)?.isNotEmpty ?? false) Padding(padding: const EdgeInsets.only(top: 5), child: Text(f['help'] as String, style: TypeX.ui(12, color: c.text3, h: 1.4))),
        const Gap(12),
      ],
      if (p['id'] == 'bkash' && mode == 'live') ...[
        DkField(controller: _c('base_url', (p['baseUrl'] as String?) ?? ''), label: (extra['base_url'] as Map)['label'] as String, mono: true),
        Padding(padding: const EdgeInsets.only(top: 5), child: Text((extra['base_url'] as Map)['help'] as String, style: TypeX.ui(12, color: c.text3, h: 1.4))),
        const Gap(12),
      ],
      for (final f in cfgFields) ...[
        DkField(controller: _c('cfg_${f['key']}', '${f['value'] ?? ''}'), label: f['label'] as String, mono: true),
        if ((f['help'] as String?)?.isNotEmpty ?? false) Padding(padding: const EdgeInsets.only(top: 5), child: Text(f['help'] as String, style: TypeX.ui(12, color: c.text3, h: 1.4))),
        const Gap(12),
      ],
      if (p['needsTest'] == true) ...[
        DkField(controller: _c('test_number'), label: 'Send a test SMS to (01XXXXXXXXX)', mono: true),
        Padding(padding: const EdgeInsets.only(top: 5), child: Text('Your own phone. It is the only way to prove these credentials, and the number is not saved.', style: TypeX.ui(12, color: c.text3, h: 1.4))),
        const Gap(12),
      ],
      const Gap(8),
      Row(mainAxisAlignment: MainAxisAlignment.end, children: [
        DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
        const Gap(8),
        DkButton(busy ? 'Checking with ${p['name']}…' : 'Verify and connect', icon: PhosphorIconsBold.plugsConnected, kind: BtnKind.primary, onPressed: busy ? null : () async {
          setState(() { busy = true; error = null; });
          final values = {for (final f in fields) f['key'] as String: _c(f['key'] as String).text.trim()};
          final config = {for (final f in cfgFields) f['key'] as String: _c('cfg_${f['key']}').text.trim(), if (p['id'] == 'bkash' && mode == 'live') 'base_url': _c('base_url').text.trim(), if (p['needsTest'] == true) 'test_number': _c('test_number').text.trim()};
          final r = await s.connectProvider(p['id'] as String, {'mode': mode, 'values': values, 'config': config});
          if (!mounted) return;
          for (final f in fields.where((f) => f['secret'] == true)) { _c(f['key'] as String).clear(); }
          if (r['error'] != null) { setState(() { busy = false; error = r['error'] as String; }); } else { Navigator.pop(context); s.toast('${p['name']} connected (${mode == 'live' ? 'live' : 'sandbox'})'); }
        }),
      ]),
    ]);
  }
}

class _UrlsDialog extends StatelessWidget {
  const _UrlsDialog({required this.p});
  final J p;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.read<AppState>();
    final urls = (p['urls'] as List).cast<J>();
    final secret = p['webhookSecret'] as String?;
    final hasPublic = ((s.metaApp['publicUrl'] as String?) ?? '').isNotEmpty;
    Widget copyRow(String label, String value) => Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(label, style: TypeX.ui(12.5, w: FontWeight.w700, color: c.text2)),
            const SizedBox(height: 6),
            Hover(
              onTap: () { Clipboard.setData(ClipboardData(text: value)); s.toast('Copied'); },
              builder: (_, h, __) => Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10), decoration: BoxDecoration(color: c.sunken, borderRadius: BorderRadius.circular(10), border: Border.all(color: h ? c.primary : c.line)), child: Row(children: [Expanded(child: Text(value, style: TypeX.mono(12, color: c.text))), Icon(PhosphorIconsRegular.copy, size: 15, color: c.text3)])),
            ),
          ]),
        );
    return _Shell(title: '${p['name']} setup URLs', width: 560, children: [
      if (!hasPublic) const _Banner('No public https URL is saved yet, so these show this server’s current address. Providers can only reach a public address: set it under Channels, Meta app.'),
      for (final u in urls) copyRow(u['label'] as String, u['url'] as String),
      if (secret != null) copyRow('Webhook secret (use as the Bearer token)', secret),
      Align(alignment: Alignment.centerRight, child: DkButton('Done', kind: BtnKind.primary, onPressed: () => Navigator.pop(context))),
    ]);
  }
}

class _DisconnectDialog extends StatelessWidget {
  const _DisconnectDialog({required this.p});
  final J p;
  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    return _Shell(title: 'Disconnect ${p['name']}?', width: 460, children: [
      Text('Dakbox deletes the saved credentials. ${p['kind'] == 'sms' ? 'Order updates stop going out and are shown as “Not sent”. Messages already queued for the morning are not sent. ' : p['kind'] == 'payment' ? 'Payment links already sent will still work at the provider but can no longer be confirmed here, so a customer who pays through one would need to be marked paid by hand. ' : 'Parcels already booked stay booked, but tracking stops refreshing. '}Orders and history are kept.', style: TypeX.ui(13, color: c.text2, h: 1.5)),
      const Gap(22),
      Row(mainAxisAlignment: MainAxisAlignment.end, children: [
        DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
        const Gap(8),
        DkButton('Disconnect', kind: BtnKind.danger, onPressed: () async { Navigator.pop(context); await s.disconnectProvider(p['id'] as String); s.toast('${p['name']} disconnected'); }),
      ]),
    ]);
  }
}


class _TestSmsDialog extends StatefulWidget {
  const _TestSmsDialog({required this.p});
  final J p;
  @override
  State<_TestSmsDialog> createState() => _TestSmsDialogState();
}

class _TestSmsDialogState extends State<_TestSmsDialog> {
  final to = TextEditingController();
  String? error, done;
  bool busy = false;
  @override
  void dispose() { to.dispose(); super.dispose(); }
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.read<AppState>();
    return _Shell(title: 'Send a test SMS', width: 460, children: [
      Text('Sends one real message through ${widget.p['name']} and uses a little of your balance.', style: TypeX.ui(13, color: c.text2, h: 1.5)),
      const Gap(14),
      if (error != null) _Banner(error!, danger: true),
      if (done != null) Container(margin: const EdgeInsets.only(bottom: 14), padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: c.okSoft, borderRadius: BorderRadius.circular(12)), child: Text(done!, style: TypeX.ui(12.5, w: FontWeight.w600, color: c.text, h: 1.45))),
      DkField(controller: to, label: 'Mobile number (01XXXXXXXXX)', mono: true),
      const Gap(20),
      Row(mainAxisAlignment: MainAxisAlignment.end, children: [
        DkButton('Close', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
        const Gap(8),
        DkButton(busy ? 'Sending…' : 'Send test', icon: PhosphorIconsRegular.paperPlaneTilt, kind: BtnKind.primary, onPressed: busy ? null : () async {
          setState(() { busy = true; error = null; done = null; });
          final r = await s.testSms(widget.p['id'] as String, to.text.trim());
          if (!mounted) return;
          setState(() { busy = false; if (r['error'] != null) { error = r['error'] as String; } else { done = r['message'] as String; } });
        }),
      ]),
    ]);
  }
}


class _GuideDialog extends StatelessWidget {
  const _GuideDialog({required this.p});
  final J p;
  @override
  Widget build(BuildContext context) {
    final g = (p['guide'] as Map).cast<String, dynamic>();
    final live = p['live'] == true;
    return _Shell(title: 'How to connect ${p['name']}', width: 560, children: [
      GuideSteps(steps: (g['steps'] as List).cast<String>(), where: g['where'] as String?),
      const Gap(8),
      Row(mainAxisAlignment: MainAxisAlignment.end, children: [
        DkButton('Close', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
        if (!live) ...[const Gap(8), DkButton('Connect now', icon: PhosphorIconsBold.plugsConnected, kind: BtnKind.primary, onPressed: () { Navigator.pop(context); _dialog(context, _ConnectDialog(p: p)); })],
      ]),
    ]);
  }
}
