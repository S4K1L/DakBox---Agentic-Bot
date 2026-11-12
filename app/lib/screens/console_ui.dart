import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../brand/icons.dart';
import '../brand/theme.dart';
import '../core/api.dart';
import '../core/format.dart';
import '../core/state.dart';
import '../widgets/kit.dart';
import '../widgets/page.dart';
import 'platform_ui.dart' show ConfirmDialog, DeleteBusinessDialog;
import 'team.dart' show generatePassword;

const _roles = ['owner', 'admin', 'agent', 'viewer'];

String _roleName(String r) => r[0].toUpperCase() + r.substring(1);

void _err(AppState s, J r, String ok) => s.toast(r['error'] != null ? r['error'] as String : ok, error: r['error'] != null);

/// Usage against a limit (null = no limit).
class UsageMeter extends StatelessWidget {
  const UsageMeter(this.label, this.used, this.limit, {super.key});
  final String label;
  final int used;
  final int? limit;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final full = limit != null && used >= limit!;
    return Expanded(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: TypeX.ui(11.5, w: FontWeight.w700, color: c.text3)),
        const SizedBox(height: 2),
        Text(limit == null ? '$used' : '$used of $limit', style: TypeX.mono(12.5, w: FontWeight.w700, color: full ? c.danger : c.text)),
        if (limit != null) ...[
          const SizedBox(height: 4),
          ClipRRect(borderRadius: BorderRadius.circular(3), child: LinearProgressIndicator(value: limit == 0 ? 1 : (used / limit!).clamp(0, 1).toDouble(), minHeight: 4, backgroundColor: c.line, color: full ? c.danger : c.primary)),
        ],
      ]),
    );
  }
}

Widget _statusTag(String status) => switch (status) {
      'suspended' => const Tag('Suspended', tone: 'danger', small: true),
      'trial' => const Tag('Trial', tone: 'warn', small: true),
      _ => const Tag('Active', tone: 'ok', small: true),
    };

Widget _back(BuildContext context, String label, VoidCallback onTap) {
  final c = context.c;
  return Hover(
    onTap: onTap,
    builder: (_, h, __) => Padding(padding: const EdgeInsets.only(bottom: 14), child: Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(PhosphorIconsBold.arrowLeft, size: 15, color: h ? c.primary : c.text3),
      const SizedBox(width: 6),
      Text(label, style: TypeX.ui(13, w: FontWeight.w700, color: h ? c.primary : c.text3)),
    ])),
  );
}

Widget _pill(BuildContext context, String t, {IconData? icon, bool ok = true, bool menu = false}) {
  final c = context.c;
  return Container(
    padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
    decoration: BoxDecoration(color: ok ? c.sunken : c.dangerSoft, borderRadius: BorderRadius.circular(9)),
    child: Row(mainAxisSize: MainAxisSize.min, children: [
      if (icon != null) ...[Icon(icon, size: 13, color: c.text3), const SizedBox(width: 5)],
      Text(t, style: TypeX.ui(12, w: FontWeight.w600, color: ok ? c.text2 : c.danger)),
      if (menu) ...[const SizedBox(width: 6), Icon(PhosphorIconsBold.caretDown, size: 11, color: c.text3)],
    ]),
  );
}

// ====================================================================== overview
class ConsoleOverview extends StatefulWidget {
  const ConsoleOverview({super.key, required this.onBusiness, required this.onPage});
  final ValueChanged<String> onBusiness;
  final ValueChanged<String> onPage;
  @override
  State<ConsoleOverview> createState() => _ConsoleOverviewState();
}

class _ConsoleOverviewState extends State<ConsoleOverview> {
  J? health;

  @override
  void initState() {
    super.initState();
    context.read<AppState>().platformHealth().then((h) { if (mounted && h['error'] == null) setState(() => health = h); });
  }

  int _sum(List<J> f, String k) => f.fold<int>(0, (a, b) => a + (((b['counts'] as Map?)?[k] as int?) ?? 0));

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final f = s.pFeatures;
    final o = s.pOverview;
    if (o == null) return Center(child: CircularProgressIndicator(color: c.primary, strokeWidth: 3));
    final attention = <(String, String, String?)>[];       // (tone, text, business slug)
    for (final b in f) {
      if (b['error'] != null) attention.add(('danger', '${b['name']}: its database could not be read.', b['slug'] as String));
      if (b['status'] == 'suspended') attention.add(('warn', '${b['name']} is suspended.', b['slug'] as String));
    }
    for (final u in s.pUsage) {
      for (final (k, label) in [('seats', 'team seats'), ('products', 'products'), ('aiReplies', 'AI replies this month')]) {
        final m = u[k] as Map;
        final lim = m['limit'] as int?;
        if (lim != null && lim > 0 && (m['used'] as int) >= lim * .9) attention.add(('warn', '${u['name']} has used ${m['used']} of $lim $label.', u['slug'] as String));
      }
    }
    final never = s.pAccounts.where((a) => a['lastLoginAt'] == null).length;
    final stopped = s.pAccounts.where((a) => a['active'] != true).length;
    if (stopped > 0) attention.add(('', '$stopped ${stopped == 1 ? 'account is' : 'accounts are'} stopped.', null));
    if (never > 0) attention.add(('', '$never ${never == 1 ? 'person has' : 'people have'} never signed in.', null));
    for (final p in ((health?['problems'] as List?) ?? const []).cast<String>()) { attention.add(('danger', p, null)); }
    return ListView(padding: const EdgeInsets.fromLTRB(24, 16, 24, 28), children: [
      LayoutBuilder(builder: (context, box) {
        final cols = box.maxWidth >= 760 ? 4 : 2;
        final tiles = <Widget>[
          _Kpi(PhosphorIconsRegular.buildings, '${(o['businesses'] as Map)['total']}', 'Businesses', '${(o['businesses'] as Map)['active']} active'),
          _Kpi(PhosphorIconsRegular.users, '${o['accounts']}', 'People', '${s.pAccounts.where((a) => a['platformAdmin'] == true).length} platform admin${s.pAccounts.where((a) => a['platformAdmin'] == true).length == 1 ? '' : 's'}'),
          _Kpi(PhosphorIconsRegular.chatCircleDots, '${_sum(f, 'messages30')}', 'Messages, 30 days', '${_sum(f, 'conversations')} conversations in all'),
          _Kpi(PhosphorIconsRegular.shoppingBag, '${_sum(f, 'orders30')}', 'Orders, 30 days', '${_sum(f, 'orders')} in all · ${_sum(f, 'products')} products'),
        ];
        return Wrap(spacing: 10, runSpacing: 10, children: [for (final t in tiles) SizedBox(width: (box.maxWidth - 10 * (cols - 1)) / cols, child: t)]);
      }),
      const Gap(16),
      SectionCard('Needs attention', icon: PhosphorIconsRegular.warning, margin: const EdgeInsets.only(bottom: 16), child: attention.isEmpty
          ? Row(children: [Icon(PhosphorIconsFill.checkCircle, size: 18, color: c.ok), const SizedBox(width: 8), Text('Nothing needs attention right now.', style: TypeX.ui(13.5, color: c.text2))])
          : Column(children: [
              for (final a in attention.take(8))
                Hover(
                  onTap: a.$3 == null ? null : () => widget.onBusiness(a.$3!),
                  builder: (_, h, __) => Container(
                    margin: const EdgeInsets.only(bottom: 6), padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
                    decoration: BoxDecoration(color: a.$1 == 'danger' ? c.dangerSoft : (a.$1 == 'warn' ? c.warnSoft : c.sunken), borderRadius: BorderRadius.circular(10)),
                    child: Row(children: [
                      Icon(a.$1 == 'danger' ? PhosphorIconsFill.warningCircle : PhosphorIconsFill.warning, size: 15, color: a.$1 == 'danger' ? c.danger : (a.$1 == 'warn' ? c.warn : c.text3)),
                      const SizedBox(width: 9),
                      Expanded(child: Text(a.$2, style: TypeX.ui(13, w: FontWeight.w600, color: c.text))),
                      if (a.$3 != null) Icon(PhosphorIconsBold.caretRight, size: 12, color: c.text3),
                    ]),
                  ),
                ),
            ])),
      SectionCard('What each business has set up', icon: PhosphorIconsRegular.plugsConnected, margin: const EdgeInsets.only(bottom: 16), child: _Matrix(onBusiness: widget.onBusiness)),
      SectionCard('Recent platform activity', icon: PhosphorIconsRegular.clock, trailing: Hover(onTap: () => widget.onPage('log'), builder: (_, h, __) => Text('See all', style: TypeX.ui(12, w: FontWeight.w700, color: h ? c.primaryHover : c.primary))), child: s.pLog.isEmpty
          ? Text('Nothing yet.', style: TypeX.ui(13, color: c.text3))
          : Column(children: [
              for (final e in s.pLog.take(6))
                Padding(padding: const EdgeInsets.only(bottom: 7), child: Row(children: [
                  Expanded(child: Text('${e['actor']}  ·  ${e['action']}${e['target'] != null ? '  ·  ${e['target']}' : ''}', style: TypeX.ui(13, color: c.text), maxLines: 1, overflow: TextOverflow.ellipsis)),
                  Text(relative(e['at'] as String), style: TypeX.ui(12, color: c.text3)),
                ])),
            ])),
    ]);
  }
}

