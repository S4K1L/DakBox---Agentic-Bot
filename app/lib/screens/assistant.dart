import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../brand/icons.dart';
import 'package:provider/provider.dart';
import '../brand/theme.dart';
import '../core/api.dart';
import '../core/state.dart';
import '../core/format.dart';
import '../widgets/kit.dart';
import '../widgets/page.dart';
import 'ai_key_ui.dart';
import 'inbox.dart' show showSimulator;

class AssistantScreen extends StatefulWidget {
  const AssistantScreen({super.key});
  @override
  State<AssistantScreen> createState() => _AssistantScreenState();
}

class _AssistantScreenState extends State<AssistantScreen> {
  String tab = 'behavior';
  @override
  void initState() {
    super.initState();
    final st = context.read<AppState>();
    st.loadSettings();
    if (st.assistantTab != null) { tab = st.assistantTab!; st.assistantTab = null; }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final claude = s.settings?['engine'] != null && s.settings?['engine'] != 'offline';
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        PageHeader(
          title: 'Assistant',
          subtitle: Row(mainAxisSize: MainAxisSize.min, children: [
            Text('${s.settings?['agent']?['storeName'] ?? ''}. Control what the assistant may do, how it speaks, and what it knows.', style: TypeX.ui(13.5, color: c.text3)),
          ]),
        ),
        if (s.settings != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(24, 0, 24, 14),
            child: Builder(builder: (context) {
              final a = s.settings!['agent'] as J;
              final can = (a['can'] as Map).cast<String, dynamic>();
              final ordering = can['carts'] == true && can['checkout'] != false;
              return Row(children: [
                StatTile(value: claude ? '${s.settings!['engineLabel'] ?? 'AI'}' : 'Offline', label: claude ? '${s.settings!['model']}' : 'Rules engine, no AI key', icon: PhosphorIconsFill.sparkle, tone: claude ? 'ok' : 'warn', active: tab == 'engine', onTap: () => setState(() => tab = 'engine')),
                const SizedBox(width: 8),
                StatTile(value: ordering ? 'On' : 'Off', label: ordering ? 'Orders in chat, up to ${taka((a['maxOrder'] ?? 20000) as num)}' : 'Orders in chat', icon: PhosphorIconsRegular.shoppingBag, tone: ordering ? 'ok' : ''),
                const SizedBox(width: 8),
                StatTile(value: '${a['confidence']}%', label: 'Hands off below this confidence', icon: PhosphorIconsRegular.userSwitch),
                const SizedBox(width: 8),
                StatTile(value: {'match': 'Match', 'bn': 'বাংলা', 'en': 'English'}[a['replyLanguage']] ?? 'Match', label: 'Reply language', icon: PhosphorIconsRegular.translate),
              ]);
            }),
          ),
        UnderTabs(value: tab, onChanged: (v) => setState(() => tab = v), tabs: const [('behavior', 'Behavior', null), ('knowledge', 'Knowledge', null), ('engine', 'Engine and key', null), ('try', 'Try it', null)]),
        Expanded(
          child: s.settings == null
              ? Center(child: CircularProgressIndicator(color: c.primary, strokeWidth: 3))
              : switch (tab) {
                  'knowledge' => _Locked(locked: !s.can('settings.write'), what: 'edit the assistant’s knowledge', child: const _Knowledge()),
                  'engine' => const AiEngineTab(),
                  'try' => _Locked(locked: !s.can('simulate'), what: 'send test messages', child: const _TryIt()),
                  _ => _Locked(locked: !s.can('settings.write'), what: 'change the assistant’s behavior', child: const _Behavior()),
                },
        ),
      ]),
    );
  }
}

