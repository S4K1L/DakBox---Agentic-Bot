import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../brand/icons.dart';
import '../brand/theme.dart';
import '../core/api.dart';
import '../core/format.dart';
import '../core/state.dart';
import '../widgets/kit.dart';
import '../widgets/page.dart';
import '../shell/shell.dart' show Brand, UserMenu;
import 'console_ui.dart';
import 'team.dart' show generatePassword;

/// The platform console: every business, every person, the plans, the platform's own AI keys, server health and a record of what was done.
/// The administrator sees how each business is set up and used (counts, connections, staff activity), never its customers or messages;
/// to look inside a business they must Open it, which joins them as an admin and is written in that business's own activity log.
class PlatformScreen extends StatefulWidget {
  const PlatformScreen({super.key});
  @override
  State<PlatformScreen> createState() => _PlatformScreenState();
}

class _PlatformScreenState extends State<PlatformScreen> {
  String page = 'overview';
  String? business;                 // a business's detail page is open
  String? person;                   // a person's detail page is open

  @override
  void initState() {
    super.initState();
    context.read<AppState>().loadPlatform();
  }

  void _go(String p) => setState(() { page = p; business = null; person = null; });
  void _openBusiness(String slug) => setState(() { page = 'businesses'; business = slug; person = null; });
  void _openPerson(String id) => setState(() { page = 'users'; person = id; business = null; });

  static const _nav = [
    ('overview', 'Overview', PhosphorIconsRegular.gauge),
    ('businesses', 'Businesses', PhosphorIconsRegular.buildings),
    ('users', 'Users', PhosphorIconsRegular.users),
    ('plans', 'Plans', PhosphorIconsRegular.creditCard),
    ('ai', 'AI keys', PhosphorIconsRegular.sparkle),
    ('health', 'Health and backups', PhosphorIconsRegular.heartbeat),
    ('log', 'Activity', PhosphorIconsRegular.clock),
  ];

  Widget _body() => switch (page) {
        'businesses' => ConsoleBusinesses(selected: business, onOpen: _openBusiness, onUser: _openPerson, onBack: () => setState(() => business = null)),
        'users' => ConsoleUsers(selected: person, onOpen: _openPerson, onBusiness: _openBusiness, onBack: () => setState(() => person = null)),
        'plans' => const _Plans(),
        'ai' => const _PlatformAi(),
        'health' => const _Health(),
        'log' => const _Log(),
        _ => ConsoleOverview(onBusiness: _openBusiness, onPage: _go),
      };

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final actions = [
      DkButton('Create a business', icon: PhosphorIconsBold.plus, kind: BtnKind.primary, onPressed: () => showDialog<void>(context: context, barrierColor: Colors.black.withValues(alpha: .45), builder: (_) => const NewBusinessDialog())),
    ];
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        PageHeader(
          title: 'Super admin',
          subtitle: Text('Create businesses and their owners, and manage plans, people and the server. You see how each business is set up and used, not its customers or messages.', style: TypeX.ui(13.5, color: c.text3)),
          actions: actions,
        ),
        Expanded(
          child: LayoutBuilder(builder: (context, box) {
            if (box.maxWidth < 900) {
              return Column(children: [
                UnderTabs(value: page, onChanged: _go, tabs: [for (final n in _nav) (n.$1, n.$2, null)]),
                Expanded(child: Align(alignment: Alignment.topCenter, child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 1100), child: _body()))),
              ]);
            }
            return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Container(
                width: 208, padding: const EdgeInsets.fromLTRB(14, 10, 8, 14),
                decoration: BoxDecoration(border: Border(right: BorderSide(color: c.line))),
                child: Column(children: [
                  for (final n in _nav)
                    Hover(
                      onTap: () => _go(n.$1),
                      builder: (_, h, __) {
                        final on = page == n.$1;
                        return AnimatedContainer(
                          duration: const Duration(milliseconds: 140), height: 40, margin: const EdgeInsets.only(bottom: 3), padding: const EdgeInsets.symmetric(horizontal: 12),
                          decoration: BoxDecoration(color: on ? c.primarySoft : (h ? c.sunken : c.sunken.withValues(alpha: 0)), borderRadius: BorderRadius.circular(11)),
                          child: Row(children: [
                            Icon(n.$3, size: 18, color: on ? c.primary : c.text3),
                            const SizedBox(width: 11),
                            Expanded(child: Text(n.$2, style: TypeX.ui(13.5, w: on ? FontWeight.w800 : FontWeight.w600, color: on ? c.primary : c.text2), maxLines: 1, overflow: TextOverflow.ellipsis)),
                            if (n.$1 == 'users' && s.pAccounts.isNotEmpty) Text('${s.pAccounts.length}', style: TypeX.ui(11.5, w: FontWeight.w700, color: c.text3)),
                            if (n.$1 == 'businesses' && s.pBusinesses.isNotEmpty) Text('${s.pBusinesses.length}', style: TypeX.ui(11.5, w: FontWeight.w700, color: c.text3)),
                          ]),
                        );
                      },
                    ),
                ]),
              ),
              Expanded(child: Align(alignment: Alignment.topCenter, child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 1100), child: _body()))),
            ]);
          }),
        ),
      ]),
    );
  }
}