class _Kpi extends StatelessWidget {
  const _Kpi(this.icon, this.value, this.label, this.sub);
  final IconData icon;
  final String value, label, sub;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(16), border: Border.all(color: c.line)),
      child: Row(children: [
        Container(width: 38, height: 38, alignment: Alignment.center, decoration: BoxDecoration(color: c.primarySoft, borderRadius: BorderRadius.circular(11)), child: Icon(icon, size: 19, color: c.primary)),
        const SizedBox(width: 12),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(value, style: TypeX.display(22, color: c.text)),
          Text(label, style: TypeX.ui(12, w: FontWeight.w700, color: c.text2), maxLines: 1, overflow: TextOverflow.ellipsis),
          Text(sub, style: TypeX.ui(11.5, color: c.text3), maxLines: 1, overflow: TextOverflow.ellipsis),
        ])),
      ]),
    );
  }
}

/// Every business against what it has connected and how much it is used.
class _Matrix extends StatelessWidget {
  const _Matrix({required this.onBusiness});
  final ValueChanged<String> onBusiness;

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    if (s.pFeatures.isEmpty) return Text('Loading…', style: TypeX.ui(13, color: c.text3));
    const widths = [190.0, 84.0, 120.0, 110.0, 110.0, 96.0, 104.0, 74.0, 84.0, 92.0, 100.0];
    const heads = ['Business', 'Plan', 'Channels', 'Couriers', 'Payments', 'SMS', 'AI', 'Products', 'Orders 30d', 'Messages 30d', 'Last active'];
    Widget cell(int i, Widget w) => SizedBox(width: widths[i], child: Padding(padding: const EdgeInsets.only(right: 10), child: w));
    Widget txt(String t, {Color? col, bool bold = false}) => Text(t, style: TypeX.ui(12.5, w: bold ? FontWeight.w700 : FontWeight.w500, color: col ?? c.text2), maxLines: 1, overflow: TextOverflow.ellipsis);
    Widget list(List l) => l.isEmpty ? txt('—', col: c.text3) : Tooltip(message: l.join(', '), child: txt(l.join(', ')));
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Column(children: [
        Row(children: [for (var i = 0; i < heads.length; i++) cell(i, Text(heads[i].toUpperCase(), style: TypeX.ui(10.5, w: FontWeight.w800, color: c.text3, ls: .6)))]),
        const SizedBox(height: 8),
        for (final b in s.pFeatures)
          Hover(
            onTap: () => onBusiness(b['slug'] as String),
            builder: (_, h, __) {
              final err = b['error'] != null;
              final ft = (b['features'] as Map?) ?? const {};
              final ct = (b['counts'] as Map?) ?? const {};
              final channels = ((ft['channels'] as List?) ?? const []).cast<String>();
              return Container(
                padding: const EdgeInsets.symmetric(vertical: 9), margin: const EdgeInsets.only(bottom: 2),
                decoration: BoxDecoration(color: h ? c.surface2 : c.surface2.withValues(alpha: 0), borderRadius: BorderRadius.circular(10)),
                child: Row(children: [
                  cell(0, Row(children: [Flexible(child: txt('${b['name']}', col: c.text, bold: true)), if (b['status'] == 'suspended') const Padding(padding: EdgeInsets.only(left: 6), child: Tag('Off', tone: 'danger', small: true))])),
                  cell(1, txt('${b['plan'] ?? '—'}')),
                  if (err) ...[for (var i = 2; i < 11; i++) cell(i, i == 2 ? Text('Could not be read', style: TypeX.ui(12, color: c.danger)) : const SizedBox())] else ...[
                    cell(2, Row(children: [if (ft['webChat'] == true) const Padding(padding: EdgeInsets.only(right: 4), child: ChannelIcon(kind: 'web', size: 20)), for (final k in channels) Padding(padding: const EdgeInsets.only(right: 4), child: ChannelIcon(kind: k, size: 20)), if (channels.isEmpty && ft['webChat'] != true) txt('—', col: c.text3)])),
                    cell(3, list((ft['couriers'] as List?) ?? const [])),
                    cell(4, list((ft['payments'] as List?) ?? const [])),
                    cell(5, list((ft['sms'] as List?) ?? const [])),
                    cell(6, txt(ft['ai'] == 'offline' ? 'Offline rules' : '${ft['ai']}${ft['aiSource'] == 'platform' || ft['aiSource'] == 'environment' ? ' (platform)' : ''}', col: ft['ai'] == 'offline' ? c.text3 : c.text2)),
                    cell(7, txt('${ct['products'] ?? 0}')),
                    cell(8, txt('${ct['orders30'] ?? 0}')),
                    cell(9, txt('${ct['messages30'] ?? 0}')),
                    cell(10, txt(b['lastActivityAt'] == null ? 'Never' : relative(b['lastActivityAt'] as String), col: b['lastActivityAt'] == null ? c.text3 : c.text2)),
                  ],
                ]),
              );
            },
          ),
      ]),
    );
  }
}