/// Shows the page read-only, with a note, when the signed-in role cannot change it.
class _Locked extends StatelessWidget {
  const _Locked({required this.locked, required this.what, required this.child});
  final bool locked;
  final String what;
  final Widget child;
  @override
  Widget build(BuildContext context) {
    if (!locked) return child;
    final c = context.c;
    return Column(children: [
      Container(
        margin: const EdgeInsets.fromLTRB(24, 16, 24, 0), padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: c.sunken, borderRadius: BorderRadius.circular(12)),
        child: Row(children: [Icon(PhosphorIconsFill.lockSimple, size: 17, color: c.text2), const SizedBox(width: 10), Expanded(child: Text('Your role cannot $what. You can look, but not change.', style: TypeX.ui(13, color: c.text2)))]),
      ),
      Expanded(child: IgnorePointer(child: Opacity(opacity: .6, child: child))),
    ]);
  }
}

class _Card extends StatelessWidget {
  const _Card({required this.title, required this.children, this.trailing, this.icon, this.subtitle});
  final String title;
  final List<Widget> children;
  final Widget? trailing;
  final IconData? icon;
  final String? subtitle;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(18), border: Border.all(color: c.line)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(padding: const EdgeInsets.fromLTRB(20, 16, 20, 14), child: Row(children: [
          if (icon != null) ...[Container(width: 34, height: 34, decoration: BoxDecoration(color: c.primarySoft, borderRadius: BorderRadius.circular(10)), child: Icon(icon, size: 17, color: c.primary)), const SizedBox(width: 12)],
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(title, style: TypeX.display(16, color: c.text)), if (subtitle != null) Padding(padding: const EdgeInsets.only(top: 2), child: Text(subtitle!, style: TypeX.ui(12.5, color: c.text3)))])),
          if (trailing != null) trailing!,
        ])),
        for (final w in children) Container(decoration: BoxDecoration(border: Border(top: BorderSide(color: c.line))), padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14), child: w),
      ]),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.title, required this.body, required this.trailing});
  final String title, body;
  final Widget trailing;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Row(children: [
      Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(title, style: TypeX.ui(14, w: FontWeight.w700, color: c.text)), const SizedBox(height: 2), Text(body, style: TypeX.ui(12.5, color: c.text3, h: 1.4))])),
      const SizedBox(width: 16),
      trailing,
    ]);
  }
}

