import 'package:flutter/material.dart';
import '../brand/icons.dart';
import 'package:provider/provider.dart';
import '../brand/theme.dart';
import '../core/state.dart';
import '../screens/approvals.dart';
import '../screens/assistant.dart';
import '../screens/connections.dart';
import '../screens/customers.dart';
import '../screens/inbox.dart';
import '../screens/insights.dart';
import '../screens/orders.dart';
import '../screens/business_ui.dart';
import '../screens/platform_ui.dart' show ConsoleShell;
import '../screens/setup_ui.dart';
import '../screens/team.dart';
import '../screens/products.dart';
import '../widgets/kit.dart';

IconData sectionIcon(Section s, {bool active = false}) {
  if (active) {
    return switch (s) {
      Section.inbox => PhosphorIconsFill.tray,
      Section.approvals => PhosphorIconsFill.sealCheck,
      Section.orders => PhosphorIconsFill.shoppingBag,
      Section.products => PhosphorIconsFill.package,
      Section.customers => PhosphorIconsFill.users,
      Section.insights => PhosphorIconsFill.chartLineUp,
      Section.connections => PhosphorIconsFill.plugsConnected,
      Section.assistant => PhosphorIconsFill.sparkle,
      Section.team => PhosphorIconsFill.usersThree,
      Section.setup => PhosphorIconsFill.rocketLaunch,
      Section.business => PhosphorIconsFill.storefront,
    };
  }
  return switch (s) {
    Section.inbox => PhosphorIconsRegular.tray,
    Section.approvals => PhosphorIconsRegular.sealCheck,
    Section.orders => PhosphorIconsRegular.shoppingBag,
    Section.products => PhosphorIconsRegular.package,
    Section.customers => PhosphorIconsRegular.users,
    Section.insights => PhosphorIconsRegular.chartLineUp,
    Section.connections => PhosphorIconsRegular.plugsConnected,
    Section.assistant => PhosphorIconsRegular.sparkle,
    Section.team => PhosphorIconsRegular.usersThree,
    Section.setup => PhosphorIconsRegular.rocketLaunch,
    Section.business => PhosphorIconsRegular.storefront,
  };
}

int badgeFor(AppState s, Section sec) => switch (sec) {
      Section.inbox => s.unreadCount,
      Section.approvals => s.pendingApprovals + s.draftsWaiting,
      Section.orders => s.toShip,
      _ => 0,
    };

class Shell extends StatelessWidget {
  const Shell({super.key});
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    return Scaffold(
      backgroundColor: c.bg,
      body: LayoutBuilder(builder: (context, box) {
        final w = box.maxWidth;
        final mode = w >= 1180 ? 2 : (w >= 780 ? 1 : 0); // 2 full, 1 rail, 0 bottom
        final banner = s.isPlatformAdmin ? _SupportBanner(business: '${s.me['business']?['name'] ?? ''}') : null;
        final body = Stack(children: [
          Positioned.fill(child: Padding(padding: EdgeInsets.fromLTRB(mode == 0 ? 0 : 12, mode == 0 ? 0 : 12, mode == 0 ? 0 : 12, mode == 0 ? 0 : 12), child: _Page(section: s.section, compact: mode == 0))),
          Positioned(left: 0, right: 0, bottom: mode == 0 ? 76 : 28, child: Center(child: _Toast(text: s.toastText, error: s.toastError))),
          if (s.offline) const Positioned(top: 0, left: 0, right: 0, child: _OfflineBar()),
        ]);
        if (mode == 0) {
          return Column(children: [if (banner != null) SafeArea(bottom: false, child: banner), Expanded(child: SafeArea(top: banner == null, bottom: false, child: body)), const _BottomNav()]);
        }
        return Row(children: [
          mode == 2 ? const _Sidebar() : const _Rail(),
          Expanded(child: Column(children: [if (banner != null) banner, Expanded(child: body)])),
        ]);
      }),
    );
  }
}