// ====================================================================== businesses
class ConsoleBusinesses extends StatefulWidget {
  const ConsoleBusinesses({super.key, required this.selected, required this.onOpen, required this.onUser, required this.onBack});
  final String? selected;
  final ValueChanged<String> onOpen;
  final ValueChanged<String> onUser;
  final VoidCallback onBack;
  @override
  State<ConsoleBusinesses> createState() => _ConsoleBusinessesState();
}

class _ConsoleBusinessesState extends State<ConsoleBusinesses> {
  String q = '';
  String status = 'all';

  @override
  Widget build(BuildContext context) {
    if (widget.selected != null) return _BusinessDetail(slug: widget.selected!, onBack: widget.onBack, onUser: widget.onUser);
    final s = context.watch<AppState>();
    final c = context.c;
    final usage = {for (final u in s.pUsage) u['slug']: u};
    final list = s.pBusinesses.where((b) {
      if (status != 'all' && b['status'] != status) return false;
      final t = q.trim().toLowerCase();
      return t.isEmpty || '${b['name']} ${b['slug']} ${(b['owners'] as List).join(' ')}'.toLowerCase().contains(t);
    }).toList();
    return ListView(padding: const EdgeInsets.fromLTRB(24, 16, 24, 28), children: [
      Wrap(spacing: 10, runSpacing: 10, crossAxisAlignment: WrapCrossAlignment.center, children: [
        SearchBox(hint: 'Search businesses or owners', width: 280, onChanged: (v) => setState(() => q = v)),
        Seg<String>(small: true, items: const [('all', 'All'), ('active', 'Active'), ('suspended', 'Suspended')], value: status, onChanged: (v) => setState(() => status = v)),
        Text(plural(list.length, 'business', 'businesses'), style: TypeX.ui(12.5, color: c.text3)),
      ]),
      const Gap(14),
      if (list.isEmpty) Padding(padding: const EdgeInsets.all(24), child: Text('No business matches.', style: TypeX.ui(13.5, color: c.text3))),
      for (var i = 0; i < list.length; i++)
        Builder(builder: (context) {
          final b = list[i];
          final u = usage[b['slug']] as Map?;
          return Reveal(
            delay: i * 25,
            child: Hover(
              onTap: () => widget.onOpen(b['slug'] as String),
              builder: (_, h, __) => Container(
                margin: const EdgeInsets.only(bottom: 10), padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(16), border: Border.all(color: h ? c.primaryLine : c.line)),
                child: Opacity(
                  opacity: b['status'] == 'suspended' ? .7 : 1,
                  child: Row(children: [
                    Container(width: 40, height: 40, alignment: Alignment.center, decoration: BoxDecoration(color: c.primarySoft, borderRadius: BorderRadius.circular(12)), child: Icon(PhosphorIconsRegular.storefront, size: 20, color: c.primary)),
                    const SizedBox(width: 12),
                    Expanded(flex: 3, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('${b['name']}', style: TypeX.ui(14.5, w: FontWeight.w800, color: c.text), maxLines: 1, overflow: TextOverflow.ellipsis),
                      Text('${b['slug']} · ${plural(b['members'] as int, 'person', 'people')}${(b['owners'] as List).isEmpty ? '' : ' · ${(b['owners'] as List).first}'}', style: TypeX.ui(12, color: c.text3), maxLines: 1, overflow: TextOverflow.ellipsis),
                    ])),
                    if (u != null && MediaQuery.of(context).size.width > 900) ...[
                      const SizedBox(width: 12),
                      Expanded(flex: 4, child: Row(children: [
                        UsageMeter('Team', (u['seats'] as Map)['used'] as int, (u['seats'] as Map)['limit'] as int?), const SizedBox(width: 14),
                        UsageMeter('Products', (u['products'] as Map)['used'] as int, (u['products'] as Map)['limit'] as int?), const SizedBox(width: 14),
                        UsageMeter('AI replies', (u['aiReplies'] as Map)['used'] as int, (u['aiReplies'] as Map)['limit'] as int?),
                      ])),
                    ],
                    const SizedBox(width: 12),
                    Tag(u == null ? '${b['plan']}' : '${u['plan']}', tone: 'ai', small: true),
                    const SizedBox(width: 6),
                    _statusTag('${b['status']}'),
                    const SizedBox(width: 8),
                    Icon(PhosphorIconsBold.caretRight, size: 14, color: c.text3),
                  ]),
                ),
              ),
            ),
          );
        }),
    ]);
  }
}

class _BusinessDetail extends StatefulWidget {
  const _BusinessDetail({required this.slug, required this.onBack, required this.onUser});
  final String slug;
  final VoidCallback onBack;
  final ValueChanged<String> onUser;
  @override
  State<_BusinessDetail> createState() => _BusinessDetailState();
}

