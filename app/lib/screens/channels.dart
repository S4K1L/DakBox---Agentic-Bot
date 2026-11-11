import 'package:flutter/material.dart';
import 'guide_ui.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../brand/icons.dart';
import '../brand/theme.dart';
import '../core/api.dart';
import '../core/format.dart';
import '../core/state.dart';
import '../widgets/kit.dart';
import 'inbox.dart' show showSimulator;

String kindTitle(String k) => switch (k) { 'wa' => 'WhatsApp Business', 'ms' => 'Facebook Messenger', 'ig' => 'Instagram', _ => 'Web chat' };

Future<void> _dialog(BuildContext context, Widget d) => showDialog<void>(context: context, barrierColor: Colors.black.withValues(alpha: .45), builder: (_) => d);

class ChannelsTab extends StatelessWidget {
  const ChannelsTab({super.key});
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final canWrite = s.can('connections.write');
    return LayoutBuilder(builder: (context, box) {
      final cols = (box.maxWidth / 380).floor().clamp(1, 3);
      final cw = (box.maxWidth - 48 - 16 * (cols - 1)) / cols;
      return ListView(padding: const EdgeInsets.all(24), children: [
        const HowToConnect(title: 'How to connect WhatsApp, Messenger and Instagram', where: 'Meta for Developers (developers.facebook.com) and this page', steps: metaGuide),
        const HowToConnect(title: 'How the website chat works', steps: webChatGuide),
        if (canWrite) ...[const _MetaAppCard(), const Gap(18)],
        Wrap(spacing: 16, runSpacing: 16, children: [
          for (var i = 0; i < s.channels.length; i++) SizedBox(width: cw, child: Reveal(delay: i * 50, child: _ChannelCard(key: ValueKey(s.channels[i]['id']), a: s.channels[i]))),
          if (canWrite) SizedBox(width: cw, child: Reveal(delay: s.channels.length * 50, child: const _ConnectCard())),
        ]),
        if (canWrite) ...[const Gap(22), const _Activity()],
      ]);
    });
  }
}

// ---------------------------------------------------------------- the Meta app
class _MetaAppCard extends StatelessWidget {
  const _MetaAppCard();
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final m = s.metaApp;
    final https = ((m['publicUrl'] as String?) ?? '').startsWith('https://');
    final ready = m['appSecretSet'] == true && m['verifyTokenSet'] == true && https;
    Widget check(String label, bool ok) => Padding(
          padding: const EdgeInsets.only(right: 18, top: 6),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(ok ? PhosphorIconsFill.checkCircle : PhosphorIconsRegular.circle, size: 17, color: ok ? c.ok : c.text3),
            const SizedBox(width: 7),
            Text(label, style: TypeX.ui(13, w: FontWeight.w600, color: ok ? c.text : c.text2)),
          ]),
        );
    final url = (m['webhookUrl'] as String?) ?? '';
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(20), border: Border.all(color: ready ? c.line : c.warn.withValues(alpha: .5)), boxShadow: c.shadow),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Container(width: 40, height: 40, decoration: BoxDecoration(gradient: c.brand, borderRadius: BorderRadius.circular(12)), child: const Icon(PhosphorIconsFill.plugsConnected, color: Colors.white, size: 21)),
          const SizedBox(width: 14),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Meta app and webhook', style: TypeX.display(17, color: c.text)),
            Text('One Meta app can serve WhatsApp, Messenger and Instagram. Its secret signs every message Meta sends you.', style: TypeX.ui(12.5, color: c.text3, h: 1.4)),
          ])),
          Tag(ready ? 'Ready' : 'Setup needed', tone: ready ? 'ok' : 'warn', dot: true),
        ]),
        const Gap(8),
        Wrap(children: [check('App ID', ((m['appId'] as String?) ?? '').isNotEmpty), check('App secret', m['appSecretSet'] == true), check('Verify token', m['verifyTokenSet'] == true), check('Public https URL', https)]),
        const Gap(14),
        Hover(
          onTap: () { Clipboard.setData(ClipboardData(text: url)); s.toast('Webhook URL copied'); },
          builder: (_, h, __) => Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
            decoration: BoxDecoration(color: c.sunken, borderRadius: BorderRadius.circular(12), border: Border.all(color: h ? c.primary : c.line)),
            child: Row(children: [Text('Callback URL', style: TypeX.ui(12, w: FontWeight.w700, color: c.text3)), const SizedBox(width: 12), Expanded(child: Text(url, style: TypeX.mono(12.5, color: c.text), overflow: TextOverflow.ellipsis)), Icon(PhosphorIconsRegular.copy, size: 16, color: c.text3)]),
          ),
        ),
        const Gap(14),
        DkButton(ready ? 'Edit Meta app' : 'Set up Meta app', icon: PhosphorIconsRegular.gearSix, kind: ready ? BtnKind.secondary : BtnKind.primary, small: true, onPressed: () => _dialog(context, const _MetaAppDialog())),
      ]),
    );
  }
}