/// Shown only to a super administrator who has opened a business: a reminder of where they are, and the way back.
class _SupportBanner extends StatelessWidget {
  const _SupportBanner({required this.business});
  final String business;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.read<AppState>();
    return Container(
      width: double.infinity, padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      decoration: const BoxDecoration(gradient: LinearGradient(colors: [Color(0xFF2B1B6B), Color(0xFF4A2FB8)])),
      child: Row(children: [
        Icon(PhosphorIconsFill.shieldCheck, size: 16, color: Colors.white.withValues(alpha: .9)),
        const SizedBox(width: 10),
        Expanded(child: Text('Super admin · you are inside $business', style: TypeX.ui(12.5, w: FontWeight.w700, color: Colors.white), maxLines: 1, overflow: TextOverflow.ellipsis)),
        Hover(
          onTap: s.openAdminPanel,
          builder: (_, h, __) => Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
            decoration: BoxDecoration(color: Colors.white.withValues(alpha: h ? .24 : .16), borderRadius: BorderRadius.circular(9)),
            child: Text('Back to super admin panel', style: TypeX.ui(12, w: FontWeight.w800, color: Colors.white)),
          ),
        ),
      ]),
    );
  }
}

class _Page extends StatelessWidget {
  const _Page({required this.section, required this.compact});
  final Section section;
  final bool compact;
  @override
  Widget build(BuildContext context) {
    final Widget page = switch (section) {
      Section.inbox => const InboxScreen(),
      Section.approvals => const ApprovalsScreen(),
      Section.orders => const OrdersScreen(),
      Section.products => const ProductsScreen(),
      Section.customers => const CustomersScreen(),
      Section.insights => const InsightsScreen(),
      Section.connections => const ConnectionsScreen(),
      Section.assistant => const AssistantScreen(),
      Section.team => const TeamScreen(),
      Section.setup => const SetupScreen(),
      Section.business => const BusinessScreen(),
    };
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 220),
      switchInCurve: Curves.easeOutCubic,
      transitionBuilder: (child, anim) => FadeTransition(opacity: anim, child: SlideTransition(position: Tween(begin: const Offset(0, .012), end: Offset.zero).animate(anim), child: child)),
      child: KeyedSubtree(key: ValueKey(section), child: page),
    );
  }
}

// ------------------------------------------------------------------ sidebar
class Brand extends StatelessWidget {
  const Brand({super.key, this.compact = false, this.light = true});
  final bool compact, light;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Row(mainAxisSize: MainAxisSize.min, children: [
      Container(
        width: 38, height: 38, alignment: Alignment.center,
        decoration: BoxDecoration(gradient: c.brand, borderRadius: BorderRadius.circular(12), boxShadow: [BoxShadow(color: DK.violet.withValues(alpha: .45), blurRadius: 16, offset: const Offset(0, 6), spreadRadius: -4)]),
        child: const Icon(PhosphorIconsFill.chatsCircle, color: Colors.white, size: 21),
      ),
      if (!compact) ...[
        const SizedBox(width: 11),
        Text('Dakbox', style: TypeX.display(23, color: light ? Colors.white : c.text, ls: -.035)),
      ],
    ]);
  }
}