class _BusinessDetailState extends State<_BusinessDetail> {
  J? d;
  String? error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant _BusinessDetail old) {
    super.didUpdateWidget(old);
    if (old.slug != widget.slug) { d = null; _load(); }
  }

  Future<void> _load() async {
    final r = await context.read<AppState>().businessDetail(widget.slug);
    if (!mounted) return;
    setState(() { if (r['error'] != null) { error = r['error'] as String; } else { d = r; error = null; } });
  }

  Future<void> _open(J b) async {
    final s = context.read<AppState>();
    final member = s.businesses.any((m) => m['slug'] == widget.slug);
    if (!member) {
      final ok = await showDialog<bool>(context: context, builder: (_) => ConfirmDialog(title: 'Open ${b['name']}?', body: 'You will join this business as an admin so you can see inside it. Its owners can see that you joined in their activity log, and you can leave again afterwards.', action: 'Join and open'));
      if (ok != true) return;
      final r = await s.joinBusiness(widget.slug);
      if (r['error'] != null) { s.toast(r['error'] as String, error: true); return; }
    }
    final e = await s.switchBusiness(b['id'] as String);
    if (e != null) s.toast(e, error: true);
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    if (error != null) return Padding(padding: const EdgeInsets.all(24), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [_back(context, 'All businesses', widget.onBack), Text(error!, style: TypeX.ui(13.5, color: c.danger))]));
    if (d == null) return Center(child: CircularProgressIndicator(color: c.primary, strokeWidth: 3));
    final b = d!;
    final suspended = b['status'] == 'suspended';
    final isDefault = b['slug'] == 'default';
    final plan = b['plan'] as Map;
    final counts = b['counts'] as Map;
    final ft = b['features'] as Map;
    final ai = b['ai'] as Map;
    final channels = (b['channels'] as List).cast<J>();
    final integ = (b['integrations'] as List).cast<J>().where((i) => i['id'] != 'cod').toList();
    final members = (b['members'] as List).cast<J>();
    final audit = (b['audit'] as List).cast<J>();
    final sources = (b['catalogSources'] as List).cast<J>();
    final quota = ai['quota'] as Map?;

    final overview = SectionCard('Plan and use', icon: PhosphorIconsRegular.creditCard, margin: const EdgeInsets.only(bottom: 14), trailing: PopupMenuButton<String>(
      tooltip: 'Change plan', color: c.surface,
      onSelected: (v) async { final r = await s.patchBusiness(widget.slug, {'plan': v}); _err(s, r, 'Plan changed.'); _load(); },
      itemBuilder: (_) => [for (final p in s.pPlans) PopupMenuItem<String>(value: p['id'] as String, child: Text('${p['name']}', style: TypeX.ui(13.5, w: p['name'] == plan['name'] ? FontWeight.w800 : FontWeight.w600, color: c.text)))],
      child: Text('Change plan', style: TypeX.ui(12, w: FontWeight.w700, color: c.primary)),
    ), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [Text('${plan['name']}', style: TypeX.ui(15, w: FontWeight.w800, color: c.text)), if (plan['platformAi'] == true) const Padding(padding: EdgeInsets.only(left: 8), child: Tag('Platform AI', tone: 'ai', small: true))]),
      const Gap(12),
      Row(children: [
        UsageMeter('Team', (b['usage'] as Map)['seats'] as int, plan['seats'] as int?), const SizedBox(width: 14),
        UsageMeter('Products', counts['products'] as int, plan['products'] as int?), const SizedBox(width: 14),
        UsageMeter('AI replies', (b['usage'] as Map)['aiReplies'] as int, plan['aiReplies'] as int?),
      ]),
      const Gap(14),
      Wrap(spacing: 8, runSpacing: 8, children: [
        _pill(context, '${counts['customers']} customers', icon: PhosphorIconsRegular.users),
        _pill(context, '${counts['conversations']} conversations (${counts['openConversations']} open)', icon: PhosphorIconsRegular.chatCircleDots),
        _pill(context, '${counts['orders']} orders (${counts['orders30']} in 30 days)', icon: PhosphorIconsRegular.shoppingBag),
        _pill(context, '${counts['messages30']} messages in 30 days', icon: PhosphorIconsRegular.tray),
      ]),
      const Gap(10),
      Text('Created ${shortDate(b['createdAt'] as String?)} · last activity ${b['lastActivityAt'] == null ? 'never' : relative(b['lastActivityAt'] as String)}', style: TypeX.ui(12, color: c.text3)),
    ]));

    final connected = SectionCard('Channels and connections', icon: PhosphorIconsRegular.plugsConnected, margin: const EdgeInsets.only(bottom: 14), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Label('Channels'),
      const Gap(8),
      for (final ch in channels)
        Padding(padding: const EdgeInsets.only(bottom: 7), child: Row(children: [
          ChannelIcon(kind: ch['kind'] as String, size: 24, circle: true),
          const SizedBox(width: 10),
          Expanded(child: Text('${ch['name']}', style: TypeX.ui(13.5, w: FontWeight.w600, color: c.text))),
          Tag(ch['kind'] == 'web' ? 'Ready' : (ch['live'] == true ? (ch['status'] == 'ok' ? 'Live' : '${ch['status']}') : 'Not live'), tone: ch['kind'] == 'web' || (ch['live'] == true && ch['status'] == 'ok') ? 'ok' : (ch['status'] == 'danger' ? 'danger' : ''), small: true),
          if (ch['lastWebhookAt'] != null) Padding(padding: const EdgeInsets.only(left: 8), child: Text(relative(ch['lastWebhookAt'] as String), style: TypeX.ui(11.5, color: c.text3))),
        ])),
      const Gap(8),
      for (final grp in ['Couriers', 'Payments', 'SMS']) ...[
        Label(grp),
        const Gap(6),
        Wrap(spacing: 6, runSpacing: 6, children: [
          for (final i in integ.where((x) => x['group'] == grp))
            Tag('${i['name']}${i['live'] == true ? '' : ''}', tone: i['live'] == true ? 'ok' : '', dot: i['live'] == true, small: true),
        ]),
        const Gap(10),
      ],
      Label('Website import'),
      const Gap(6),
      if (sources.isEmpty) Text('No website connected.', style: TypeX.ui(12.5, color: c.text3)),
      for (final src in sources) Padding(padding: const EdgeInsets.only(bottom: 4), child: Text('${src['host']} · ${src['kind']} · ${src['lastCount']} products${src['lastSyncAt'] != null ? ' · synced ${relative(src['lastSyncAt'] as String)}' : ''}${src['ordersCount'] != null && src['ordersCount'] != 0 ? ' · ${src['ordersCount']} orders received' : ''}${src['lastError'] != null ? ' · error' : ''}', style: TypeX.ui(12.5, color: src['lastError'] != null ? c.danger : c.text2))),
    ]));

    final assistant = SectionCard('Assistant', icon: PhosphorIconsRegular.sparkle, margin: const EdgeInsets.only(bottom: 14), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Tag(ai['engine'] == 'offline' ? 'Offline rules' : '${ai['provider']}', tone: ai['engine'] == 'offline' ? '' : 'ok', dot: true),
        const SizedBox(width: 8),
        if (ai['source'] != null) Tag(ai['source'] == 'panel' ? 'Own key' : 'Platform key', tone: ai['source'] == 'panel' ? 'accent' : 'ai', small: true),
        if (ai['model'] != null) Padding(padding: const EdgeInsets.only(left: 8), child: Text('${ai['model']}', style: TypeX.mono(12, color: c.text3))),
      ]),
      if (quota != null) ...[const Gap(10), Text('${quota['used']} of ${quota['limit']} platform AI replies used this month${quota['exhausted'] == true ? ' (used up)' : ''}', style: TypeX.ui(12.5, color: quota['exhausted'] == true ? c.danger : c.text2))],
      if (ai['lastError'] != null) ...[const Gap(8), Text('${ai['lastError']}', style: TypeX.ui(12, color: c.danger, h: 1.4))],
    ]));

    final team = SectionCard('Team', icon: PhosphorIconsRegular.usersThree, margin: const EdgeInsets.only(bottom: 14), child: Column(children: [
      for (final m in members)
        Hover(
          onTap: () => widget.onUser(m['id'] as String),
          builder: (_, h, __) => Container(
            margin: const EdgeInsets.only(bottom: 4), padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 7),
            decoration: BoxDecoration(color: h ? c.surface2 : c.surface2.withValues(alpha: 0), borderRadius: BorderRadius.circular(10)),
            child: Row(children: [
              Avatar(name: '${m['name']}', hue: 220, size: 30),
              const SizedBox(width: 10),
              Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${m['name']}', style: TypeX.ui(13.5, w: FontWeight.w700, color: c.text), maxLines: 1, overflow: TextOverflow.ellipsis),
                Text('${m['email']} · ${m['lastLoginAt'] == null ? 'never signed in' : 'last sign-in ${relative(m['lastLoginAt'] as String)}'}', style: TypeX.ui(11.5, color: c.text3), maxLines: 1, overflow: TextOverflow.ellipsis),
              ])),
              if (m['active'] != true) const Padding(padding: EdgeInsets.only(right: 6), child: Tag('Off', tone: 'danger', small: true)),
              Tag(_roleName('${m['role']}'), tone: m['role'] == 'owner' ? 'ai' : (m['role'] == 'admin' ? 'accent' : (m['role'] == 'agent' ? 'ok' : '')), small: true),
            ]),
          ),
        ),
      Align(alignment: Alignment.centerLeft, child: Padding(padding: const EdgeInsets.only(top: 6), child: DkButton('Add a person', icon: PhosphorIconsBold.userPlus, small: true, onPressed: () => showDialog<void>(context: context, barrierColor: Colors.black.withValues(alpha: .45), builder: (_) => NewUserDialog(business: widget.slug)).then((_) => _load())))),
    ]));

    final guide = SectionCard('Setup guide', icon: PhosphorIconsRegular.rocketLaunch, margin: const EdgeInsets.only(bottom: 14), child: Text((b['setupGuide'] as Map)['shown'] == true ? 'The guide is still showing to its owners and admins: they have not finished or hidden it.' : 'Finished or hidden.', style: TypeX.ui(13, color: c.text2, h: 1.4)));

    final activity = SectionCard('Recent staff activity', icon: PhosphorIconsRegular.clock, margin: const EdgeInsets.only(bottom: 14), child: audit.isEmpty
        ? Text('Nothing yet.', style: TypeX.ui(13, color: c.text3))
        : Column(children: [
            for (final a in audit.take(12))
              Padding(padding: const EdgeInsets.only(bottom: 6), child: Row(children: [
                Expanded(child: Text('${a['actor']} · ${a['action']}${a['target'] != null ? ' · ${a['target']}' : ''}', style: TypeX.ui(12.5, color: c.text), maxLines: 1, overflow: TextOverflow.ellipsis)),
                const SizedBox(width: 8),
                Text(relative(a['at'] as String), style: TypeX.ui(11.5, color: c.text3)),
              ])),
          ]));

    return ListView(padding: const EdgeInsets.fromLTRB(24, 16, 24, 28), children: [
      _back(context, 'All businesses', widget.onBack),
      Wrap(spacing: 12, runSpacing: 12, crossAxisAlignment: WrapCrossAlignment.center, children: [
        Row(mainAxisSize: MainAxisSize.min, children: [
          Container(width: 48, height: 48, alignment: Alignment.center, decoration: BoxDecoration(color: c.primarySoft, borderRadius: BorderRadius.circular(14)), child: Icon(PhosphorIconsRegular.storefront, size: 24, color: c.primary)),
          const SizedBox(width: 14),
          Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(mainAxisSize: MainAxisSize.min, children: [Text('${b['name']}', style: TypeX.display(24, color: c.text)), const SizedBox(width: 10), _statusTag('${b['status']}')]),
            Text('${b['slug']} · ${ft['webChat'] == true ? 'website chat on' : 'no website chat'}', style: TypeX.mono(12.5, color: c.text3)),
          ]),
        ]),
        Wrap(spacing: 8, runSpacing: 8, children: [
          if (!suspended) DkButton('Open', icon: PhosphorIconsRegular.arrowSquareOut, kind: BtnKind.primary, small: true, onPressed: () => _open(b)),
          DkButton('Export data', icon: PhosphorIconsRegular.downloadSimple, small: true, onPressed: () async { final e = await s.exportBusiness(widget.slug); s.toast(e ?? 'Your download is starting.', error: e != null); }),
          if (!isDefault) DkButton(suspended ? 'Reactivate' : 'Suspend', small: true, kind: suspended ? BtnKind.soft : BtnKind.ghost, onPressed: () async {
            if (!suspended) {
              final ok = await showDialog<bool>(context: context, builder: (_) => ConfirmDialog(title: 'Suspend ${b['name']}?', body: 'Everyone working in it is moved out at once and cannot open it until you reactivate it. Nothing is deleted.', action: 'Suspend'));
              if (ok != true) return;
            }
            final r = await s.patchBusiness(widget.slug, {'status': suspended ? 'active' : 'suspended'});
            _err(s, r, suspended ? 'Reactivated.' : 'Suspended.');
            _load();
          }),
          if (!isDefault) DkButton('Delete…', small: true, kind: BtnKind.danger, onPressed: () async {
            await showDialog<void>(context: context, barrierColor: Colors.black.withValues(alpha: .45), builder: (_) => DeleteBusinessDialog(slug: widget.slug, name: '${b['name']}'));
            if (mounted && !s.pBusinesses.any((x) => x['slug'] == widget.slug)) widget.onBack();
          }),
        ]),
      ]),
      const Gap(18),
      LayoutBuilder(builder: (context, box) {
        if (box.maxWidth < 860) return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [overview, connected, assistant, team, guide, activity]);
        return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: Column(children: [overview, connected, assistant])),
          const SizedBox(width: 14),
          Expanded(child: Column(children: [team, guide, activity])),
        ]);
      }),
    ]);
  }
}