class _MetaAppDialog extends StatefulWidget {
  const _MetaAppDialog();
  @override
  State<_MetaAppDialog> createState() => _MetaAppDialogState();
}

class _MetaAppDialogState extends State<_MetaAppDialog> {
  late final TextEditingController appId, secret, url, token;
  String? error;
  bool busy = false;
  @override
  void initState() {
    super.initState();
    final m = context.read<AppState>().metaApp;
    appId = TextEditingController(text: (m['appId'] as String?) ?? '');
    secret = TextEditingController();
    url = TextEditingController(text: (m['publicUrl'] as String?) ?? '');
    token = TextEditingController(text: (m['verifyToken'] as String?) ?? '');
  }

  @override
  void dispose() { appId.dispose(); secret.dispose(); url.dispose(); token.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    final hint = s.metaApp['appSecretHint'] as String?;
    return _Shell(title: 'Meta app and webhook', children: [
      Text('In the Meta app dashboard, open the webhook settings for each product. Paste the Callback URL and Verify token from here, subscribe to the messages field, and use the App secret below so Dakbox can verify every request.', style: TypeX.ui(13, color: c.text3, h: 1.5)),
      const Gap(16),
      if (error != null) _Err(error!),
      DkField(controller: appId, label: 'App ID (optional, lets Dakbox read token expiry)', mono: true),
      const Gap(12),
      DkField(controller: secret, label: hint == null ? 'App secret' : 'App secret (saved $hint, leave empty to keep it)', obscure: true),
      const Gap(12),
      DkField(controller: url, label: 'Public https URL of this server', hint: 'https://inbox.yourshop.com'),
      const Gap(12),
      Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Expanded(child: DkField(controller: token, label: 'Verify token', mono: true)),
        const SizedBox(width: 8),
        DkButton('Generate', small: true, onPressed: () async { final t = await s.newVerifyToken(); if (t != null) setState(() => token.text = t); }),
        const SizedBox(width: 6),
        DkIconButton(PhosphorIconsRegular.copy, onPressed: () { Clipboard.setData(ClipboardData(text: token.text)); s.toast('Copied'); }),
      ]),
      const Gap(22),
      Row(mainAxisAlignment: MainAxisAlignment.end, children: [
        DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
        const Gap(8),
        DkButton(busy ? 'Saving…' : 'Save', icon: PhosphorIconsBold.check, kind: BtnKind.primary, onPressed: busy ? null : () async {
          setState(() { busy = true; error = null; });
          final e = await s.saveMetaApp({'appId': appId.text.trim(), if (secret.text.trim().isNotEmpty) 'appSecret': secret.text.trim(), 'publicUrl': url.text.trim(), if (token.text.trim().isNotEmpty) 'verifyToken': token.text.trim()});
          if (!context.mounted) return;
          if (e == null) { Navigator.pop(context); s.toast('Meta app saved'); } else { setState(() { busy = false; error = e; }); }
        }),
      ]),
    ]);
  }
}

