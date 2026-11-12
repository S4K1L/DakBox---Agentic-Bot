import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../brand/icons.dart';
import '../brand/theme.dart';
import '../core/state.dart';
import '../widgets/kit.dart';
import '../widgets/page.dart';
import 'catalog_ui.dart';

/// The guide a new business sees: what you sell, products, a channel, the AI, a test message. Each step's state comes from the server's real data;
/// only "skip" and "hide this guide" are remembered.
class SetupScreen extends StatefulWidget {
  const SetupScreen({super.key});
  @override
  State<SetupScreen> createState() => _SetupScreenState();
}

class _SetupScreenState extends State<SetupScreen> {
  final about = TextEditingController();
  bool busy = false;
  bool filled = false;

  @override
  void initState() {
    super.initState();
    final s = context.read<AppState>();
    s.loadOnboarding();
    s.loadSettings().then((_) {
      if (!mounted || filled) return;
      filled = true;
      setState(() => about.text = ((s.settings?['agent'] as Map?)?['storeAbout'] as String?) ?? '');
    });
  }

  @override
  void dispose() { about.dispose(); super.dispose(); }

  Future<void> _saveAbout() async {
    final s = context.read<AppState>();
    if (s.settings == null) return;
    setState(() => busy = true);
    await s.saveSettings({'storeAbout': about.text.trim()});
    await s.loadOnboarding();
    if (mounted) setState(() => busy = false);
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final g = s.onboarding;
    if (g == null) return Panel(child: Center(child: CircularProgressIndicator(color: c.primary, strokeWidth: 3)));
    final steps = {for (final x in (g['steps'] as List).cast<Map>()) x['id'] as String: x};
    bool done(String id) => steps[id]?['done'] == true;
    bool skipped(String id) => steps[id]?['skipped'] == true;
    final n = g['done'] as int, total = g['total'] as int;
    final first = ['about', 'products', 'channel', 'ai', 'test'].firstWhere((id) => !done(id), orElse: () => '');

    Widget step(int i, String id, String title, String body, List<Widget> actions, {Widget? extra}) {
      final isDone = done(id);
      final current = id == first;
      return Reveal(
        delay: i * 50,
        child: Container(
          margin: const EdgeInsets.only(bottom: 12), padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(18), border: Border.all(color: current ? c.primary : c.line, width: current ? 1.6 : 1), boxShadow: current ? c.shadow : null),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(
              width: 32, height: 32, alignment: Alignment.center,
              decoration: BoxDecoration(color: isDone ? c.okSoft : (current ? c.primarySoft : c.sunken), shape: BoxShape.circle),
              child: isDone ? Icon(PhosphorIconsBold.check, size: 16, color: c.ok) : Text('${i + 1}', style: TypeX.ui(14, w: FontWeight.w800, color: current ? c.primary : c.text3)),
            ),
            const SizedBox(width: 14),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Flexible(child: Text(title, style: TypeX.ui(15, w: FontWeight.w800, color: c.text))),
                if (skipped(id)) ...[const SizedBox(width: 8), const Tag('Skipped for now', small: true)] else if (isDone) ...[const SizedBox(width: 8), const Tag('Done', tone: 'ok', small: true)],
              ]),
              const SizedBox(height: 4),
              Text(body, style: TypeX.ui(13, color: c.text3, h: 1.45)),
              if (extra != null) ...[const SizedBox(height: 12), extra],
              if (actions.isNotEmpty) ...[const SizedBox(height: 12), Wrap(spacing: 8, runSpacing: 8, children: actions)],
            ])),
          ]),
        ),
      );
    }

    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        PageHeader(
          title: 'Get started',
          subtitle: Text('${s.me['business']?['name'] ?? 'Your business'} · $n of $total steps done', style: TypeX.ui(13.5, color: c.text3)),
          actions: [DkButton('Hide this guide', kind: BtnKind.ghost, onPressed: () => s.dismissSetup())],
        ),
        Expanded(
          child: Align(
            alignment: Alignment.topCenter,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 820),
              child: ListView(padding: const EdgeInsets.fromLTRB(24, 4, 24, 28), children: [
                ClipRRect(borderRadius: BorderRadius.circular(5), child: LinearProgressIndicator(value: n / total, minHeight: 7, backgroundColor: c.line, color: c.primary)),
                const SizedBox(height: 16),
                if (g['complete'] == true)
                  Container(
                    margin: const EdgeInsets.only(bottom: 14), padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(color: c.okSoft, borderRadius: BorderRadius.circular(14)),
                    child: Row(children: [
                      Icon(PhosphorIconsFill.checkCircle, color: c.ok, size: 20),
                      const SizedBox(width: 10),
                      Expanded(child: Text('Everything is set up. Customers can message you and the assistant answers.', style: TypeX.ui(13.5, w: FontWeight.w700, color: c.text))),
                      DkButton('Hide this guide', small: true, onPressed: () => s.dismissSetup()),
                    ]),
                  ),
                step(0, 'about', 'Tell the assistant what you sell', 'One line is enough, for example “handloom sarees, panjabis and women’s clothing”. It uses this when a customer asks about something you do not stock.', const [],
                    extra: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Expanded(child: DkField(controller: about, hint: 'For example: handloom sarees, panjabis and women’s clothing', onSubmitted: (_) => busy ? null : _saveAbout())),
                      const SizedBox(width: 8),
                      DkButton(busy ? 'Saving…' : 'Save', kind: BtnKind.primary, onPressed: busy ? null : _saveAbout),
                    ])),
                step(1, 'products', 'Add your products', 'The assistant answers prices and stock from this list. Paste your website address and Dakbox reads the products from it, or add them by hand.', [
                  DkButton('Import from my website', icon: PhosphorIconsRegular.globeHemisphereEast, kind: BtnKind.primary, onPressed: () => showImportSite(context)),
                  DkButton('Add by hand', icon: PhosphorIconsBold.plus, onPressed: () => s.setSection(Section.products)),
                ]),
                step(2, 'channel', 'Connect where customers write to you', 'Your website chat is ready. Connect Facebook Messenger, Instagram or WhatsApp so those messages land here too. You can do this later.', [
                  DkButton('Open Connections', icon: PhosphorIconsRegular.plugsConnected, kind: BtnKind.primary, onPressed: () => s.setSection(Section.connections)),
                  if (!done('channel')) DkButton('Just the website chat for now', kind: BtnKind.ghost, onPressed: () => s.skipStep('channel')),
                ]),
                step(3, 'ai', 'Choose who answers customers', 'Add an AI key (Claude, ChatGPT, Gemini, DeepSeek or another) for natural replies. Without one, the built-in rules still answer prices, stock and orders.', [
                  DkButton('Choose the AI', icon: PhosphorIconsRegular.sparkle, kind: BtnKind.primary, onPressed: () => s.openAssistantTab('engine')),
                  if (!done('ai')) DkButton('The built-in rules are fine for now', kind: BtnKind.ghost, onPressed: () => s.skipStep('ai')),
                ]),
                step(4, 'test', 'Send a test message', 'Pretend to be a customer and ask about a product. You will see exactly what a real customer would get.', [
                  DkButton('Try it now', icon: PhosphorIconsRegular.chatCircleDots, kind: BtnKind.primary, onPressed: () => s.openAssistantTab('try')),
                ]),
              ]),
            ),
          ),
        ),
      ]),
    );
  }
}