// ====================================================================== users
class ConsoleUsers extends StatefulWidget {
  const ConsoleUsers({super.key, required this.selected, required this.onOpen, required this.onBusiness, required this.onBack});
  final String? selected;
  final ValueChanged<String> onOpen;
  final ValueChanged<String> onBusiness;
  final VoidCallback onBack;
  @override
  State<ConsoleUsers> createState() => _ConsoleUsersState();
}

class _ConsoleUsersState extends State<ConsoleUsers> {
  String q = '';
  String filter = 'all';

  @override
  Widget build(BuildContext context) {
    if (widget.selected != null) return _UserDetail(id: widget.selected!, onBack: widget.onBack, onBusiness: widget.onBusiness);
    final s = context.watch<AppState>();
    final c = context.c;
    final all = s.pAccounts;
    final list = all.where((a) {
      switch (filter) {
        case 'admins': if (a['platformAdmin'] != true) return false;
        case 'stopped': if (a['active'] == true) return false;
        case 'never': if (a['lastLoginAt'] != null) return false;
        case 'nobiz': if ((a['businesses'] as List).isNotEmpty) return false;
      }
      final t = q.trim().toLowerCase();
      return t.isEmpty || '${a['name']} ${a['email']} ${(a['businesses'] as List).map((b) => (b as Map)['name']).join(' ')}'.toLowerCase().contains(t);
    }).toList();
    return ListView(padding: const EdgeInsets.fromLTRB(24, 16, 24, 28), children: [
      Wrap(spacing: 10, runSpacing: 10, crossAxisAlignment: WrapCrossAlignment.center, children: [
        SearchBox(hint: 'Search name, email or business', width: 280, onChanged: (v) => setState(() => q = v)),
        Seg<String>(small: true, items: [('all', 'All ${all.length}'), ('admins', 'Admins'), ('stopped', 'Stopped'), ('never', 'Never signed in'), ('nobiz', 'No business')], value: filter, onChanged: (v) => setState(() => filter = v)),
        DkButton('New user', icon: PhosphorIconsBold.userPlus, kind: BtnKind.primary, small: true, onPressed: () => showDialog<void>(context: context, barrierColor: Colors.black.withValues(alpha: .45), builder: (_) => const NewUserDialog())),
      ]),
      const Gap(14),
      if (list.isEmpty) Padding(padding: const EdgeInsets.all(24), child: Text('No one matches.', style: TypeX.ui(13.5, color: c.text3))),
      for (var i = 0; i < list.length; i++)
        Builder(builder: (context) {
          final a = list[i];
          final ms = (a['businesses'] as List).cast<Map>();
          return Reveal(
            delay: i * 18,
            child: Hover(
              onTap: () => widget.onOpen(a['id'] as String),
              builder: (_, h, __) => Container(
                margin: const EdgeInsets.only(bottom: 8), padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(14), border: Border.all(color: h ? c.primaryLine : c.line)),
                child: Opacity(
                  opacity: a['active'] == true ? 1 : .6,
                  child: Row(children: [
                    Avatar(name: '${a['name']}', hue: 220, size: 38),
                    const SizedBox(width: 12),
                    Expanded(flex: 3, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Row(children: [
                        Flexible(child: Text('${a['name']}', style: TypeX.ui(14, w: FontWeight.w800, color: c.text), overflow: TextOverflow.ellipsis)),
                        if (a['platformAdmin'] == true) const Padding(padding: EdgeInsets.only(left: 8), child: Tag('Platform admin', tone: 'ai', small: true)),
                        if (a['active'] != true) const Padding(padding: EdgeInsets.only(left: 6), child: Tag('Stopped', tone: 'danger', small: true)),
                      ]),
                      Text('${a['email']}', style: TypeX.ui(12, color: c.text3), overflow: TextOverflow.ellipsis),
                    ])),
                    const SizedBox(width: 10),
                    Expanded(flex: 3, child: ms.isEmpty ? Text('No business', style: TypeX.ui(12.5, color: c.text3)) : Wrap(spacing: 5, runSpacing: 4, children: [for (final b in ms.take(3)) Tag('${b['name']} · ${b['role']}${b['active'] == true ? '' : ' (off)'}', small: true), if (ms.length > 3) Tag('+${ms.length - 3}', small: true)])),
                    const SizedBox(width: 10),
                    SizedBox(width: 108, child: Text(a['lastLoginAt'] == null ? 'Never signed in' : relative(a['lastLoginAt'] as String), style: TypeX.ui(12, color: c.text3), textAlign: TextAlign.right)),
                    const SizedBox(width: 6),
                    Icon(PhosphorIconsBold.caretRight, size: 14, color: c.text3),
                  ]),
                ),
              ),
            ),
          );
        }),
    ]);
  }
}