/// The super admin panel: its own screen, apart from any business. Platform administrators land here; a business's owner and staff never see it.
class ConsoleShell extends StatelessWidget {
  const ConsoleShell({super.key});
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.watch<AppState>();
    return Scaffold(
      backgroundColor: c.bg,
      body: Column(children: [
        Container(
          decoration: BoxDecoration(gradient: c.sidebar),
          child: SafeArea(
            bottom: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(18, 10, 18, 10),
              child: Row(children: [
                const Brand(),
                const SizedBox(width: 14),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                  decoration: BoxDecoration(color: Colors.white.withValues(alpha: .12), borderRadius: BorderRadius.circular(9), border: Border.all(color: Colors.white.withValues(alpha: .18))),
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    Icon(PhosphorIconsFill.shieldCheck, size: 13, color: Colors.white.withValues(alpha: .9)),
                    const SizedBox(width: 6),
                    Text('SUPER ADMIN', style: TypeX.ui(10.5, w: FontWeight.w800, color: Colors.white, ls: 1)),
                  ]),
                ),
                const Spacer(),
                UserMenu(dark: true, below: true, child: Row(mainAxisSize: MainAxisSize.min, children: [
                  Avatar(name: (s.me['name'] ?? 'You') as String, hue: (s.me['hue'] ?? 225) as num, size: 34),
                  const SizedBox(width: 10),
                  Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                    Text((s.me['name'] ?? '') as String, style: TypeX.ui(12.5, w: FontWeight.w700, color: Colors.white)),
                    Text('Super administrator', style: TypeX.ui(11, color: c.inkText)),
                  ]),
                  const SizedBox(width: 8),
                  Icon(PhosphorIconsBold.caretDown, size: 12, color: c.inkText),
                ])),
              ]),
            ),
          ),
        ),
        const Expanded(child: Padding(padding: EdgeInsets.all(12), child: PlatformScreen())),
      ]),
    );
  }
}

// ------------------------------------------------------------------ dialogs
class ConfirmDialog extends StatelessWidget {
  const ConfirmDialog({super.key, required this.title, required this.body, required this.action});
  final String title, body, action;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Dialog(
      backgroundColor: Colors.transparent, insetPadding: const EdgeInsets.all(20),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 440),
        child: Panel(radius: 24, child: Padding(padding: const EdgeInsets.all(24), child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: TypeX.display(20, color: c.text)),
          const Gap(8),
          Text(body, style: TypeX.ui(13.5, color: c.text2, h: 1.5)),
          const Gap(20),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context, false)),
            const Gap(8),
            DkButton(action, kind: BtnKind.primary, onPressed: () => Navigator.pop(context, true)),
          ]),
        ]))),
      ),
    );
  }
}

class DeleteBusinessDialog extends StatefulWidget {
  const DeleteBusinessDialog({super.key, required this.slug, required this.name});
  final String slug, name;
  @override
  State<DeleteBusinessDialog> createState() => DeleteBusinessDialogState();
}

