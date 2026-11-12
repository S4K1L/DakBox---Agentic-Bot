import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../brand/icons.dart';
import '../brand/theme.dart';
import '../core/api.dart';
import '../core/format.dart';
import '../core/state.dart';
import '../widgets/kit.dart';
import '../widgets/page.dart';
import 'guide_ui.dart';

/// The Assistant screen's Engine tab: which AI answers customers (Claude, ChatGPT, Gemini, DeepSeek or another OpenAI-compatible
/// service), its key and its model. Owners and admins only.
class AiEngineTab extends StatefulWidget {
  const AiEngineTab({super.key});
  @override
  State<AiEngineTab> createState() => _AiEngineTabState();
}

class _AiEngineTabState extends State<AiEngineTab> {
  J? info;
  J? plan;
  String? sel;                                   // the provider being looked at
  final key = TextEditingController();
  final base = TextEditingController();
  final model = TextEditingController();
  final small = TextEditingController();
  bool busy = false;
  String? error, notice;
  bool? modelAvailable;
  final Map<String, List<String>> models = {};   // provider -> model names its account lists
  String? loadedFor;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() { for (final t in [key, base, model, small]) { t.dispose(); } super.dispose(); }

  J? _p(String id) => ((info?['providers'] as List?) ?? const []).cast<J>().cast<J?>().firstWhere((p) => p!['id'] == id, orElse: () => null);

  Future<void> _load() async {
    final st = context.read<AppState>();
    final r = await st.aiKeyInfo();
    final pl = await st.planInfo();
    if (!mounted) return;
    if (pl['error'] == null) plan = pl;
    setState(() { if (r['error'] != null) { error = r['error'] as String; } else { info = r; sel ??= r['provider'] as String; _fill(); } });
    _loadModels();
  }

  void _fill() {
    final p = _p(sel ?? '');
    if (p == null || loadedFor == sel) return;
    loadedFor = sel;
    model.text = (p['model'] as String?) ?? '';
    small.text = sel == 'anthropic' || p['smallModel'] == p['model'] ? '' : ((p['smallModel'] as String?) ?? '');
    base.text = (p['baseUrl'] as String?) ?? '';
    key.clear();
    error = null; notice = null; modelAvailable = null;
  }

  Future<void> _loadModels() async {
    final id = sel;
    final p = id == null ? null : _p(id);
    if (id == null || p == null || p['hasKey'] != true || models.containsKey(id)) return;
    final r = await context.read<AppState>().checkAiKey(id);
    if (!mounted) return;
    setState(() { if (r['error'] == null) { models[id] = ((r['models'] as List?) ?? const []).cast<String>(); } });
  }

  void _pick(String id) {
    setState(() { sel = id; loadedFor = null; _fill(); });
    _loadModels();
  }

  Future<void> _run(Future<J> Function() f, {String? ok}) async {
    setState(() { busy = true; error = null; notice = null; });
    final r = await f();
    if (!mounted) return;
    setState(() {
      busy = false;
      if (r['error'] != null) { error = r['error'] as String; return; }
      info = r;
      modelAvailable = r['modelAvailable'] as bool?;
      if (r['models'] != null && sel != null) { models[sel!] = (r['models'] as List).cast<String>(); }
      notice = ok;
      loadedFor = null;
      _fill();
    });
  }

  Future<void> _saveKey({bool skip = false}) async {
    final id = sel!;
    final p = _p(id)!;
    final v = key.text.trim();
    if (v.isEmpty && p['keyOptional'] != true) { setState(() => error = 'Paste your API key first.'); return; }
    if (id == 'custom' && base.text.trim().isEmpty) { setState(() => error = 'Enter the provider’s address first.'); return; }
    final m = model.text.trim();
    await _run(() => context.read<AppState>().saveAiKey(id, v, model: m.isEmpty ? null : m, smallModel: small.text.trim().isEmpty ? null : small.text.trim(), baseUrl: id == 'custom' ? base.text.trim() : null, skipCheck: skip),
        ok: 'Saved. ${(model.text.trim().isEmpty && id != 'anthropic') ? 'Now choose a model below to switch it on.' : 'The next customer message uses it.'}');
    if (error == null) key.clear();
  }