class _UserDetail extends StatefulWidget {
  const _UserDetail({required this.id, required this.onBack, required this.onBusiness});
  final String id;
  final VoidCallback onBack;
  final ValueChanged<String> onBusiness;
  @override
  State<_UserDetail> createState() => _UserDetailState();
}

class _UserDetailState extends State<_UserDetail> {
  J? d;
  String? error;
  final name = TextEditingController();
  String addBusiness = '';
  String addRole = 'agent';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() { name.dispose(); super.dispose(); }

  Future<void> _load() async {
    final r = await context.read<AppState>().accountDetail(widget.id);
    if (!mounted) return;
    setState(() { if (r['error'] != null) { error = r['error'] as String; } else { d = r; error = null; name.text = r['name'] as String; } });
  }

  Future<void> _do(Future<J> Function() f, String ok) async {
    final r = await f();
    if (!mounted) return;
    _err(context.read<AppState>(), r, ok);
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    if (error != null) return Padding(padding: const EdgeInsets.all(24), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [_back(context, 'All users', widget.onBack), Text(error!, style: TypeX.ui(13.5, color: c.danger))]));
    if (d == null) return Center(child: CircularProgressIndicator(color: c.primary, strokeWidth: 3));
    final a = d!;
    final id = a['id'] as String;
    final me = id == s.user['id'];
    final ms = (a['businesses'] as List).cast<J>();
    final sessions = (a['sessionList'] as List).cast<J>();
    final log = (a['platformLog'] as List).cast<J>();
    final addable = s.pBusinesses.where((b) => !ms.any((m) => m['slug'] == b['slug'])).toList();
    if (addable.isNotEmpty && !addable.any((b) => b['slug'] == addBusiness)) addBusiness = addable.first['slug'] as String;

