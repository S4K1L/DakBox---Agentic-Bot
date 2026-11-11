import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../brand/theme.dart';
import '../core/api.dart';
import '../core/format.dart';
import '../core/state.dart';
import '../widgets/kit.dart';

/// Under the SMS provider cards: what was sent, the guard rails, and the recent messages.
class SmsPanel extends StatefulWidget {
  const SmsPanel({super.key});
  @override
  State<SmsPanel> createState() => _SmsPanelState();
}

class _SmsPanelState extends State<SmsPanel> {
  bool? quiet;
  final per = TextEditingController(), day = TextEditingController();
  bool seeded = false, busy = false;

  @override
  void initState() {
    super.initState();
    context.read<AppState>().loadSms();
  }

  @override
  void dispose() { per.dispose(); day.dispose(); super.dispose(); }

  static (String, String) _tone(String st) => switch (st) {
        'Delivered' => ('ok', 'Delivered'),
        'Accepted' => ('accent', 'Accepted'),
        'Sent' => ('accent', 'Sent'),
        'Queued' => ('warn', 'Waiting'),
        'Sending' => ('warn', 'Sending'),
        'Unknown' => ('warn', 'Unknown'),
        'Failed' => ('danger', 'Failed'),
        _ => ('', st),
      };

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final d = s.sms;
    if (d.isEmpty) return const SizedBox.shrink();
    final st = (d['settings'] as Map).cast<String, dynamic>();
    final u = (d['usage'] as Map).cast<String, dynamic>();
    final msgs = (d['messages'] as List).cast<J>();
    if (!seeded) { seeded = true; quiet = st['quiet'] == true; per.text = '${st['perNumberDay']}'; day.text = '${st['perDay']}'; }
    final canWrite = s.can('connections.write');
    Widget stat(String v, String l, {bool warn = false}) => Expanded(child: Container(
          padding: const EdgeInsets.all(14), decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(16), border: Border.all(color: warn ? c.warn.withValues(alpha: .5) : c.line)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(v, style: TypeX.display(24, color: warn ? c.warn : c.text)), const SizedBox(height: 2), Text(l, style: TypeX.ui(12, color: c.text3))])));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Last 24 hours', style: TypeX.display(17, color: c.text)),
      const Gap(10),
      Row(children: [
        stat('${u['sent24h']}', 'messages sent'), const SizedBox(width: 10),
        stat('${u['parts24h']}', 'SMS parts billed'), const SizedBox(width: 10),
        stat('${u['queued']}', 'waiting for morning'), const SizedBox(width: 10),
        stat('${u['failed24h']}', 'failed', warn: (u['failed24h'] as int) > 0),
      ]),
      const Gap(24),
      Text('Guard rails', style: TypeX.display(17, color: c.text)),
      const Gap(10),
      Container(
        padding: const EdgeInsets.all(16), decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(16), border: Border.all(color: c.line)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Quiet hours', style: TypeX.ui(14, w: FontWeight.w700, color: c.text)),
              Text('Automatic messages wait until ${st['quietTo'].toString().padLeft(2, '0')}:00 Bangladesh time if they come due between ${st['quietFrom']}:00 and then. A person pressing Send is never held.', style: TypeX.ui(12.5, color: c.text3, h: 1.4)),
            ])),
            const SizedBox(width: 14),
            DkSwitch(value: quiet ?? true, onChanged: canWrite ? (v) => setState(() => quiet = v) : null),
          ]),
          const Gap(14),
          Row(children: [
            Expanded(child: DkField(controller: per, label: 'Most messages to one number per 24 hours', mono: true)),
            const SizedBox(width: 12),
            Expanded(child: DkField(controller: day, label: 'Most messages in total per 24 hours', mono: true)),
          ]),
          const Gap(14),
          Align(alignment: Alignment.centerRight, child: DkButton(busy ? 'Saving…' : 'Save', kind: BtnKind.soft, small: true, onPressed: !canWrite || busy ? null : () async {
            setState(() => busy = true);
            final r = await s.saveSmsSettings({'quiet': quiet ?? true, 'quietFrom': st['quietFrom'], 'quietTo': st['quietTo'], 'perNumberDay': int.tryParse(per.text.trim()) ?? 6, 'perDay': int.tryParse(day.text.trim()) ?? 500});
            if (!mounted) return;
            setState(() => busy = false);
            s.toast(r['error'] != null ? r['error'] as String : 'SMS limits saved', error: r['error'] != null);
          })),
        ]),
      ),
      const Gap(24),
      Text('Recent messages', style: TypeX.display(17, color: c.text)),
      const Gap(4),
      Text('“Accepted” means the provider took the message. Only a provider that publishes delivery reports can move it to “Delivered”; SSL Wireless documents none.', style: TypeX.ui(12.5, color: c.text3, h: 1.4)),
      const Gap(12),
      if (msgs.isEmpty)
        Container(padding: const EdgeInsets.all(24), decoration: BoxDecoration(border: Border.all(color: c.line), borderRadius: BorderRadius.circular(16)), child: Center(child: Text('Nothing sent yet. Messages appear here when an order ships, is delivered or refunded.', style: TypeX.ui(13, color: c.text3))))
      else
        Container(
          decoration: BoxDecoration(border: Border.all(color: c.line), borderRadius: BorderRadius.circular(16), color: c.surface),
          clipBehavior: Clip.antiAlias,
          child: Column(children: [
            for (var i = 0; i < msgs.length; i++) _Row(m: msgs[i], first: i == 0, tone: _tone(msgs[i]['status'] as String)),
          ]),
        ),
    ]);
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.m, required this.first, required this.tone});
  final J m;
  final bool first;
  final (String, String) tone;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.read<AppState>();
    final body = m['body'] as String;
    final bn = RegExp(r'[অ-হ]').hasMatch(body);
    final err = m['error'] as String?;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(border: first ? null : Border(top: BorderSide(color: c.line))),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(body, style: bn ? TypeX.bn(13.5, color: c.text) : TypeX.ui(13.5, color: c.text), maxLines: 3, overflow: TextOverflow.ellipsis),
          const SizedBox(height: 4),
          Text('${m['order'] ?? 'Test'} · ${m['event']} · to ${m['to']} · ${m['parts']} ${m['parts'] == 1 ? 'part' : 'parts'} (${m['encoding']}) · ${m['providerName']} · ${relative(m['createdAt'] as String?)}${m['by'] != null ? ' · by ${m['by']}' : ''}', style: TypeX.ui(11.5, color: c.text3)),
          if (err != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text(err, style: TypeX.ui(12, color: c.danger, h: 1.35))),
        ])),
        const SizedBox(width: 12),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Tag(tone.$2, tone: tone.$1, dot: true, small: true),
          if (m['canResend'] == true && s.can('orders.manage')) Padding(padding: const EdgeInsets.only(top: 8), child: DkButton('Send again', small: true, kind: BtnKind.ghost, onPressed: () async {
            final r = await s.resendSms(m['id'] as String);
            s.toast(r['error'] != null ? r['error'] as String : 'Sent again', error: r['error'] != null);
          })),
        ]),
      ]),
    );
  }
}