// ---------------------------------------------------------------- channel cards
class _ChannelCard extends StatefulWidget {
  const _ChannelCard({super.key, required this.a});
  final J a;
  @override
  State<_ChannelCard> createState() => _ChannelCardState();
}

class _ChannelCardState extends State<_ChannelCard> {
  String? busy;

  Future<void> _run(String label, Future<J> Function() f, {String? okText}) async {
    final s = context.read<AppState>();
    setState(() => busy = label);
    final r = await f();
    if (!mounted) return;
    setState(() => busy = null);
    final err = r['error'] as String?;
    final chk = (r['check'] ?? r['result'] ?? r['subscription']) as J?;
    if (err != null) { s.toast(err, error: true); } else if (chk != null && chk['ok'] == false) { s.toast(chk['message'] as String, error: true); } else { s.toast(okText ?? (chk?['message'] as String?) ?? 'Done'); }
  }

  @override
  Widget build(BuildContext context) {
    final a = widget.a;
    final c = context.c;
    final s = context.read<AppState>();
    final canWrite = s.can('connections.write');
    final st = a['status'] as String;
    final demo = a['demo'] == true;
    final kind = a['kind'] as String;
    final tone = st == 'ok' ? 'ok' : (st == 'warn' ? 'warn' : (st == 'off' ? '' : 'danger'));
    final label = st == 'ok' ? 'Healthy' : st == 'warn' ? 'Needs review' : st == 'off' ? 'Disconnected' : 'Not working';
    final id = a['id'] as String;
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(20), boxShadow: c.shadow, border: Border.all(color: st == 'ok' || st == 'off' ? c.line : (st == 'warn' ? c.warn.withValues(alpha: .5) : c.danger.withValues(alpha: .5)))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          ChannelIcon(kind: kind, size: 44),
          const SizedBox(width: 14),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(kind == 'ms' ? 'Facebook Messenger' : (a['name'] as String), style: TypeX.ui(15, w: FontWeight.w800, color: c.text), maxLines: 1, overflow: TextOverflow.ellipsis),
            Text(a['handle'] as String, style: TypeX.ui(12.5, color: c.text3), maxLines: 1, overflow: TextOverflow.ellipsis),
          ])),
          Tag(label, tone: tone, dot: true, small: true),
        ]),
        const Gap(12),
        Wrap(spacing: 6, children: [Tag(demo ? 'Demo' : 'Live', tone: demo ? 'ai' : 'accent', small: true), if (a['via'] != null) Tag(a['via'] == 'page' ? 'via Facebook Page' : 'via Instagram Login', small: true)]),
        const Gap(8),
        for (final h in (a['health'] as List).cast<List>())
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(h[0] as String, style: TypeX.ui(12.5, color: c.text3)), const SizedBox(width: 12),
              Expanded(child: Text(h[1] as String, textAlign: TextAlign.right, style: TypeX.ui(12.5, w: FontWeight.w700, color: h[2] == 'ok' ? c.ok : (h[2] == 'warn' ? c.warn : (h[2] == 'danger' ? c.danger : c.text))))),
            ]),
          ),
        Padding(padding: const EdgeInsets.symmetric(vertical: 4), child: Row(children: [Text('Conversations', style: TypeX.ui(12.5, color: c.text3)), const Spacer(), Text('${a['conversations']}', style: TypeX.ui(12.5, w: FontWeight.w700, color: c.text))])),
        if (a['alert'] != null) Container(margin: const EdgeInsets.only(top: 10), padding: const EdgeInsets.all(10), decoration: BoxDecoration(color: st == 'danger' ? c.dangerSoft : c.warnSoft, borderRadius: BorderRadius.circular(10)), child: Text(a['alert'] as String, style: TypeX.ui(12.5, color: c.text2, h: 1.45))),
        const Gap(14),
        if (demo)
          Wrap(spacing: 8, runSpacing: 8, children: [
            if (s.can('simulate')) DkButton('Send test message', icon: PhosphorIconsRegular.paperPlaneTilt, small: true, onPressed: st == 'off' ? null : () => showSimulator(context)),
            if (canWrite && kind != 'web') DkButton('Connect a real account', kind: BtnKind.soft, small: true, onPressed: () => _dialog(context, _ConnectDialog(kind: kind))),
          ])
        else if (canWrite)
          Wrap(spacing: 8, runSpacing: 8, children: [
            if (st != 'off') DkButton(busy == 'check' ? 'Checking…' : 'Check now', icon: PhosphorIconsRegular.heartbeat, small: true, onPressed: busy != null ? null : () => _run('check', () => s.channelAction(id, 'check'))),
            if (st != 'off') DkButton(busy == 'sub' ? 'Subscribing…' : 'Subscribe webhooks', small: true, onPressed: busy != null ? null : () => _run('sub', () => s.channelAction(id, 'subscribe'))),
            if (st != 'off') DkButton('Replace token', small: true, kind: st == 'danger' ? BtnKind.primary : BtnKind.secondary, onPressed: () => _dialog(context, _TokenDialog(a: a))),
            if (st != 'off') DkButton('Disconnect', small: true, kind: BtnKind.danger, onPressed: () => _dialog(context, _DisconnectDialog(a: a))),
          ]),
      ]),
    );
  }
}