    final profile = SectionCard('Profile', icon: PhosphorIconsRegular.userCircle, margin: const EdgeInsets.only(bottom: 14), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Expanded(child: DkField(controller: name, label: 'Name')),
        const SizedBox(width: 8),
        DkButton('Save name', small: true, onPressed: () => _do(() => s.patchAccount(id, {'name': name.text.trim()}), 'Name saved.')),
      ]),
      const Gap(12),
      Kv('Email', '${a['email']}'),
      Kv('Created', shortDate(a['createdAt'] as String?)),
      Kv('Last sign-in', a['lastLoginAt'] == null ? 'Never' : relative(a['lastLoginAt'] as String)),
      Kv('Open sessions', '${a['sessions']}'),
      Kv('Password', a['mustChange'] == true ? 'Temporary: must be changed at next sign-in' : 'Set by the person'),
    ]));

    final access = SectionCard('Businesses and roles', icon: PhosphorIconsRegular.storefront, margin: const EdgeInsets.only(bottom: 14), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (ms.isEmpty) Text('Not in any business.', style: TypeX.ui(13, color: c.text3)),
      for (final m in ms)
        Container(
          margin: const EdgeInsets.only(bottom: 8), padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(12)),
          child: Row(children: [
            Expanded(child: Hover(onTap: () => widget.onBusiness(m['slug'] as String), builder: (_, h, __) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${m['name']}', style: TypeX.ui(13.5, w: FontWeight.w800, color: h ? c.primary : c.text)),
              Text('${m['slug']}${m['status'] == 'suspended' ? ' · suspended' : ''}', style: TypeX.mono(11.5, color: c.text3)),
            ]))),
            PopupMenuButton<String>(
              tooltip: 'Change role', color: c.surface,
              onSelected: (v) => _do(() => s.setMembership(id, m['slug'] as String, {'role': v}), 'Role changed.'),
              itemBuilder: (_) => [for (final r in _roles) PopupMenuItem<String>(value: r, child: Text(_roleName(r), style: TypeX.ui(13.5, w: r == m['role'] ? FontWeight.w800 : FontWeight.w600, color: c.text)))],
              child: IgnorePointer(child: Row(mainAxisSize: MainAxisSize.min, children: [Tag(_roleName('${m['role']}'), tone: m['role'] == 'owner' ? 'ai' : (m['role'] == 'admin' ? 'accent' : (m['role'] == 'agent' ? 'ok' : ''))), const SizedBox(width: 4), Icon(PhosphorIconsBold.caretDown, size: 11, color: c.text3)])),
            ),
            const SizedBox(width: 8),
            Tooltip(message: m['active'] == true ? 'Active: switch off' : 'Off: switch on', child: DkSwitch(value: m['active'] == true, onChanged: (v) => _do(() => s.setMembership(id, m['slug'] as String, {'active': v}), v ? 'Switched on.' : 'Switched off.'))),
            const SizedBox(width: 6),
            DkIconButton(PhosphorIconsRegular.x, size: 30, onPressed: () async {
              final ok = await showDialog<bool>(context: context, builder: (_) => ConfirmDialog(title: 'Remove from ${m['name']}?', body: '${a['name']} will lose access to this business immediately. Their account stays.', action: 'Remove'));
              if (ok == true) _do(() => s.removeMembership(id, m['slug'] as String), 'Removed.');
            }),
          ]),
        ),
      if (addable.isNotEmpty) ...[
        const Gap(6),
        Label('Add to a business'),
        const Gap(8),
        Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
          PopupMenuButton<String>(
            color: c.surface, onSelected: (v) => setState(() => addBusiness = v),
            itemBuilder: (_) => [for (final b in addable) PopupMenuItem<String>(value: b['slug'] as String, child: Text('${b['name']}', style: TypeX.ui(13.5, color: c.text)))],
            child: IgnorePointer(child: _pill(context, '${addable.firstWhere((b) => b['slug'] == addBusiness)['name']}', menu: true)),
          ),
          PopupMenuButton<String>(
            color: c.surface, onSelected: (v) => setState(() => addRole = v),
            itemBuilder: (_) => [for (final r in _roles) PopupMenuItem<String>(value: r, child: Text(_roleName(r), style: TypeX.ui(13.5, color: c.text)))],
            child: IgnorePointer(child: _pill(context, _roleName(addRole), menu: true)),
          ),
          DkButton('Add', icon: PhosphorIconsBold.plus, small: true, kind: BtnKind.soft, onPressed: () => _do(() => s.setMembership(id, addBusiness, {'role': addRole}), 'Added.')),
        ]),
      ],
    ]));

    final sess = SectionCard('Open sessions', icon: PhosphorIconsRegular.heartbeat, margin: const EdgeInsets.only(bottom: 14), child: sessions.isEmpty
        ? Text('Not signed in anywhere.', style: TypeX.ui(13, color: c.text3))
        : Column(children: [
            for (final x in sessions)
              Padding(padding: const EdgeInsets.only(bottom: 8), child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Icon(PhosphorIconsRegular.desktop, size: 16, color: c.text3),
                const SizedBox(width: 10),
                Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${x['businessName'] ?? 'No business selected'} · last seen ${relative(x['lastSeenAt'] as String)}', style: TypeX.ui(13, w: FontWeight.w600, color: c.text)),
                  Text('${x['ip'] ?? ''} ${(x['device'] as String?) ?? ''}'.trim(), style: TypeX.ui(11.5, color: c.text3), maxLines: 1, overflow: TextOverflow.ellipsis),
                ])),
              ])),
          ]));

    final actions = SectionCard('Actions', icon: PhosphorIconsRegular.lightning, margin: const EdgeInsets.only(bottom: 14), child: Wrap(spacing: 8, runSpacing: 8, children: [
      DkButton('Reset password…', icon: PhosphorIconsRegular.key, small: true, onPressed: me ? null : () => showDialog<void>(context: context, barrierColor: Colors.black.withValues(alpha: .45), builder: (_) => ResetPasswordDialog(id: id, name: '${a['name']}')).then((_) => _load())),
      DkButton('Sign out everywhere', small: true, onPressed: me ? null : () => _do(() => s.patchAccount(id, {'signOut': true}), 'Signed out of every device.')),
      DkButton(a['platformAdmin'] == true ? 'Remove platform admin' : 'Make platform admin', small: true, kind: BtnKind.ghost, onPressed: () async {
        if (a['platformAdmin'] != true) {
          final ok = await showDialog<bool>(context: context, builder: (_) => ConfirmDialog(title: 'Make ${a['name']} a platform administrator?', body: 'They will be able to see and change every business, plan and account on this server.', action: 'Make administrator'));
          if (ok != true) return;
        }
        _do(() => s.patchAccount(id, {'platformAdmin': a['platformAdmin'] != true}), 'Updated.');
      }),
      if (!me) DkButton(a['active'] == true ? 'Stop account' : 'Allow account', small: true, kind: a['active'] == true ? BtnKind.danger : BtnKind.soft, onPressed: () => _do(() => s.patchAccount(id, {'active': a['active'] != true}), a['active'] == true ? 'Account stopped.' : 'Account allowed.')),
      if (!me && ms.isEmpty && a['platformAdmin'] != true) DkButton('Delete account…', small: true, kind: BtnKind.danger, onPressed: () async {
        final ok = await showDialog<bool>(context: context, builder: (_) => ConfirmDialog(title: 'Delete ${a['name']}’s account?', body: 'The account and its sign-ins are removed for good. This cannot be undone.', action: 'Delete'));
        if (ok != true) return;
        final r = await s.deleteAccount(id);
        if (!mounted) return;
        if (r['error'] != null) { s.toast(r['error'] as String, error: true); } else { s.toast('Account deleted.'); widget.onBack(); }
      }),
    ]));

    final history = SectionCard('Platform activity about this account', icon: PhosphorIconsRegular.clock, child: log.isEmpty
        ? Text('Nothing yet.', style: TypeX.ui(13, color: c.text3))
        : Column(children: [for (final e in log) Padding(padding: const EdgeInsets.only(bottom: 6), child: Row(children: [Expanded(child: Text('${e['actor']} · ${e['action']}', style: TypeX.ui(12.5, color: c.text))), Text(relative(e['at'] as String), style: TypeX.ui(11.5, color: c.text3))]))]));

    return ListView(padding: const EdgeInsets.fromLTRB(24, 16, 24, 28), children: [
      _back(context, 'All users', widget.onBack),
      Row(children: [
        Avatar(name: '${a['name']}', hue: 220, size: 52),
        const SizedBox(width: 14),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Flexible(child: Text('${a['name']}', style: TypeX.display(24, color: c.text), overflow: TextOverflow.ellipsis)),
            if (a['platformAdmin'] == true) const Padding(padding: EdgeInsets.only(left: 10), child: Tag('Platform admin', tone: 'ai')),
            if (a['active'] != true) const Padding(padding: EdgeInsets.only(left: 8), child: Tag('Stopped', tone: 'danger')),
            if (me) const Padding(padding: EdgeInsets.only(left: 8), child: Tag('You', tone: 'accent')),
          ]),
          Text('${a['email']}', style: TypeX.ui(13, color: c.text3)),
        ])),
      ]),
      const Gap(18),
      LayoutBuilder(builder: (context, box) {
        if (box.maxWidth < 860) return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [profile, access, actions, sess, history]);
        return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: Column(children: [profile, actions, sess])),
          const SizedBox(width: 14),
          Expanded(child: Column(children: [access, history])),
        ]);
      }),
    ]);
  }
}