class DeleteBusinessDialogState extends State<DeleteBusinessDialog> {
  final ctl = TextEditingController();
  String? error;
  bool busy = false;
  @override
  void dispose() { ctl.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    return Dialog(
      backgroundColor: Colors.transparent, insetPadding: const EdgeInsets.all(20),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 460),
        child: Panel(radius: 24, child: Padding(padding: const EdgeInsets.all(24), child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Delete ${widget.name}?', style: TypeX.display(20, color: c.text)),
          const Gap(8),
          Text('This removes its products, customers, conversations, orders and settings for good. It cannot be undone. Export its data first if its owner may want it. People keep their accounts.', style: TypeX.ui(13.5, color: c.text2, h: 1.5)),
          const Gap(14),
          if (error != null) Container(margin: const EdgeInsets.only(bottom: 12), padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: c.dangerSoft, borderRadius: BorderRadius.circular(12)), child: Text(error!, style: TypeX.ui(13, w: FontWeight.w600, color: c.text))),
          DkField(controller: ctl, label: 'Type  ${widget.slug}  to confirm', mono: true),
          const Gap(20),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
            const Gap(8),
            ListenableBuilder(listenable: ctl, builder: (_, __) => DkButton(busy ? 'Deleting…' : 'Delete for good', kind: BtnKind.primary, onPressed: busy || ctl.text.trim().toLowerCase() != widget.slug ? null : () async {
              setState(() { busy = true; error = null; });
              final r = await s.deleteBusiness(widget.slug, ctl.text.trim());
              if (!context.mounted) return;
              if (r['error'] != null) { setState(() { busy = false; error = r['error'] as String; }); return; }
              Navigator.pop(context);
              s.toast('${widget.name} was deleted.');
            })),
          ]),
        ]))),
      ),
    );
  }
}

class NewBusinessDialog extends StatefulWidget {
  const NewBusinessDialog({super.key});
  @override
  State<NewBusinessDialog> createState() => NewBusinessDialogState();
}

class NewBusinessDialogState extends State<NewBusinessDialog> {
  final name = TextEditingController();
  final slug = TextEditingController();
  final ownerName = TextEditingController();
  final ownerEmail = TextEditingController();
  late final ownerPw = TextEditingController(text: generatePassword());
  String plan = 'free';
  String? error;
  bool busy = false;
  J? created;                                      // the result, shown after creating