class _Behavior extends StatelessWidget {
  const _Behavior();
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final a = s.settings!['agent'] as J;
    final can = Map<String, dynamic>.from(a['can'] as Map);
    void setCan(String k, bool v) { can[k] = v; s.saveSettings({'can': can}); }
    return Align(
      alignment: Alignment.topCenter,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 820),
        child: ListView(padding: const EdgeInsets.all(24), children: [
          _Card(title: 'About the store', icon: PhosphorIconsRegular.storefront, subtitle: 'Tell the assistant, in a few words, what you sell.', children: [const _About()]),
          _Card(title: 'What the assistant can do', icon: PhosphorIconsFill.sparkle, subtitle: 'Anything switched off here, the assistant will not do.', children: [
            _Row(title: 'Answer product questions', body: 'Uses live catalog data for price and stock.', trailing: DkSwitch(value: can['products'] == true, onChanged: (v) => setCan('products', v))),
            _Row(title: 'Build carts', body: 'The customer confirms every cart change. In Review mode a person approves it too.', trailing: DkSwitch(value: can['carts'] == true, onChanged: (v) => setCan('carts', v))),
            _Row(title: 'Take orders in chat', body: 'After the customer confirms a written summary, the assistant creates the order as Pending: staff still confirm cash on delivery by phone, and online payments are confirmed by the provider. In Review mode a person approves it first. Needs Build carts.', trailing: DkSwitch(value: can['checkout'] != false, onChanged: can['carts'] == true ? (v) => setCan('checkout', v) : null)),
            _Row(title: 'Largest order it may place', body: 'Bigger orders are handed to a person. Also limited to 20 items and 3 orders per customer per day.', trailing: Seg<String>(items: const [('5000', '৳5,000'), ('10000', '৳10,000'), ('20000', '৳20,000'), ('50000', '৳50,000')], value: '${a['maxOrder'] ?? 20000}', onChanged: (v) => s.saveSettings({'maxOrder': int.parse(v)}), small: true)),
            _Row(title: 'Share order status', body: 'Only after the customer is verified by phone.', trailing: DkSwitch(value: can['orders'] == true, onChanged: (v) => setCan('orders', v))),
            _Row(title: 'Start return requests', body: 'Every request goes to Approvals. The assistant never approves or promises a refund.', trailing: DkSwitch(value: can['returns'] == true, onChanged: (v) => setCan('returns', v))),
            _Row(title: 'Offer discount codes', body: 'The assistant can never grant discounts. Price matches go to Approvals for a person.', trailing: const Tag('Never', tone: '', small: true)),
          ]),
          _Card(title: 'Languages', icon: PhosphorIconsRegular.translate, subtitle: 'Bangla, Banglish and English.', children: [
            _Row(title: 'Reply language', body: 'The assistant answers in the language the customer writes in.', trailing: Seg<String>(items: const [('match', 'Match customer'), ('bn', 'বাংলা'), ('en', 'English')], value: a['replyLanguage'] as String, onChanged: (v) => s.saveSettings({'replyLanguage': v}), small: true)),
            _Row(title: 'Reply in Banglish', body: 'When a customer writes Bangla in English letters, the assistant answers the same way.', trailing: DkSwitch(value: a['banglish'] == true, onChanged: (v) => s.saveSettings({'banglish': v}))),
            _Row(title: 'Bangla digits', body: 'Show ১২৩ instead of 123 in Bangla replies.', trailing: DkSwitch(value: a['bnDigits'] == true, onChanged: (v) => s.saveSettings({'bnDigits': v}))),
            _Row(title: 'Show English translation to staff', body: 'A small line under each Bangla or Banglish message.', trailing: DkSwitch(value: a['showTranslation'] == true, onChanged: (v) => s.saveSettings({'showTranslation': v}))),
          ]),
          _Card(title: 'When to involve a person', icon: PhosphorIconsRegular.userSwitch, subtitle: 'The assistant hands over rather than guess.', children: [
            _Row(title: 'Handoff confidence', body: 'Below this, the assistant asks a person to step in.', trailing: SizedBox(width: 240, child: Row(children: [
              Expanded(child: SliderTheme(data: SliderTheme.of(context).copyWith(activeTrackColor: c.primary, inactiveTrackColor: c.sunken, thumbColor: c.primary, overlayColor: c.primary.withValues(alpha: .12), trackHeight: 5), child: Slider(min: 50, max: 95, divisions: 45, value: (a['confidence'] as num).toDouble(), onChanged: (v) => s.saveSettings({'confidence': v.round()})))),
              SizedBox(width: 44, child: Text('${a['confidence']}%', textAlign: TextAlign.right, style: TypeX.mono(13, w: FontWeight.w700, color: c.text))),
            ]))),
            _Row(title: 'Tone', body: 'Applies to the assistant’s own replies.', trailing: Seg<String>(items: const [('friendly', 'Friendly'), ('formal', 'Formal'), ('playful', 'Playful')], value: a['tone'] as String, onChanged: (v) => s.saveSettings({'tone': v}), small: true)),
            _Row(title: 'Always hand off', body: 'Refunds, complaints and legal topics.', trailing: const Tag('On', tone: 'ok', dot: true)),
          ]),
          _Card(title: 'Safety rails', icon: PhosphorIconsRegular.shieldCheck, subtitle: 'Built in. These cannot be switched off.', children: [
            for (final (t, b) in const [
              ('Facts come from your data', 'Prices, stock, orders and delivery are read from live tools, never guessed.'),
              ('Order details stay private', 'Shared only after the customer matches the phone number on the order.'),
              ('No money decisions', 'Refunds, returns and price matches always go to a person in Approvals.'),
              ('No PINs, OTPs or card numbers', 'Customers are told not to share them, and the assistant never asks.'),
              ('Orders need a confirmed summary', 'An order is placed only after the customer confirms the exact written summary.'),
            ]) Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Padding(padding: const EdgeInsets.only(top: 1), child: Icon(PhosphorIconsFill.checkCircle, size: 18, color: c.ok)),
              const SizedBox(width: 12),
              Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(t, style: TypeX.ui(13.5, w: FontWeight.w700, color: c.text)), const SizedBox(height: 2), Text(b, style: TypeX.ui(12.5, color: c.text3, h: 1.4))])),
            ]),
          ]),
        ]),
      ),
    );
  }
}