class _ConnectCard extends StatelessWidget {
  const _ConnectCard();
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Hover(
      onTap: () => _dialog(context, const _ConnectDialog()),
      builder: (_, h, __) => AnimatedContainer(
        duration: const Duration(milliseconds: 150), height: 250,
        decoration: BoxDecoration(color: h ? c.primarySoft : c.primarySoft.withValues(alpha: 0), borderRadius: BorderRadius.circular(20), border: Border.all(color: h ? c.primary : c.line2, width: 1.5)),
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          Container(width: 48, height: 48, decoration: BoxDecoration(color: c.primarySoft, shape: BoxShape.circle), child: Icon(PhosphorIconsBold.plus, color: c.primary)),
          const Gap(12),
          Text('Connect a real account', style: TypeX.ui(15, w: FontWeight.w800, color: c.text)),
          const Gap(4),
          Text('WhatsApp, Facebook Page or Instagram', style: TypeX.ui(12.5, color: c.text3)),
        ]),
      ),
    );
  }
}

// ---------------------------------------------------------------- dialogs
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
        constraints: BoxConstraints(maxWidth: width, maxHeight: 760),
        child: Panel(
          radius: 24,
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [Expanded(child: Text(title, style: TypeX.display(21, color: c.text))), DkIconButton(PhosphorIconsBold.x, size: 32, onPressed: () => Navigator.pop(context))]),
              const Gap(14),
              ...children,
            ]),
          ),
        ),
      ),
    );
  }
}

class _Err extends StatelessWidget {
  const _Err(this.text);
  final String text;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      margin: const EdgeInsets.only(bottom: 14), padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: c.dangerSoft, borderRadius: BorderRadius.circular(12), border: Border.all(color: c.danger.withValues(alpha: .25))),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Icon(PhosphorIconsFill.warningCircle, size: 18, color: c.danger), const SizedBox(width: 10), Expanded(child: Text(text, style: TypeX.ui(13, w: FontWeight.w600, color: c.text)))]),
    );
  }
}

class _ConnectDialog extends StatefulWidget {
  const _ConnectDialog({this.kind});
  final String? kind;
  @override
  State<_ConnectDialog> createState() => _ConnectDialogState();
}

class _ConnectDialogState extends State<_ConnectDialog> {
  String? kind;
  String via = 'instagram_login';
  final id = TextEditingController();
  final waba = TextEditingController();
  final token = TextEditingController();
  final name = TextEditingController();
  String? error;
  bool busy = false;
  J? done;

  @override
  void initState() { super.initState(); kind = widget.kind; }
  @override
  void dispose() { id.dispose(); waba.dispose(); token.dispose(); name.dispose(); super.dispose(); }