  @override
  void dispose() { for (final t in [name, slug, ownerName, ownerEmail, ownerPw]) { t.dispose(); } super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    return Dialog(
      backgroundColor: Colors.transparent, insetPadding: const EdgeInsets.all(20),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 500),
        child: Panel(radius: 24, child: Padding(padding: const EdgeInsets.all(24), child: SingleChildScrollView(child: created != null ? _done(context, s) : _form(context, s)))),
      ),
    );
  }

  Widget _done(BuildContext context, AppState s) {
    final c = context.c;
    final owner = created!['owner'] as Map?;
    final biz = created!['business'] as Map;
    final isNew = owner?['created'] == true;
    return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [Icon(PhosphorIconsFill.checkCircle, color: c.ok, size: 26), const SizedBox(width: 10), Expanded(child: Text('${biz['name']} is ready', style: TypeX.display(21, color: c.text)))]),
      const Gap(12),
      Text(isNew ? 'Give the owner these details. They sign in, choose their own password, and then run the business from their own panel, where they add their staff.' : 'The owner already had an account, so they sign in as usual and will find this business in their account menu.', style: TypeX.ui(13.5, color: c.text2, h: 1.5)),
      const Gap(14),
      Container(
        padding: const EdgeInsets.all(14), width: double.infinity,
        decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(14), border: Border.all(color: c.line)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Kv('Owner', '${owner?['name']}'),
          Kv('Email', '${owner?['email']}', mono: true),
          if (isNew) Kv('Temporary password', ownerPw.text, mono: true),
          Kv('Plan', '${biz['plan']}'),
        ]),
      ),
      const Gap(20),
      Row(mainAxisAlignment: MainAxisAlignment.end, children: [
        if (isNew) DkButton('Copy sign-in details', icon: PhosphorIconsRegular.copy, kind: BtnKind.ghost, onPressed: () { Clipboard.setData(ClipboardData(text: 'Dakbox sign-in\nEmail: ${owner?['email']}\nTemporary password: ${ownerPw.text}\nYou will choose your own password after you sign in.')); s.toast('Copied.'); }),
        const Gap(8),
        DkButton('Done', kind: BtnKind.primary, onPressed: () => Navigator.pop(context)),
      ]),
    ]);
  }

  Widget _form(BuildContext context, AppState s) {
    final c = context.c;
    final existing = s.pAccounts.any((a) => (a['email'] as String).toLowerCase() == ownerEmail.text.trim().toLowerCase() && ownerEmail.text.trim().isNotEmpty);
    return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [Expanded(child: Text('Create a business', style: TypeX.display(21, color: c.text))), DkIconButton(PhosphorIconsBold.x, size: 32, onPressed: () => Navigator.pop(context))]),
      const Gap(6),
      Text('A separate workspace with its own database, products, customers and team. Its owner signs in to their own panel and adds their own staff; you are not made a member.', style: TypeX.ui(13, color: c.text3, h: 1.45)),
      const Gap(16),
      if (error != null) Container(margin: const EdgeInsets.only(bottom: 14), padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: c.dangerSoft, borderRadius: BorderRadius.circular(12)), child: Text(error!, style: TypeX.ui(13, w: FontWeight.w600, color: c.text))),
      Label('Business'),
      const Gap(8),
      DkField(controller: name, label: 'Business name', hint: 'For example: Rina Saree House'),
      const Gap(10),
      DkField(controller: slug, label: 'Short address (optional)', hint: 'rina-saree-house', mono: true),
      const Gap(12),
      Label('Plan'),
      const Gap(6),
      Wrap(spacing: 8, runSpacing: 8, children: [
        for (final p in s.pPlans)
          Hover(
            onTap: () => setState(() => plan = p['id'] as String),
            builder: (_, h, __) => Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
              decoration: BoxDecoration(color: plan == p['id'] ? c.primarySoft : c.surface, borderRadius: BorderRadius.circular(11), border: Border.all(color: plan == p['id'] ? c.primary : (h ? c.line2 : c.line))),
              child: Text('${p['name']}', style: TypeX.ui(13, w: FontWeight.w700, color: plan == p['id'] ? c.primary : c.text2)),
            ),
          ),
      ]),
      const Gap(18),
      Label('Business owner'),
      const Gap(8),
      DkField(controller: ownerEmail, label: 'Owner email', hint: 'owner@theirshop.com', onSubmitted: (_) {}),
      ListenableBuilder(listenable: ownerEmail, builder: (_, __) {
        final ex = s.pAccounts.any((a) => (a['email'] as String).toLowerCase() == ownerEmail.text.trim().toLowerCase() && ownerEmail.text.trim().isNotEmpty);
        if (ex) return Padding(padding: const EdgeInsets.only(top: 10), child: Row(children: [Icon(PhosphorIconsFill.checkCircle, size: 14, color: c.ok), const SizedBox(width: 6), Expanded(child: Text('This person already has an account. They keep their password and get this business too.', style: TypeX.ui(12.5, color: c.text2, h: 1.4)))]));
        return Padding(padding: const EdgeInsets.only(top: 10), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          DkField(controller: ownerName, label: 'Owner name'),
          const Gap(10),
          Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Expanded(child: DkField(controller: ownerPw, label: 'Temporary password', mono: true)),
            const SizedBox(width: 8),
            DkButton('New', small: true, onPressed: () => setState(() => ownerPw.text = generatePassword())),
          ]),
        ]));
      }),
      const Gap(22),
      Row(mainAxisAlignment: MainAxisAlignment.end, children: [
        DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
        const Gap(8),
        DkButton(busy ? 'Creating…' : 'Create business', kind: BtnKind.primary, onPressed: busy ? null : () async {
          setState(() { busy = true; error = null; });
          final r = await s.createBusiness(name.text.trim(), slug.text.trim(), plan: plan, ownerName: existing ? '' : ownerName.text.trim(), ownerEmail: ownerEmail.text.trim(), ownerPassword: existing ? '' : ownerPw.text);
          if (!mounted) return;
          if (r['error'] != null) { setState(() { busy = false; error = r['error'] as String; }); return; }
          setState(() { busy = false; created = r; });
        }),
      ]),
    ]);
  }
}

// ------------------------------------------------------------------ plans
String _lim(dynamic v) => v == null ? 'No limit' : '$v';