class _Knowledge extends StatelessWidget {
  const _Knowledge();
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final pol = (s.settings!['policies'] as List).cast<J>();
    return Align(
      alignment: Alignment.topCenter,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 820),
        child: ListView(padding: const EdgeInsets.all(24), children: [
          Container(
            padding: const EdgeInsets.all(14), margin: const EdgeInsets.only(bottom: 16),
            decoration: BoxDecoration(color: c.primarySoft, borderRadius: BorderRadius.circular(14), border: Border.all(color: c.primaryLine)),
            child: Row(children: [const AiMark(size: 26), const SizedBox(width: 12), Expanded(child: Text('The assistant reads these before answering any policy question and cites them to your team in Approvals. Edit one and it applies to the next message.', style: TypeX.ui(13, color: c.text2, h: 1.45)))]),
          ),
          for (final p in pol) _PolicyCard(key: ValueKey(p['key']), p: p),
        ]),
      ),
    );
  }
}

class _PolicyCard extends StatefulWidget {
  const _PolicyCard({super.key, required this.p});
  final J p;
  @override
  State<_PolicyCard> createState() => _PolicyCardState();
}

class _PolicyCardState extends State<_PolicyCard> {
  late final title = TextEditingController(text: widget.p['title'] as String);
  late final body = TextEditingController(text: widget.p['body'] as String);
  bool dirty = false;
  @override
  void dispose() { title.dispose(); body.dispose(); super.dispose(); }
  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    return Container(
      margin: const EdgeInsets.only(bottom: 14), padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(18), border: Border.all(color: dirty ? c.primary : c.line)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [Icon(PhosphorIconsFill.bookOpenText, size: 16, color: c.primary), const SizedBox(width: 8), Text((widget.p['key'] as String).toUpperCase(), style: TypeX.ui(11, w: FontWeight.w800, color: c.primary, ls: .9))]),
        const Gap(10),
        TextField(controller: title, onChanged: (_) => setState(() => dirty = true), style: TypeX.display(16, color: c.text), decoration: const InputDecoration(border: InputBorder.none, isDense: true, contentPadding: EdgeInsets.zero)),
        const Gap(8),
        DkField(controller: body, maxLines: 5),
        if (dirty) ...[const Gap(12), Row(children: [DkButton('Save policy', icon: PhosphorIconsBold.check, kind: BtnKind.primary, small: true, onPressed: () async { await s.savePolicy(widget.p['key'] as String, title.text.trim(), body.text.trim()); if (mounted) setState(() => dirty = false); }), const SizedBox(width: 8), DkButton('Discard', kind: BtnKind.ghost, small: true, onPressed: () => setState(() { title.text = widget.p['title'] as String; body.text = widget.p['body'] as String; dirty = false; }))])],
      ]),
    );
  }
}