// ====================================================================== dialogs
class NewUserDialog extends StatefulWidget {
  const NewUserDialog({super.key, this.business});
  final String? business;                         // preselected business (from a business page)
  @override
  State<NewUserDialog> createState() => _NewUserDialogState();
}

class _NewUserDialogState extends State<NewUserDialog> {
  final name = TextEditingController();
  final email = TextEditingController();
  late final pw = TextEditingController(text: generatePassword());
  String? business;
  String role = 'agent';
  String? error;
  bool busy = false;

  @override
  void initState() {
    super.initState();
    business = widget.business;
  }

  @override
  void dispose() { name.dispose(); email.dispose(); pw.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    return Dialog(
      backgroundColor: Colors.transparent, insetPadding: const EdgeInsets.all(20),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 480),
        child: Panel(radius: 24, child: Padding(padding: const EdgeInsets.all(24), child: SingleChildScrollView(child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [Expanded(child: Text('New user', style: TypeX.display(21, color: c.text))), DkIconButton(PhosphorIconsBold.x, size: 32, onPressed: () => Navigator.pop(context))]),
          const Gap(6),
          Text('They sign in with this temporary password and choose their own straight away. Share it with them yourself.', style: TypeX.ui(13, color: c.text3, h: 1.45)),
          const Gap(14),
          if (error != null) Container(margin: const EdgeInsets.only(bottom: 12), padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: c.dangerSoft, borderRadius: BorderRadius.circular(12)), child: Text(error!, style: TypeX.ui(13, w: FontWeight.w600, color: c.text))),
          DkField(controller: name, label: 'Name'),
          const Gap(10),
          DkField(controller: email, label: 'Email'),
          const Gap(10),
          Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Expanded(child: DkField(controller: pw, label: 'Temporary password', mono: true)),
            const SizedBox(width: 8),
            DkButton('New', small: true, onPressed: () => setState(() => pw.text = generatePassword())),
          ]),
          const Gap(14),
          Label('Business (optional)'),
          const Gap(6),
          Wrap(spacing: 8, runSpacing: 8, children: [
            _chip(context, 'None', business == null, () => setState(() => business = null)),
            for (final b in s.pBusinesses) _chip(context, '${b['name']}', business == b['slug'], () => setState(() => business = b['slug'] as String)),
          ]),
          if (business != null) ...[
            const Gap(12),
            Label('Role there'),
            const Gap(6),
            Wrap(spacing: 8, children: [for (final r in _roles) _chip(context, _roleName(r), role == r, () => setState(() => role = r))]),
          ],
          const Gap(20),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
            const Gap(8),
            DkButton(busy ? 'Creating…' : 'Create user', kind: BtnKind.primary, onPressed: busy ? null : () async {
              setState(() { busy = true; error = null; });
              final r = await s.createAccount({'name': name.text.trim(), 'email': email.text.trim(), 'password': pw.text, if (business != null) 'business': business, 'role': role});
              if (!context.mounted) return;
              if (r['error'] != null) { setState(() { busy = false; error = r['error'] as String; }); return; }
              Navigator.pop(context);
              s.toast('User created. Temporary password: ${pw.text}');
            }),
          ]),
        ])))),
      ),
    );
  }

  Widget _chip(BuildContext context, String t, bool on, VoidCallback f) {
    final c = context.c;
    return Hover(onTap: f, builder: (_, h, __) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
      decoration: BoxDecoration(color: on ? c.primarySoft : c.surface, borderRadius: BorderRadius.circular(10), border: Border.all(color: on ? c.primary : (h ? c.line2 : c.line))),
      child: Text(t, style: TypeX.ui(12.5, w: FontWeight.w700, color: on ? c.primary : c.text2)),
    ));
  }
}

class ResetPasswordDialog extends StatefulWidget {
  const ResetPasswordDialog({super.key, required this.id, required this.name});
  final String id, name;
  @override
  State<ResetPasswordDialog> createState() => _ResetPasswordDialogState();
}

class _ResetPasswordDialogState extends State<ResetPasswordDialog> {
  late final pw = TextEditingController(text: generatePassword());
  String? error;
  bool busy = false, done = false;
  @override
  void dispose() { pw.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    return Dialog(
      backgroundColor: Colors.transparent, insetPadding: const EdgeInsets.all(20),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 460),
        child: Panel(radius: 24, child: Padding(padding: const EdgeInsets.all(24), child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Reset ${widget.name}’s password', style: TypeX.display(20, color: c.text)),
          const Gap(8),
          Text(done ? 'Done. Share this temporary password with them yourself. They are signed out everywhere and must choose their own at the next sign-in.' : 'They are signed out of every device and must choose their own password at the next sign-in.', style: TypeX.ui(13.5, color: c.text2, h: 1.5)),
          const Gap(14),
          if (error != null) Container(margin: const EdgeInsets.only(bottom: 12), padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: c.dangerSoft, borderRadius: BorderRadius.circular(12)), child: Text(error!, style: TypeX.ui(13, w: FontWeight.w600, color: c.text))),
          Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Expanded(child: DkField(controller: pw, label: 'Temporary password', mono: true)),
            const SizedBox(width: 8),
            if (!done) DkButton('New', small: true, onPressed: () => setState(() => pw.text = generatePassword())),
          ]),
          const Gap(20),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            DkButton(done ? 'Close' : 'Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
            if (!done) ...[
              const Gap(8),
              DkButton(busy ? 'Resetting…' : 'Reset password', kind: BtnKind.primary, onPressed: busy ? null : () async {
                setState(() { busy = true; error = null; });
                final r = await s.resetAccountPassword(widget.id, pw.text);
                if (!context.mounted) return;
                setState(() { busy = false; if (r['error'] != null) { error = r['error'] as String; } else { done = true; } });
              }),
            ],
          ]),
        ]))),
      ),
    );
  }
}