class _Plans extends StatelessWidget {
  const _Plans();
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    return ListView(padding: const EdgeInsets.fromLTRB(24, 16, 24, 28), children: [
      Text('Limits are per business. A single business can be given different numbers from its own plan from the API; the plan is the default.', style: TypeX.ui(12.5, color: c.text3, h: 1.45)),
      const Gap(12),
      for (final p in s.pPlans)
        Container(
          margin: const EdgeInsets.only(bottom: 10), padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(16), border: Border.all(color: c.line)),
          child: Row(children: [
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [Text('${p['name']}', style: TypeX.ui(15, w: FontWeight.w800, color: c.text)), const SizedBox(width: 8), Tag(plural(p['businesses'] as int, 'business', 'businesses'), small: true), if (p['platformAi'] == true) const Padding(padding: EdgeInsets.only(left: 6), child: Tag('Platform AI', tone: 'ai', small: true))]),
              const SizedBox(height: 6),
              Text('Team ${_lim(p['seats'])} · Products ${_lim(p['products'])} · AI replies a month ${_lim(p['aiReplies'])}', style: TypeX.ui(12.5, color: c.text3)),
            ])),
            DkButton('Edit', small: true, onPressed: () => showDialog<void>(context: context, barrierColor: Colors.black.withValues(alpha: .45), builder: (_) => _EditPlan(plan: p))),
          ]),
        ),
    ]);
  }
}

class _EditPlan extends StatefulWidget {
  const _EditPlan({required this.plan});
  final J plan;
  @override
  State<_EditPlan> createState() => _EditPlanState();
}

class _EditPlanState extends State<_EditPlan> {
  late final name = TextEditingController(text: widget.plan['name'] as String);
  late final seats = TextEditingController(text: '${widget.plan['seats'] ?? ''}');
  late final products = TextEditingController(text: '${widget.plan['products'] ?? ''}');
  late final ai = TextEditingController(text: '${widget.plan['aiReplies'] ?? ''}');
  late bool platformAi = widget.plan['platformAi'] == true;
  String? error;
  bool busy = false;
  @override
  void dispose() { for (final t in [name, seats, products, ai]) { t.dispose(); } super.dispose(); }

  int? _n(TextEditingController t) => t.text.trim().isEmpty ? null : int.tryParse(t.text.trim());

  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    return Dialog(
      backgroundColor: Colors.transparent, insetPadding: const EdgeInsets.all(20),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 460),
        child: Panel(radius: 24, child: Padding(padding: const EdgeInsets.all(24), child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [Expanded(child: Text('Edit plan', style: TypeX.display(21, color: c.text))), DkIconButton(PhosphorIconsBold.x, size: 32, onPressed: () => Navigator.pop(context))]),
          const Gap(6),
          Text('Leave a number empty for no limit.', style: TypeX.ui(13, color: c.text3)),
          const Gap(14),
          if (error != null) Container(margin: const EdgeInsets.only(bottom: 12), padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: c.dangerSoft, borderRadius: BorderRadius.circular(12)), child: Text(error!, style: TypeX.ui(13, w: FontWeight.w600, color: c.text))),
          DkField(controller: name, label: 'Name'),
          const Gap(10),
          Row(children: [
            Expanded(child: DkField(controller: seats, label: 'Team members', mono: true)),
            const Gap(8),
            Expanded(child: DkField(controller: products, label: 'Products', mono: true)),
            const Gap(8),
            Expanded(child: DkField(controller: ai, label: 'AI replies / month', mono: true)),
          ]),
          const Gap(12),
          Row(children: [
            DkSwitch(value: platformAi, onChanged: (v) => setState(() => platformAi = v)),
            const SizedBox(width: 10),
            Expanded(child: Text('Can use the platform’s AI keys (counted against the monthly allowance)', style: TypeX.ui(13, color: c.text2, h: 1.4))),
          ]),
          const Gap(20),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
            const Gap(8),
            DkButton(busy ? 'Saving…' : 'Save plan', kind: BtnKind.primary, onPressed: busy ? null : () async {
              setState(() { busy = true; error = null; });
              final r = await s.savePlan(widget.plan['id'] as String, {'name': name.text.trim(), 'seats': _n(seats), 'products': _n(products), 'aiReplies': _n(ai), 'platformAi': platformAi});
              if (!context.mounted) return;
              if (r['error'] != null) { setState(() { busy = false; error = r['error'] as String; }); return; }
              Navigator.pop(context);
              s.toast('Plan saved.');
            }),
          ]),
        ]))),
      ),
    );
  }
}

// ------------------------------------------------------------------ the platform's AI keys
class _PlatformAi extends StatefulWidget {
  const _PlatformAi();
  @override
  State<_PlatformAi> createState() => _PlatformAiState();
}