  (String, String, String) get labels => switch (kind) {
        'wa' => ('Phone number ID', 'Meta app dashboard, WhatsApp, API setup. This is the ID of the number, not the number itself.', 'WhatsApp access token'),
        'ms' => ('Facebook Page ID', 'Your Page, About, Page transparency. Or the Page ID shown in Messenger settings of the Meta app.', 'Page access token'),
        _ => via == 'page' ? ('Facebook Page ID', 'The Facebook Page that the Instagram professional account is linked to.', 'Page access token') : ('Instagram account ID', 'Shown in Instagram API setup with Instagram login.', 'Instagram access token'),
      };

  String get tokenHelp => switch (kind) {
        'wa' => 'Use a System User token (it does not expire after 24 hours like the test token). Needs the whatsapp_business_messaging permission.',
        'ms' => 'Generate a Page access token for this Page. Needs pages_messaging (and pages_manage_metadata to subscribe webhooks).',
        _ => via == 'page' ? 'A Page access token with instagram_manage_messages.' : 'Needs instagram_business_basic and instagram_business_manage_messages.',
      };

  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    if (done != null) return _success(context, done!);
    if (kind == null) {
      return _Shell(title: 'Connect a real account', children: [
        Text('Choose what to connect. Dakbox checks the token with Meta before saving anything, and stores it encrypted. It is never shown again.', style: TypeX.ui(13, color: c.text3, h: 1.5)),
        const Gap(16),
        for (final k in ['wa', 'ms', 'ig'])
          Hover(
            onTap: () => setState(() => kind = k),
            builder: (_, h, __) => Container(
              margin: const EdgeInsets.only(bottom: 10), padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(color: h ? c.primarySoft : c.surface, borderRadius: BorderRadius.circular(16), border: Border.all(color: h ? c.primary : c.line)),
              child: Row(children: [ChannelIcon(kind: k, size: 40), const SizedBox(width: 14), Expanded(child: Text(kindTitle(k), style: TypeX.ui(15, w: FontWeight.w800, color: c.text))), Icon(PhosphorIconsBold.arrowRight, size: 16, color: c.text3)]),
            ),
          ),
      ]);
    }
    final (idLabel, idHelp, tokLabel) = labels;
    return _Shell(title: 'Connect ${kindTitle(kind!)}', children: [
      const HowToConnect(steps: metaGuide, where: 'Meta for Developers'),
      Row(children: [ChannelIcon(kind: kind!, size: 28), const SizedBox(width: 10), Expanded(child: Text('Values come from the Meta app dashboard.', style: TypeX.ui(13, color: c.text3)))]),
      const Gap(16),
      if (error != null) _Err(error!),
      if (kind == 'ig') ...[
        Text('How is this Instagram account connected?', style: TypeX.ui(12.5, w: FontWeight.w700, color: c.text2)),
        const Gap(6),
        Seg<String>(items: const [('instagram_login', 'Instagram Login'), ('page', 'Facebook Page')], value: via, onChanged: (v) => setState(() => via = v), small: true),
        const Gap(14),
      ],
      DkField(controller: id, label: idLabel, mono: true, hint: 'digits only'),
      Padding(padding: const EdgeInsets.only(top: 6), child: Text(idHelp, style: TypeX.ui(12, color: c.text3, h: 1.4))),
      if (kind == 'wa') ...[
        const Gap(12),
        DkField(controller: waba, label: 'WhatsApp Business Account ID', mono: true, hint: 'digits only'),
        Padding(padding: const EdgeInsets.only(top: 6), child: Text('Used to list your approved message templates and to subscribe webhooks.', style: TypeX.ui(12, color: c.text3, h: 1.4))),
      ],
      const Gap(12),
      DkField(controller: token, label: tokLabel, obscure: true),
      Padding(padding: const EdgeInsets.only(top: 6), child: Text(tokenHelp, style: TypeX.ui(12, color: c.text3, h: 1.4))),
      const Gap(12),
      DkField(controller: name, label: 'Name for your team (optional)', hint: kindTitle(kind!)),
      const Gap(22),
      Row(mainAxisAlignment: MainAxisAlignment.end, children: [
        if (widget.kind == null) DkButton('Back', kind: BtnKind.ghost, onPressed: () => setState(() { kind = null; error = null; })),
        const Gap(8),
        DkButton(busy ? 'Checking with Meta…' : 'Verify and connect', icon: PhosphorIconsBold.plugsConnected, kind: BtnKind.primary, onPressed: busy ? null : () async {
          if (id.text.trim().isEmpty || token.text.trim().length < 10) { setState(() => error = 'Enter the ID and the access token.'); return; }
          setState(() { busy = true; error = null; });
          final r = await s.connectChannel({'kind': kind, 'externalId': id.text.trim(), 'accessToken': token.text.trim(), if (name.text.trim().isNotEmpty) 'name': name.text.trim(), if (kind == 'wa') 'wabaId': waba.text.trim(), if (kind == 'ig') 'via': via});
          if (!mounted) return;
          token.clear();
          if (r['error'] != null) { setState(() { busy = false; error = r['error'] as String; }); } else { setState(() { busy = false; done = r; }); }
        }),
      ]),
    ]);
  }

  Widget _success(BuildContext context, J r) {
    final c = context.c;
    final ch = r['channel'] as J;
    final sub = r['subscription'] as J?;
    final subOk = sub?['ok'] == true;
    Widget row(bool ok, String t, String body) => Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(ok ? PhosphorIconsFill.checkCircle : PhosphorIconsFill.warningCircle, size: 20, color: ok ? c.ok : c.warn), const SizedBox(width: 10),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(t, style: TypeX.ui(14, w: FontWeight.w800, color: c.text)), const SizedBox(height: 2), Text(body, style: TypeX.ui(12.5, color: c.text3, h: 1.45))])),
          ]),
        );
    return _Shell(title: 'Connected', children: [
      Row(children: [ChannelIcon(kind: ch['kind'] as String, size: 44), const SizedBox(width: 14), Expanded(child: Text((ch['verifiedName'] ?? ch['handle']) as String, style: TypeX.display(19, color: c.text))), const Tag('Live', tone: 'ok', dot: true)]),
      const Gap(18),
      row(true, 'Token accepted by Meta', 'Saved encrypted. Ending ${ch['tokenHint'] ?? ''}.'),
      row(subOk, subOk ? 'Webhook subscription requested' : 'Webhook not subscribed yet', subOk ? 'Meta now sends this account’s messages to your webhook.' : (sub?['message'] as String? ?? 'Subscribe from the channel card.')),
      row(ch['lastWebhookAt'] != null, 'Send a test message', 'Message this account from another phone or profile. It should appear in the Inbox within seconds. If nothing arrives, open Recent webhook activity below the channels.'),
      const Gap(8),
      Align(alignment: Alignment.centerRight, child: DkButton('Done', kind: BtnKind.primary, onPressed: () => Navigator.pop(context))),
    ]);
  }
}