class _TryIt extends StatelessWidget {
  const _TryIt();
  static const prompts = [
    ('ms', 'Do you have a navy water bottle?'),
    ('wa', 'আসসালামু আলাইকুম, তাঁবু আছে?'),
    ('ig', 'bhai Alpine jacket ta ache? M size'),
    ('web', 'How long does delivery to Khulna take?'),
    ('wa', 'আমার অর্ডার #১০৪২ কোথায়?'),
    ('ms', 'my bottle lid cracked, I want a refund'),
  ];
  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    final origin = Uri.base.hasAuthority ? Uri.base.origin : 'https://YOUR-DOMAIN';
    final slug = (s.me['business'] as Map?)?['slug'] as String?;
    final widgetPath = slug == null || slug == 'default' ? '/widget' : '/widget?b=$slug';        // each business has its own chat page; the default keeps the original address
    final embed = '<iframe src="$origin$widgetPath" style="position:fixed;right:20px;bottom:20px;width:380px;height:620px;border:0;border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,.25)"></iframe>';
    return Align(
      alignment: Alignment.topCenter,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 820),
        child: ListView(padding: const EdgeInsets.all(24), children: [
          _Card(title: 'Try a conversation', icon: PhosphorIconsRegular.chatCircleDots, subtitle: 'Send a test message as a customer.', children: [
            Text('Tap a message to send it as a customer on that channel. Watch it appear in the Inbox with the assistant’s tool activity.', style: TypeX.ui(13, color: c.text3, h: 1.45)),
            Wrap(spacing: 10, runSpacing: 10, children: [
              for (final (k, t) in prompts)
                Hover(
                  pressScale: .97,
                  onTap: () async {
                    final id = await s.simulate(channel: k, name: 'Playground ${channelName(k)}', text: t);
                    if (id != null) { s.setSection(Section.inbox); s.selectConversation(id); }
                  },
                  builder: (_, h, __) => AnimatedContainer(
                    duration: const Duration(milliseconds: 140), padding: const EdgeInsets.fromLTRB(8, 8, 14, 8),
                    decoration: BoxDecoration(color: h ? c.primarySoft : c.surface, borderRadius: BorderRadius.circular(99), border: Border.all(color: h ? c.primary : c.line)),
                    child: Row(mainAxisSize: MainAxisSize.min, children: [ChannelIcon(kind: k, size: 24, circle: true), const SizedBox(width: 9), Text(t, style: (RegExp(r'[ঀ-৿]').hasMatch(t) ? TypeX.bn(13, w: FontWeight.w600, color: c.text) : TypeX.ui(13, w: FontWeight.w600, color: c.text)))]),
                  ),
                ),
            ]),
            Align(alignment: Alignment.centerLeft, child: DkButton('Write your own', icon: PhosphorIconsRegular.pencilSimple, onPressed: () => showSimulator(context))),
          ]),
          _Card(title: 'Website chat widget', icon: PhosphorIconsRegular.globeHemisphereEast, children: [
            _Row(title: 'Embed on your site', body: 'The widget is served by this backend at $widgetPath. It speaks Bangla and English and always offers “Talk to a person”.', trailing: DkButton('Copy code', icon: PhosphorIconsRegular.copy, small: true, onPressed: () { Clipboard.setData(ClipboardData(text: embed)); s.toast('Embed code copied'); })),
            Container(width: double.infinity, padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: c.sunken, borderRadius: BorderRadius.circular(12)), child: SelectableText(embed, style: TypeX.mono(11.5, color: c.text2))),
          ]),
        ]),
      ),
    );
  }
}


/// One line about what the store sells. The assistant reads it first, so it answers like a shop of that kind from the first message.
class _About extends StatefulWidget {
  const _About();
  @override
  State<_About> createState() => _AboutState();
}

class _AboutState extends State<_About> {
  late final ctl = TextEditingController(text: (context.read<AppState>().settings?['agent']?['storeAbout'] ?? '') as String);
  bool saved = false;

  @override
  void dispose() { ctl.dispose(); super.dispose(); }

  Future<void> _save() async {
    await context.read<AppState>().saveSettings({'storeAbout': ctl.text.trim()});
    if (mounted) setState(() => saved = true);
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
        Expanded(child: DkField(controller: ctl, hint: 'For example: handloom sarees, panjabis and women’s clothing', onSubmitted: (_) => _save())),
        const SizedBox(width: 10),
        DkButton('Save', kind: BtnKind.primary, onPressed: _save),
      ]),
      Padding(padding: const EdgeInsets.only(top: 8), child: Text(saved ? 'Saved. The assistant uses it from the next message.' : 'Optional. If you leave it empty, the assistant looks at your product list instead.', style: TypeX.ui(12, color: saved ? c.ok : c.text3))),
    ]);
  }
}