class _Sidebar extends StatelessWidget {
  const _Sidebar();
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      width: 248,
      decoration: BoxDecoration(gradient: c.sidebar),
      padding: const EdgeInsets.fromLTRB(14, 20, 14, 14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Padding(padding: EdgeInsets.only(left: 6), child: Brand()),
        const SizedBox(height: 26),
        Padding(padding: const EdgeInsets.only(left: 10, bottom: 8), child: Text('WORKSPACE', style: TypeX.ui(10.5, w: FontWeight.w800, color: c.inkText.withValues(alpha: .6), ls: 1.1))),
        for (final sec in [Section.inbox, Section.approvals, Section.orders, Section.products, Section.customers]) _NavItem(sec: sec),
        if (context.watch<AppState>().showSetup) ...[const SizedBox(height: 6), const _NavItem(sec: Section.setup)],
        const SizedBox(height: 18),
        Padding(padding: const EdgeInsets.only(left: 10, bottom: 8), child: Text('GROW & CONFIGURE', style: TypeX.ui(10.5, w: FontWeight.w800, color: c.inkText.withValues(alpha: .6), ls: 1.1))),
        for (final sec in [Section.insights, Section.connections, Section.assistant, if (context.watch<AppState>().can('team.manage')) ...[Section.team, Section.business]]) _NavItem(sec: sec),
        const Spacer(),
        const _EngineCard(),
        const SizedBox(height: 12),
        const _UserRow(),
      ]),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({required this.sec});
  final Section sec;
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final on = s.section == sec;
    final badge = badgeFor(s, sec);
    final warn = sec == Section.connections && s.channels.any((x) => x['status'] != 'ok');
    return Hover(
      onTap: () => s.setSection(sec),
      builder: (_, h, __) => AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        height: 44, margin: const EdgeInsets.only(bottom: 3),
        padding: const EdgeInsets.symmetric(horizontal: 12),
        decoration: BoxDecoration(
          color: on ? Colors.white.withValues(alpha: .09) : (h ? Colors.white.withValues(alpha: .045) : Colors.white.withValues(alpha: 0)),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(children: [
          Icon(sectionIcon(sec, active: on), size: 20, color: on ? const Color(0xFF9DB0FF) : c.inkText),
          const SizedBox(width: 12),
          Expanded(child: Text(sec.label, style: TypeX.ui(14, w: on ? FontWeight.w700 : FontWeight.w600, color: on ? Colors.white : c.inkText))),
          if (badge > 0)
            Container(
              constraints: const BoxConstraints(minWidth: 22), height: 20, padding: const EdgeInsets.symmetric(horizontal: 6), alignment: Alignment.center,
              decoration: BoxDecoration(gradient: sec == Section.approvals ? c.spark : c.brand, borderRadius: BorderRadius.circular(10)),
              child: Text('$badge', style: TypeX.ui(11, w: FontWeight.w800, color: sec == Section.approvals ? const Color(0xFF3A2200) : Colors.white)),
            )
          else if (warn)
            Container(width: 8, height: 8, decoration: const BoxDecoration(color: DK.saffron, shape: BoxShape.circle)),
        ]),
      ),
    );
  }
}

class _EngineCard extends StatelessWidget {
  const _EngineCard();
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final claude = s.me['engine'] != null && s.me['engine'] != 'offline';
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: Colors.white.withValues(alpha: .06), borderRadius: BorderRadius.circular(14), border: Border.all(color: Colors.white.withValues(alpha: .08))),
      child: Row(children: [
        const AiMark(size: 30),
        const SizedBox(width: 10),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Assistant', style: TypeX.ui(13, w: FontWeight.w700, color: Colors.white)),
            const SizedBox(height: 1),
            Row(children: [
              Container(width: 7, height: 7, decoration: BoxDecoration(color: s.offline ? c.danger : const Color(0xFF3DD598), shape: BoxShape.circle)),
              const SizedBox(width: 6),
              Expanded(child: Text(s.offline ? 'Server offline' : (claude ? '${s.me['engineLabel'] ?? 'AI'} · live' : 'Offline engine'), style: TypeX.ui(11.5, color: c.inkText), maxLines: 1, overflow: TextOverflow.ellipsis)),
            ]),
          ]),
        ),
      ]),
    );
  }
}