class _TokenDialog extends StatefulWidget {
  const _TokenDialog({required this.a});
  final J a;
  @override
  State<_TokenDialog> createState() => _TokenDialogState();
}

class _TokenDialogState extends State<_TokenDialog> {
  final token = TextEditingController();
  final waba = TextEditingController();
  String? error;
  bool busy = false;
  @override
  void dispose() { token.dispose(); waba.dispose(); super.dispose(); }
  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    final a = widget.a;
    return _Shell(title: 'Replace access token', width: 480, children: [
      Text('${a['handle']}. The new token is checked with Meta first; the old one is kept if the check fails. Current token ends ${a['tokenHint'] ?? ''}.', style: TypeX.ui(13, color: c.text3, h: 1.5)),
      const Gap(14),
      if (error != null) _Err(error!),
      DkField(controller: token, label: 'New access token', obscure: true),
      if (a['kind'] == 'wa' && a['wabaId'] == null) ...[const Gap(12), DkField(controller: waba, label: 'WhatsApp Business Account ID', mono: true)],
      const Gap(20),
      Row(mainAxisAlignment: MainAxisAlignment.end, children: [
        DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
        const Gap(8),
        DkButton(busy ? 'Checking…' : 'Replace token', kind: BtnKind.primary, onPressed: busy ? null : () async {
          if (token.text.trim().length < 10) { setState(() => error = 'Paste the new access token.'); return; }
          setState(() { busy = true; error = null; });
          final r = await s.updateChannel(a['id'] as String, {'accessToken': token.text.trim(), if (waba.text.trim().isNotEmpty) 'wabaId': waba.text.trim()});
          if (!mounted) return;
          token.clear();
          if (r['error'] != null) { setState(() { busy = false; error = r['error'] as String; }); } else { Navigator.pop(context); s.toast('Token replaced and verified'); }
        }),
      ]),
    ]);
  }
}