  Future<void> _saveModels() async {
    final id = sel!;
    if (id != 'anthropic' && model.text.trim().isEmpty) { setState(() => error = 'Choose or type the model to use.'); return; }
    await _run(() => context.read<AppState>().setAiProvider(id, model: model.text.trim(), smallModel: small.text.trim(), baseUrl: id == 'custom' ? base.text.trim() : null), ok: '${_p(id)!['label']} is now answering customers.');
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.watch<AppState>();
    final i = info;
    if (!s.can('settings.write')) {
      return Align(alignment: Alignment.topCenter, child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 820), child: Padding(padding: const EdgeInsets.all(24), child: Text('Only owners and admins can see or change the AI provider and key.', style: TypeX.ui(13, color: c.text3)))));
    }
    final active = i?['provider'] as String?;
    final live = i != null && i['engine'] != 'offline';
    final p = sel == null ? null : _p(sel!);
    final lastError = i?['lastError'] as String?;
    final isActive = p != null && p['id'] == active;
    final needsModel = p != null && p['hasKey'] == true && (p['model'] == null || (p['model'] as String).isEmpty);
    final suggestions = (models[sel] ?? const <String>[]).where((m) => model.text.trim().isEmpty || (m.toLowerCase().contains(model.text.trim().toLowerCase()) && m != model.text.trim())).take(10).toList();
    return Align(
      alignment: Alignment.topCenter,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 820),
        child: ListView(padding: const EdgeInsets.all(24), children: [
          SectionCard('Who answers customers', icon: PhosphorIconsRegular.heartbeat, margin: const EdgeInsets.only(bottom: 16), child: Row(children: [
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(i == null ? 'Checking…' : (live ? '${i['providerLabel']} is answering' : 'Offline rules are answering'), style: TypeX.ui(15, w: FontWeight.w800, color: c.text)),
              const SizedBox(height: 3),
              Text(live ? 'Using ${i['model']} with tool use against your catalog, orders and policies. If the provider is ever unreachable, the offline rules answer so no customer is left waiting.' : 'No AI is switched on, so a built-in rule engine runs the same tools. Pick a provider below and add its key.', style: TypeX.ui(12.5, color: c.text3, h: 1.45)),
            ])),
            const SizedBox(width: 16),
            Tag(live ? '${i['engineLabel']} live' : 'Offline', tone: live ? 'ok' : 'ai', dot: true),
          ])),
          if (plan != null) _PlanCard(plan: plan!, quota: i?['quota'] as J?),
          SectionCard('AI provider', icon: PhosphorIconsRegular.plugsConnected, margin: const EdgeInsets.only(bottom: 16), child: i == null || p == null
              ? const SizedBox(height: 40)
              : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Wrap(spacing: 8, runSpacing: 8, children: [
                    for (final x in (i['providers'] as List).cast<J>())
                      Hover(
                        onTap: busy ? null : () => _pick(x['id'] as String),
                        builder: (_, h, __) => Container(
                          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
                          decoration: BoxDecoration(color: sel == x['id'] ? c.primarySoft : c.surface, borderRadius: BorderRadius.circular(11), border: Border.all(color: sel == x['id'] ? c.primary : (h ? c.line2 : c.line))),
                          child: Row(mainAxisSize: MainAxisSize.min, children: [
                            Text(_short(x['id'] as String), style: TypeX.ui(13, w: FontWeight.w700, color: sel == x['id'] ? c.primary : c.text2)),
                            if (x['id'] == active && live) ...[const SizedBox(width: 7), Container(width: 7, height: 7, decoration: BoxDecoration(color: c.ok, shape: BoxShape.circle))]
                            else if (x['hasKey'] == true) ...[const SizedBox(width: 6), Icon(PhosphorIconsFill.key, size: 11, color: c.text3)],
                          ]),
                        ),
                      ),
                  ]),
                  const Gap(14),
                  if (p['hasKey'] == true)
                    Container(
                      padding: const EdgeInsets.all(14), width: double.infinity,
                      decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(14), border: Border.all(color: c.line)),
                      child: Row(children: [
                        Icon(PhosphorIconsFill.key, size: 18, color: c.primary),
                        const SizedBox(width: 10),
                        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text('${p['label']}   ${p['masked'] ?? ''}', style: TypeX.mono(13.5, w: FontWeight.w700, color: c.text)),
                          Text(switch (p['source']) { 'panel' => 'Saved here, encrypted for your business only. It is never shown again.', 'platform' => 'Provided with your plan. A key saved here overrides it and is not counted against your plan.', _ => 'Taken from the server’s environment setting. A key saved here overrides it.' }, style: TypeX.ui(12, color: c.text3, h: 1.4)),
                        ])),
                        DkButton('Test', icon: PhosphorIconsRegular.pulse, small: true, kind: BtnKind.soft, onPressed: busy ? null : () => _run(() => s.checkAiKey(sel!), ok: 'The key works.')),
                        if (p['source'] == 'panel') ...[const SizedBox(width: 8), DkButton('Remove', small: true, kind: BtnKind.ghost, onPressed: busy ? null : _confirmRemove)],
                      ]),
                    ),
                  if (isActive && lastError != null) _box(c, c.dangerSoft, PhosphorIconsFill.warningCircle, c.danger, 'The last customer reply could not use ${p['label']}. $lastError${i['lastErrorAt'] != null ? ' (${relative(i['lastErrorAt'] as String)})' : ''}'),
                  if (needsModel) _box(c, c.warnSoft, PhosphorIconsFill.warning, c.warn, 'Choose a model below. Until you do, ${p['label']} cannot answer and the offline rules keep answering.'),
                  if (modelAvailable == false) _box(c, c.warnSoft, PhosphorIconsFill.warning, c.warn, 'This key works, but the provider does not list the model ${model.text.trim().isEmpty ? p['model'] : model.text.trim()} for it. Pick one from the list below.'),
                  if (notice != null && error == null) _box(c, c.okSoft, PhosphorIconsFill.checkCircle, c.ok, notice!),
                  const Gap(14),
                  if (sel == 'custom') ...[
                    DkField(controller: base, label: 'Provider address', hint: 'https://api.groq.com/openai/v1', mono: true),
                    const Gap(10),
                  ],
                  Label(p['hasKey'] == true ? 'Replace the key' : (p['keyOptional'] == true ? 'API key (leave empty if the server needs none)' : 'Paste your API key')),
                  const Gap(6),
                  Row(children: [
                    Expanded(child: DkField(controller: key, hint: sel == 'anthropic' ? 'sk-ant-…' : 'Key', mono: true, obscure: true, onSubmitted: (_) => busy ? null : _saveKey())),
                    const SizedBox(width: 8),
                    DkButton(busy ? 'Checking…' : 'Save key', icon: PhosphorIconsBold.check, kind: BtnKind.primary, onPressed: busy ? null : _saveKey),
                  ]),
                  if (error != null) _box(c, c.dangerSoft, PhosphorIconsFill.warningCircle, c.danger, error!),
                  if (error != null && error!.contains('Could not reach'))
                    Align(alignment: Alignment.centerLeft, child: Padding(padding: const EdgeInsets.only(top: 8), child: Hover(onTap: busy ? null : () => _saveKey(skip: true), builder: (_, h, __) => Text('Save it anyway, without checking', style: TypeX.ui(12.5, w: FontWeight.w700, color: h ? c.primaryHover : c.primary))))),
                  if (p['hasKey'] == true) ...[
                    const Gap(18),
                    Container(height: 1, color: c.line),
                    const Gap(16),
                    Label('Model'),
                    const Gap(6),
                    DkField(controller: model, hint: sel == 'anthropic' ? 'Default: ${p['model']}' : 'Type a model name, or pick one below', mono: true, onSubmitted: (_) {}),
                    if (suggestions.isNotEmpty) ...[
                      const Gap(8),
                      Wrap(spacing: 6, runSpacing: 6, children: [
                        for (final m in suggestions)
                          Hover(
                            onTap: () => setState(() => model.text = m),
                            builder: (_, h, __) => Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6), decoration: BoxDecoration(color: h ? c.primarySoft : c.surface2, borderRadius: BorderRadius.circular(99), border: Border.all(color: h ? c.primary : c.line)), child: Text(m, style: TypeX.mono(11.5, color: h ? c.primary : c.text2))),
                          ),
                      ]),
                    ],
                    const Gap(12),
                    DkField(controller: small, label: 'Model for quick jobs (translations, summaries). Optional', hint: sel == 'anthropic' ? 'Default: claude-haiku-5-5' : 'Leave empty to use the model above', mono: true),
                    const Gap(14),
                    Row(children: [
                      DkButton(isActive ? 'Save models' : 'Use ${_short(sel!)} for customers', icon: PhosphorIconsBold.check, kind: BtnKind.primary, onPressed: busy ? null : _saveModels),
                      const SizedBox(width: 10),
                      if (!isActive) Expanded(child: Text('Switches the assistant to ${p['label']} on the next message. Your other keys stay saved.', style: TypeX.ui(12, color: c.text3, h: 1.4))),
                    ]),
                  ],
                ])),
          if (p != null) HowToConnect(key: ValueKey('guide-$sel-${p['hasKey']}'), title: 'How to get a ${_short(sel!)} key', steps: _guide(p), open: p['hasKey'] != true),
          SectionCard('What is sent to the AI provider', icon: PhosphorIconsRegular.shieldCheck, margin: const EdgeInsets.only(bottom: 16), child: Text(
              'While an AI provider is on, each customer message, and the catalog, order and policy details the assistant looks up to answer it, are sent to that provider to write the reply: ${i == null ? 'the one you choose' : i['providerLabel']}. Without one, nothing leaves your server: the offline rules answer instead. The rules that protect you (order limits, stock, payments, refunds) are enforced by Dakbox, not by the model, so they hold whichever provider you choose; a weaker model may still write worse Bangla or call tools less reliably. Keys are stored encrypted, never shown again, and changes are recorded in the audit log without the key.',
              style: TypeX.ui(13, color: c.text2, h: 1.5))),
        ]),
      ),
    );
  }

  static String _short(String id) => const {'anthropic': 'Claude', 'openai': 'ChatGPT', 'gemini': 'Gemini', 'deepseek': 'DeepSeek', 'custom': 'Other'}[id] ?? id;

  List<String> _guide(J p) => [
        'Open ${p['where']} and sign in, or create an account.',
        'Create a new API key, name it Dakbox, and copy it. Most providers show a key only once.',
        if (sel != 'custom') 'Add credit or a billing method if the provider asks. API use is billed by the provider, separately from any chat subscription.' else 'Copy the provider’s API address too (it ends like /v1). A local server such as Ollama needs a public https address Dakbox can reach, and usually no key.',
        'Paste the key above and press Save key. Dakbox checks it with the provider first, then you choose the model.',
      ];

  Widget _box(DK c, Color bg, IconData icon, Color fg, String text) => Container(
        margin: const EdgeInsets.only(top: 12), padding: const EdgeInsets.all(12), width: double.infinity,
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(12)),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Icon(icon, size: 16, color: fg), const SizedBox(width: 8), Expanded(child: Text(text, style: TypeX.ui(12.5, color: c.text, h: 1.45)))]),
      );

  Future<void> _confirmRemove() async {
    final c = context.c;
    final s = context.read<AppState>();
    final id = sel!;
    final label = _p(id)!['label'];
    final ok = await showDialog<bool>(
      context: context, barrierColor: Colors.black.withValues(alpha: .45),
      builder: (ctx) => Dialog(
        backgroundColor: Colors.transparent, insetPadding: const EdgeInsets.all(20),
        child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 440), child: Panel(radius: 24, shadow: true, child: Padding(padding: const EdgeInsets.all(22), child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Remove the $label key?', style: TypeX.display(19, color: c.text)),
          const Gap(10),
          Text('Dakbox forgets the key saved here. If the server has its own environment key for this provider it is used; otherwise, if this provider is the active one, the offline rules answer customers until you add a key. Other providers’ keys and your conversations are not affected.', style: TypeX.ui(13.5, color: c.text2, h: 1.5)),
          const Gap(18),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(ctx, false)), const Gap(8), DkButton('Remove key', kind: BtnKind.danger, onPressed: () => Navigator.pop(ctx, true))]),
        ])))),
      ),
    );
    if (ok != true || !mounted) return;
    models.remove(id);
    await _run(() => s.removeAiKey(id), ok: 'Key removed.');
  }
}