class _UserRow extends StatelessWidget {
  const _UserRow();
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final name = (s.me['name'] ?? 'You') as String;
    return Row(children: [
      Expanded(child: UserMenu(dark: true, child: Row(children: [
        Avatar(name: name, hue: (s.me['hue'] ?? 225) as num, size: 38),
        const SizedBox(width: 10),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(name, style: TypeX.ui(13, w: FontWeight.w700, color: Colors.white), maxLines: 1, overflow: TextOverflow.ellipsis),
            Text('${roleLabel(s.role)} · ${s.me['store'] ?? ''}', style: TypeX.ui(11.5, color: c.inkText), maxLines: 1, overflow: TextOverflow.ellipsis),
          ]),
        ),
      ]))),
      Hover(
        onTap: s.toggleTheme,
        builder: (_, h, __) => Container(
          width: 34, height: 34,
          decoration: BoxDecoration(color: h ? Colors.white.withValues(alpha: .1) : Colors.white.withValues(alpha: 0), borderRadius: BorderRadius.circular(10)),
          child: Icon(s.themeMode == ThemeMode.dark ? PhosphorIconsRegular.sun : PhosphorIconsRegular.moon, size: 18, color: c.inkText),
        ),
      ),
    ]);
  }
}

/// Account menu: who you are, change password, sign out.
class UserMenu extends StatelessWidget {
  const UserMenu({super.key, required this.child, this.dark = false, this.below = false});
  final Widget child;
  final bool dark;
  final bool below;                            // open the menu under the button (a top bar) instead of above it (the sidebar)
  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    return PopupMenuButton<String>(
      tooltip: 'Account',
      offset: below ? const Offset(0, 46) : const Offset(0, -260),
      color: c.surface, elevation: 12, shadowColor: Colors.black45,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16), side: BorderSide(color: c.line)),
      onSelected: (v) {
        if (v == 'admin') { s.openAdminPanel(); return; }
        if (v == 'pw') { showDialog<void>(context: context, barrierColor: Colors.black.withValues(alpha: .45), builder: (_) => const _PasswordDialog()); return; }
        if (v == 'out') { s.signOut(); return; }
        if (v.startsWith('biz:')) { s.switchBusiness(v.substring(4)).then((err) { if (err != null) s.toast(err, error: true); }); }
      },
      itemBuilder: (_) => [
        PopupMenuItem<String>(enabled: false, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text((s.me['name'] ?? '') as String, style: TypeX.ui(14, w: FontWeight.w800, color: c.text)),
          Text((s.me['email'] ?? '') as String, style: TypeX.ui(12, color: c.text3)),
          const SizedBox(height: 8),
          Tag(roleLabel(s.role), tone: roleTone(s.role), small: true),
        ])),
        if (s.isPlatformAdmin) ...[
          const PopupMenuDivider(),
          PopupMenuItem<String>(value: 'admin', child: Row(children: [Icon(PhosphorIconsRegular.shieldCheck, size: 18, color: c.primary), const SizedBox(width: 12), Text('Super admin panel', style: TypeX.ui(13.5, w: FontWeight.w700, color: c.primary))])),
        ],
        if (s.businesses.length > 1) ...[
          const PopupMenuDivider(),
          PopupMenuItem<String>(enabled: false, height: 28, child: Text('BUSINESSES', style: TypeX.ui(10.5, w: FontWeight.w800, color: c.text3, ls: .9))),
          for (final b in s.businesses)
            PopupMenuItem<String>(value: 'biz:${b['id']}', child: Row(children: [
              Icon(b['id'] == s.businessId ? PhosphorIconsFill.checkCircle : PhosphorIconsRegular.storefront, size: 18, color: b['id'] == s.businessId ? c.primary : c.text2),
              const SizedBox(width: 12),
              Expanded(child: Text('${b['name']}', maxLines: 1, overflow: TextOverflow.ellipsis, style: TypeX.ui(13.5, w: b['id'] == s.businessId ? FontWeight.w800 : FontWeight.w600, color: c.text))),
              const SizedBox(width: 8),
              Text('${b['role']}', style: TypeX.ui(11.5, color: c.text3)),
            ])),
        ],
        const PopupMenuDivider(),
        PopupMenuItem<String>(value: 'pw', child: Row(children: [Icon(PhosphorIconsRegular.key, size: 18, color: c.text2), const SizedBox(width: 12), Text('Change password', style: TypeX.ui(13.5, w: FontWeight.w600, color: c.text))])),
        PopupMenuItem<String>(value: 'out', child: Row(children: [Icon(PhosphorIconsRegular.signOut, size: 18, color: c.danger), const SizedBox(width: 12), Text('Sign out', style: TypeX.ui(13.5, w: FontWeight.w600, color: c.danger))])),
      ],
      child: child,
    );
  }
}