class _PlatformAiState extends State<_PlatformAi> {
  J? info;
  String sel = 'anthropic';
  final key = TextEditingController();
  final model = TextEditingController();
  final small = TextEditingController();
  String? error, notice;
  bool busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() { for (final t in [key, model, small]) { t.dispose(); } super.dispose(); }

  Future<void> _load() async {
    final r = await context.read<AppState>().platformAi();
    if (!mounted) return;
    setState(() { if (r['error'] == null) { info = r; _fill(); } else { error = r['error'] as String; } });
  }

  J? get _p => ((info?['items'] as List?) ?? const []).cast<J>().cast<J?>().firstWhere((p) => p!['id'] == sel, orElse: () => null);

  void _fill() {
    model.text = (_p?['model'] as String?) ?? '';
    small.text = (_p?['smallModel'] as String?) ?? '';
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    final p = _p;
    if (info == null || p == null) return Center(child: error != null ? Text(error!, style: TypeX.ui(13, color: c.danger)) : CircularProgressIndicator(color: c.primary, strokeWidth: 3));
    return ListView(padding: const EdgeInsets.fromLTRB(24, 16, 24, 28), children: [
      Text('${info!['note']} Keys are checked with the provider, stored encrypted with the server’s master key and never shown again.', style: TypeX.ui(12.5, color: c.text3, h: 1.45)),
      const Gap(14),
      Wrap(spacing: 8, runSpacing: 8, children: [
        for (final x in (info!['items'] as List).cast<J>())
          Hover(
            onTap: busy ? null : () => setState(() { sel = x['id'] as String; error = null; notice = null; key.clear(); _fill(); }),
            builder: (_, h, __) => Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
              decoration: BoxDecoration(color: sel == x['id'] ? c.primarySoft : c.surface, borderRadius: BorderRadius.circular(11), border: Border.all(color: sel == x['id'] ? c.primary : (h ? c.line2 : c.line))),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Text('${x['label']}'.split(' ').first, style: TypeX.ui(13, w: FontWeight.w700, color: sel == x['id'] ? c.primary : c.text2)),
                if (x['hasKey'] == true) ...[const SizedBox(width: 6), Icon(PhosphorIconsFill.key, size: 11, color: c.ok)],
              ]),
            ),
          ),
      ]),
      const Gap(14),
      if (p['hasKey'] == true)
        Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(14), border: Border.all(color: c.line)),
          child: Row(children: [
            Icon(PhosphorIconsFill.key, size: 18, color: c.primary),
            const SizedBox(width: 10),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${p['label']}   ${p['masked'] ?? ''}', style: TypeX.mono(13.5, w: FontWeight.w700, color: c.text)),
              Text(p['source'] == 'stored' ? 'Saved here for the whole platform.' : 'From the server’s environment setting. A key saved here overrides it.', style: TypeX.ui(12, color: c.text3)),
            ])),
            if (p['source'] == 'stored') DkButton('Remove', small: true, kind: BtnKind.ghost, onPressed: busy ? null : () async {
              final r = await s.removePlatformAi(sel);
              if (r['error'] != null) { setState(() => error = r['error'] as String); } else { await _load(); }
            }),
          ]),
        ),
      if (error != null) Container(margin: const EdgeInsets.only(top: 12), padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: c.dangerSoft, borderRadius: BorderRadius.circular(12)), child: Text(error!, style: TypeX.ui(13, w: FontWeight.w600, color: c.text))),
      if (notice != null && error == null) Container(margin: const EdgeInsets.only(top: 12), padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: c.okSoft, borderRadius: BorderRadius.circular(12)), child: Text(notice!, style: TypeX.ui(13, w: FontWeight.w600, color: c.text))),
      const Gap(14),
      Label(p['hasKey'] == true ? 'Replace the key' : 'Paste the API key'),
      const Gap(6),
      DkField(controller: key, hint: 'Key', mono: true, obscure: true),
      const Gap(10),
      Row(children: [
        Expanded(child: DkField(controller: model, label: 'Model', hint: sel == 'anthropic' ? 'Default' : 'Model name', mono: true)),
        const Gap(8),
        Expanded(child: DkField(controller: small, label: 'Small model (optional)', mono: true)),
      ]),
      const Gap(14),
      Align(alignment: Alignment.centerLeft, child: DkButton(busy ? 'Checking…' : 'Check and save', icon: PhosphorIconsBold.check, kind: BtnKind.primary, onPressed: busy ? null : () async {
        if (key.text.trim().isEmpty) { setState(() => error = 'Paste a key first.'); return; }
        setState(() { busy = true; error = null; notice = null; });
        final r = await s.savePlatformAi(sel, key.text.trim(), model: model.text.trim(), smallModel: small.text.trim());
        if (!mounted) return;
        if (r['error'] != null) { setState(() { busy = false; error = r['error'] as String; }); return; }
        key.clear();
        setState(() { busy = false; info = {'items': r['items'], 'note': r['note']}; notice = 'Saved. Businesses on a plan with platform AI can use it right away.'; _fill(); });
      })),
    ]);
  }
}