/// This business's plan and how much of it is used: team seats, products and (for the platform's AI) replies this month.
class _PlanCard extends StatelessWidget {
  const _PlanCard({required this.plan, this.quota});
  final J plan;
  final J? quota;

  Widget _meter(BuildContext context, String label, J m, {String? note, String? openText}) {
    final c = context.c;
    final limit = m['limit'] as int?;
    final used = (m['used'] as int?) ?? 0;
    final full = limit != null && used >= limit;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(label, style: TypeX.ui(13, w: FontWeight.w700, color: c.text))),
          Text(limit == null ? '$used · ${openText ?? 'no limit'}' : '$used of $limit', style: TypeX.mono(12.5, w: FontWeight.w700, color: full ? c.danger : c.text2)),
        ]),
        if (limit != null) ...[
          const SizedBox(height: 6),
          ClipRRect(borderRadius: BorderRadius.circular(4), child: LinearProgressIndicator(value: limit == 0 ? 1 : (used / limit).clamp(0, 1).toDouble(), minHeight: 6, backgroundColor: c.line, color: full ? c.danger : c.primary)),
        ],
        if (note != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text(note, style: TypeX.ui(12, color: c.text3, h: 1.4))),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final ai = plan['ai'] as J;
    final limited = ai['limited'] == true;
    final pl = plan['plan'] as J;
    return SectionCard('Your plan', icon: PhosphorIconsRegular.creditCard, margin: const EdgeInsets.only(bottom: 16), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Expanded(child: Text('${pl['name']} plan', style: TypeX.ui(15, w: FontWeight.w800, color: c.text))),
        if (limited && ai['exhausted'] == true) const Tag('AI allowance used up', tone: 'warn', dot: true),
      ]),
      const Gap(12),
      _meter(context, 'Team members', plan['seats'] as J),
      _meter(context, 'Products', plan['products'] as J),
      _meter(context, 'AI replies this month', ai, openText: pl['platformAi'] == true ? 'your own key' : 'own key only', note: limited ? 'Counts replies written with the platform’s AI. Your own key is never limited.' : (pl['platformAi'] == true ? 'Replies written with your own key are counted here but never limited.' : 'Add your own key below to switch the AI on.')),
    ]));
  }
}