class _PasswordDialog extends StatefulWidget {
  const _PasswordDialog();
  @override
  State<_PasswordDialog> createState() => _PasswordDialogState();
}

class _PasswordDialogState extends State<_PasswordDialog> {
  final cur = TextEditingController();
  final pw = TextEditingController();
  String? error;
  bool busy = false;
  @override
  void dispose() { cur.dispose(); pw.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    return Dialog(
      backgroundColor: Colors.transparent, insetPadding: const EdgeInsets.all(20),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 440),
        child: Panel(
          radius: 24,
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [Expanded(child: Text('Change password', style: TypeX.display(21, color: c.text))), DkIconButton(PhosphorIconsBold.x, size: 32, onPressed: () => Navigator.pop(context))]),
              const Gap(6),
              Text('Your other signed-in devices will be signed out.', style: TypeX.ui(13, color: c.text3)),
              const Gap(16),
              if (error != null) Container(margin: const EdgeInsets.only(bottom: 14), padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: c.dangerSoft, borderRadius: BorderRadius.circular(12)), child: Text(error!, style: TypeX.ui(13, w: FontWeight.w600, color: c.text))),
              DkField(controller: cur, label: 'Current password', obscure: true),
              const Gap(12),
              DkField(controller: pw, label: 'New password (10+ characters)', obscure: true),
              const Gap(20),
              Row(mainAxisAlignment: MainAxisAlignment.end, children: [
                DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
                const Gap(8),
                DkButton(busy ? 'Saving…' : 'Update password', kind: BtnKind.primary, onPressed: busy ? null : () async {
                  setState(() { busy = true; error = null; });
                  final ok = await s.changePassword(cur.text, pw.text);
                  if (!context.mounted) return;
                  if (ok) { Navigator.pop(context); } else { setState(() { busy = false; error = s.authError; }); }
                }),
              ]),
            ]),
          ),
        ),
      ),
    );
  }
}

// ------------------------------------------------------------------ rail (tablet) & bottom bar (phone)
class _Rail extends StatelessWidget {
  const _Rail();
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    return Container(
      width: 76, decoration: BoxDecoration(gradient: c.sidebar), padding: const EdgeInsets.symmetric(vertical: 18),
      child: Column(children: [
        const Brand(compact: true),
        const SizedBox(height: 22),
        for (final sec in Section.values.where((x) => ((x != Section.team && x != Section.business) || s.can('team.manage')) && (x != Section.setup || s.showSetup)))
          Tooltip(
            message: sec.label,
            child: Hover(
              onTap: () => s.setSection(sec),
              builder: (_, h, __) {
                final on = s.section == sec;
                final b = badgeFor(s, sec);
                return Container(
                  width: 48, height: 46, margin: const EdgeInsets.only(bottom: 4),
                  decoration: BoxDecoration(color: on ? Colors.white.withValues(alpha: .1) : (h ? Colors.white.withValues(alpha: .05) : Colors.white.withValues(alpha: 0)), borderRadius: BorderRadius.circular(13)),
                  child: Stack(alignment: Alignment.center, children: [
                    Icon(sectionIcon(sec, active: on), size: 22, color: on ? const Color(0xFF9DB0FF) : c.inkText),
                    if (b > 0) Positioned(top: 6, right: 6, child: Container(width: 9, height: 9, decoration: BoxDecoration(color: sec == Section.approvals ? DK.saffron : c.primary, shape: BoxShape.circle, border: Border.all(color: c.ink, width: 1.5)))),
                  ]),
                );
              },
            ),
          ),
        const Spacer(),
        DkIconButton(s.themeMode == ThemeMode.dark ? PhosphorIconsRegular.sun : PhosphorIconsRegular.moon, onPressed: s.toggleTheme),
        const SizedBox(height: 8),
        UserMenu(child: Avatar(name: (s.me['name'] ?? 'You') as String, hue: (s.me['hue'] ?? 225) as num, size: 36)),
      ]),
    );
  }
}