// ------------------------------------------------------------------ what the administrator did
class _Log extends StatelessWidget {
  const _Log();
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    if (s.pLog.isEmpty) return Padding(padding: const EdgeInsets.all(24), child: Text('Nothing yet. Creating, suspending, deleting and exporting businesses, plan changes and account changes are recorded here.', style: TypeX.ui(13, color: c.text3)));
    return ListView(padding: const EdgeInsets.fromLTRB(24, 16, 24, 28), children: [
      for (final e in s.pLog)
        Container(
          margin: const EdgeInsets.only(bottom: 8), padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
          decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(12), border: Border.all(color: c.line)),
          child: Row(children: [
            Expanded(child: Text('${e['actor']}  ·  ${e['action']}${e['target'] != null ? '  ·  ${e['target']}' : ''}${e['detail'] != null ? '  ·  ${e['detail']}' : ''}', style: TypeX.ui(13, color: c.text), maxLines: 2, overflow: TextOverflow.ellipsis)),
            const SizedBox(width: 10),
            Text(relative(e['at'] as String), style: TypeX.ui(12, color: c.text3)),
          ]),
        ),
    ]);
  }
}


// ------------------------------------------------------------------ health and backups
class _Health extends StatefulWidget {
  const _Health();
  @override
  State<_Health> createState() => _HealthState();
}