class _DisconnectDialog extends StatelessWidget {
  const _DisconnectDialog({required this.a});
  final J a;
  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    return _Shell(title: 'Disconnect ${a['handle']}?', width: 460, children: [
      Text('Dakbox deletes the saved token and stops sending and receiving for this account. Conversations stay. You can connect it again later with a token. This does not remove the app from your Meta account.', style: TypeX.ui(13, color: c.text2, h: 1.5)),
      const Gap(22),
      Row(mainAxisAlignment: MainAxisAlignment.end, children: [
        DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
        const Gap(8),
        DkButton('Disconnect', kind: BtnKind.danger, onPressed: () async { Navigator.pop(context); await s.disconnectChannel(a['id'] as String); }),
      ]),
    ]);
  }
}

// ---------------------------------------------------------------- troubleshooting
class _Activity extends StatelessWidget {
  const _Activity();
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final rows = s.webhookLog.take(8).toList();
    (String, String, IconData) look(J r) => switch (r['outcome']) {
          'ok' => ('Message received', 'ok', PhosphorIconsFill.checkCircle),
          'duplicate' => ('Duplicate delivery ignored', '', PhosphorIconsRegular.copy),
          'no_channel' => ('Message for an account that is not connected here (${r['account_id']})', 'warn', PhosphorIconsFill.warningCircle),
          'bad_signature' => ('Rejected: the signature did not match your app secret', 'danger', PhosphorIconsFill.shieldWarning),
          'error' => ('Could not be processed (${r['detail']})', 'danger', PhosphorIconsFill.warningCircle),
          _ => ('Received, nothing to do', '', PhosphorIconsRegular.minusCircle),
        };
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(18), border: Border.all(color: c.line)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Recent webhook activity', style: TypeX.display(16, color: c.text)),
        const Gap(2),
        Text('Every request Meta sends to your webhook shows up here. If this stays empty after you message the account, Meta is not reaching your server.', style: TypeX.ui(12.5, color: c.text3, h: 1.45)),
        const Gap(12),
        if (rows.isEmpty) Text('Nothing received yet.', style: TypeX.ui(13, color: c.text3)),
        for (final r in rows)
          Builder(builder: (_) {
            final (text, tone, icon) = look(r);
            final col = tone == 'ok' ? c.ok : tone == 'warn' ? c.warn : tone == 'danger' ? c.danger : c.text3;
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 5),
              child: Row(children: [
                Icon(icon, size: 16, color: col), const SizedBox(width: 10),
                if (r['kind'] != null && (r['kind'] == 'wa' || r['kind'] == 'ms' || r['kind'] == 'ig')) ...[ChannelIcon(kind: r['kind'] as String, size: 18), const SizedBox(width: 8)],
                Expanded(child: Text(text, style: TypeX.ui(12.5, w: FontWeight.w600, color: c.text2))),
                Text(relative(r['at'] as String?), style: TypeX.ui(11.5, color: c.text3)),
              ]),
            );
          }),
      ]),
    );
  }
}