class _BottomNav extends StatelessWidget {
  const _BottomNav();
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    const main = [Section.inbox, Section.approvals, Section.orders];
    final moreOn = !main.contains(s.section);
    return Container(
      decoration: BoxDecoration(color: c.surface, border: Border(top: BorderSide(color: c.line)), boxShadow: c.shadow),
      child: SafeArea(
        top: false,
        child: SizedBox(
          height: 64,
          child: Row(children: [
            for (final sec in main) Expanded(child: _BottomItem(icon: sectionIcon(sec, active: s.section == sec), label: sec.label, on: s.section == sec, badge: badgeFor(s, sec), onTap: () => s.setSection(sec))),
            Expanded(child: _BottomItem(icon: moreOn ? sectionIcon(s.section, active: true) : PhosphorIconsRegular.squaresFour, label: moreOn ? s.section.label : 'More', on: moreOn, badge: 0, onTap: () => _more(context))),
          ]),
        ),
      ),
    );
  }

  void _more(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    showModalBottomSheet<void>(
      context: context, backgroundColor: c.surface, showDragHandle: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
          child: Wrap(spacing: 10, runSpacing: 10, children: [
            for (final sec in [if (s.showSetup) Section.setup, Section.products, Section.customers, Section.insights, Section.connections, Section.assistant, if (s.can('team.manage')) ...[Section.team, Section.business]])
              Hover(
                onTap: () { Navigator.pop(ctx); s.setSection(sec); },
                builder: (_, h, __) => Container(
                  width: (MediaQuery.of(ctx).size.width - 32 - 20) / 3, padding: const EdgeInsets.symmetric(vertical: 16),
                  decoration: BoxDecoration(color: c.sunken, borderRadius: BorderRadius.circular(16)),
                  child: Column(children: [Icon(sectionIcon(sec), size: 24, color: c.primary), const SizedBox(height: 8), Text(sec.label, style: TypeX.ui(12.5, w: FontWeight.w700, color: c.text))]),
                ),
              ),
            SizedBox(
              width: MediaQuery.of(ctx).size.width - 32,
              child: Container(
                padding: const EdgeInsets.all(14), margin: const EdgeInsets.only(top: 6),
                decoration: BoxDecoration(color: c.sunken, borderRadius: BorderRadius.circular(16)),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    Avatar(name: (s.me['name'] ?? 'You') as String, hue: (s.me['hue'] ?? 225) as num, size: 40),
                    const SizedBox(width: 12),
                    Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text((s.me['name'] ?? '') as String, style: TypeX.ui(14, w: FontWeight.w800, color: c.text)), Text((s.me['email'] ?? '') as String, style: TypeX.ui(12, color: c.text3), overflow: TextOverflow.ellipsis)])),
                    Tag(roleLabel(s.role), tone: roleTone(s.role), small: true),
                  ]),
                  const SizedBox(height: 12),
                  Row(children: [
                    Expanded(child: DkButton('Change password', small: true, expand: true, onPressed: () { Navigator.pop(ctx); showDialog<void>(context: context, barrierColor: Colors.black.withValues(alpha: .45), builder: (_) => const _PasswordDialog()); })),
                    const SizedBox(width: 8),
                    Expanded(child: DkButton('Sign out', kind: BtnKind.danger, small: true, expand: true, onPressed: () { Navigator.pop(ctx); s.signOut(); })),
                  ]),
                ]),
              ),
            ),
            Hover(
              onTap: () { Navigator.pop(ctx); s.toggleTheme(); },
              builder: (_, h, __) => Container(
                width: (MediaQuery.of(ctx).size.width - 32 - 20) / 3, padding: const EdgeInsets.symmetric(vertical: 16),
                decoration: BoxDecoration(color: c.sunken, borderRadius: BorderRadius.circular(16)),
                child: Column(children: [Icon(c.isDark ? PhosphorIconsRegular.sun : PhosphorIconsRegular.moon, size: 24, color: c.primary), const SizedBox(height: 8), Text(c.isDark ? 'Light' : 'Dark', style: TypeX.ui(12.5, w: FontWeight.w700, color: c.text))]),
              ),
            ),
          ]),
        ),
      ),
    );
  }
}