class _HealthState extends State<_Health> {
  J? health, backups;
  String? error, notice;
  bool busy = false;
  final Map<String, J> drills = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final s = context.read<AppState>();
    final h = await s.platformHealth();
    final b = await s.platformBackups();
    if (!mounted) return;
    setState(() { if (h['error'] == null) health = h; if (b['error'] == null) backups = b; error = (h['error'] ?? b['error']) as String?; });
  }

  String _size(int? b) => b == null ? '—' : (b > 1 << 20 ? '${(b / (1 << 20)).toStringAsFixed(1)} MB' : '${(b / 1024).ceil()} KB');

  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    if (health == null) return Center(child: error != null ? Text(error!, style: TypeX.ui(13, color: c.danger)) : CircularProgressIndicator(color: c.primary, strokeWidth: 3));
    final ok = health!['ok'] == true;
    final problems = (health!['problems'] as List).cast<String>();
    final items = ((backups?['items'] as List?) ?? const []).cast<J>();
    Widget box(Color bg, IconData ic, Color fg, String t) => Container(margin: const EdgeInsets.only(bottom: 8), padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(12)), child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Icon(ic, size: 16, color: fg), const SizedBox(width: 8), Expanded(child: Text(t, style: TypeX.ui(13, w: FontWeight.w600, color: c.text, h: 1.4)))]));
    return ListView(padding: const EdgeInsets.fromLTRB(24, 16, 24, 28), children: [
      Container(
        padding: const EdgeInsets.all(16), margin: const EdgeInsets.only(bottom: 14),
        decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(16), border: Border.all(color: c.line)),
        child: Row(children: [
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(ok ? 'Everything looks healthy' : 'Needs attention', style: TypeX.ui(15, w: FontWeight.w800, color: c.text)),
            const SizedBox(height: 3),
            Text('Up ${(health!['uptimeSeconds'] as int) ~/ 3600} h · ${health!['openDatabases']} databases open · ${health!['hosted'] == true ? 'hosted mode' : 'single-install mode'}${health!['strict'] == true ? ', strict' : ''}', style: TypeX.ui(12.5, color: c.text3)),
          ])),
          Tag(ok ? 'Healthy' : 'Attention', tone: ok ? 'ok' : 'warn', dot: true),
        ]),
      ),
      for (final p in problems) box(c.warnSoft, PhosphorIconsFill.warning, c.warn, p),
      const Gap(8),
      Row(children: [
        Expanded(child: Text('BACKUPS', style: TypeX.ui(10.5, w: FontWeight.w800, color: c.text3, ls: .9))),
        DkButton(busy ? 'Backing up…' : 'Back up now', icon: PhosphorIconsRegular.downloadSimple, kind: BtnKind.primary, small: true, onPressed: busy ? null : () async {
          setState(() { busy = true; error = null; notice = null; });
          final r = await s.backupNow();
          if (!mounted) return;
          setState(() { busy = false; if (r['error'] != null) { error = r['error'] as String; } else { notice = (r['verify'] as Map)['ok'] == true ? 'Backed up and checked.' : 'Backed up, but the check found a problem.'; } });
          _load();
        }),
      ]),
      const Gap(8),
      Text('${backups?['note'] ?? ''} Folder: ${backups?['directory'] ?? ''}', style: TypeX.ui(12, color: c.text3, h: 1.4)),
      const Gap(10),
      if (error != null) box(c.dangerSoft, PhosphorIconsFill.warningCircle, c.danger, error!),
      if (notice != null) box(c.okSoft, PhosphorIconsFill.checkCircle, c.ok, notice!),
      if (items.isEmpty) Text('No backups yet.', style: TypeX.ui(13, color: c.text3)),
      for (final b in items.take(8))
        Container(
          margin: const EdgeInsets.only(bottom: 8), padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(12), border: Border.all(color: c.line)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${b['name']}', style: TypeX.mono(12.5, w: FontWeight.w700, color: c.text)),
                Text('${plural(b['businesses'] as int, 'business', 'businesses')} · ${_size(b['bytes'] as int?)}${b['note'] != null ? ' · ${b['note']}' : ''}', style: TypeX.ui(12, color: c.text3)),
              ])),
              DkButton('Test restore', small: true, onPressed: () async {
                final r = await s.drillBackup(b['name'] as String);
                if (mounted) setState(() => drills['${b['name']}'] = r);
              }),
            ]),
            if (drills['${b['name']}'] != null) ...[
              const SizedBox(height: 8),
              Builder(builder: (_) {
                final r = drills['${b['name']}']!;
                if (r['error'] != null) return Text('${r['error']}', style: TypeX.ui(12.5, color: c.danger));
                final good = r['ok'] == true;
                return Text(good ? 'Restore test passed: ${r['restored']} business databases opened from this backup, live data untouched.' : 'Restore test FAILED: ${(r['problems'] as List).join('; ')}', style: TypeX.ui(12.5, w: FontWeight.w600, color: good ? c.ok : c.danger, h: 1.4));
              }),
            ],
          ]),
        ),
      const Gap(14),
      Text('DATABASES', style: TypeX.ui(10.5, w: FontWeight.w800, color: c.text3, ls: .9)),
      const Gap(8),
      for (final b in (health!['businesses'] as List).cast<J>())
        Padding(padding: const EdgeInsets.only(bottom: 4), child: Row(children: [
          Expanded(child: Text('${b['slug']}', style: TypeX.mono(12.5, color: c.text))),
          Text(b['fileMissing'] == true ? 'MISSING' : _size(b['bytes'] as int?), style: TypeX.ui(12.5, w: FontWeight.w700, color: b['fileMissing'] == true ? c.danger : c.text2)),
        ])),
      const Gap(14),
      Text('BACKGROUND JOBS (LAST PASS)', style: TypeX.ui(10.5, w: FontWeight.w800, color: c.text3, ls: .9)),
      const Gap(8),
      if ((health!['jobs'] as Map).isEmpty) Text('None has run since the server started.', style: TypeX.ui(12.5, color: c.text3)),
      for (final e in (health!['jobs'] as Map).entries)
        Padding(padding: const EdgeInsets.only(bottom: 4), child: Text('${e.key}: ${(e.value as Map)['ok']} ok${((e.value as Map)['failed'] as Map).isEmpty ? '' : ', failed for ${((e.value as Map)['failed'] as Map).keys.join(', ')}'} · ${relative((e.value as Map)['at'] as String)}', style: TypeX.ui(12.5, color: ((e.value as Map)['failed'] as Map).isEmpty ? c.text2 : c.danger))),
    ]);
  }
}