class _BottomItem extends StatelessWidget {
  const _BottomItem({required this.icon, required this.label, required this.on, required this.badge, required this.onTap});
  final IconData icon;
  final String label;
  final bool on;
  final int badge;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Hover(
      onTap: onTap,
      builder: (_, __, ___) => Column(mainAxisAlignment: MainAxisAlignment.center, children: [
        Stack(clipBehavior: Clip.none, children: [
          AnimatedContainer(
            duration: const Duration(milliseconds: 180), width: 52, height: 30, alignment: Alignment.center,
            decoration: BoxDecoration(color: on ? c.primarySoft : c.primarySoft.withValues(alpha: 0), borderRadius: BorderRadius.circular(15)),
            child: Icon(icon, size: 22, color: on ? c.primary : c.text3),
          ),
          if (badge > 0) Positioned(top: -2, right: 2, child: Container(constraints: const BoxConstraints(minWidth: 17), height: 17, padding: const EdgeInsets.symmetric(horizontal: 4), alignment: Alignment.center, decoration: BoxDecoration(color: c.danger, borderRadius: BorderRadius.circular(9), border: Border.all(color: c.surface, width: 2)), child: Text('$badge', style: TypeX.ui(9.5, w: FontWeight.w800, color: Colors.white)))),
        ]),
        const SizedBox(height: 3),
        Text(label, style: TypeX.ui(11, w: on ? FontWeight.w800 : FontWeight.w600, color: on ? c.primary : c.text3)),
      ]),
    );
  }
}

// ------------------------------------------------------------------ toast + offline
class _Toast extends StatelessWidget {
  const _Toast({required this.text, required this.error});
  final String? text;
  final bool error;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return IgnorePointer(
      child: AnimatedSlide(
        duration: const Duration(milliseconds: 260), curve: Curves.easeOutCubic,
        offset: text == null ? const Offset(0, .6) : Offset.zero,
        child: AnimatedOpacity(
          duration: const Duration(milliseconds: 200), opacity: text == null ? 0 : 1,
          child: Container(
            constraints: const BoxConstraints(maxWidth: 520),
            margin: const EdgeInsets.symmetric(horizontal: 16),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            decoration: BoxDecoration(color: c.isDark ? c.surface2 : c.ink, borderRadius: BorderRadius.circular(14), boxShadow: c.lift, border: c.isDark ? Border.all(color: c.line2) : null),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Container(width: 22, height: 22, decoration: BoxDecoration(color: error ? c.danger : const Color(0xFF2BD38C), shape: BoxShape.circle), child: Icon(error ? PhosphorIconsBold.x : PhosphorIconsBold.check, size: 13, color: Colors.white)),
              const SizedBox(width: 12),
              Flexible(child: Text(text ?? '', style: TypeX.ui(13.5, w: FontWeight.w600, color: Colors.white))),
            ]),
          ),
        ),
      ),
    );
  }
}

class _OfflineBar extends StatelessWidget {
  const _OfflineBar();
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 8), color: c.danger, alignment: Alignment.center,
      child: Text('Cannot reach the Dakbox server. Retrying…', style: TypeX.ui(12.5, w: FontWeight.w700, color: Colors.white)),
    );
  }
}
