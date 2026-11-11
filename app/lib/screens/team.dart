import 'dart:math';
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

const _permNames = {
  'conv.reply': 'Reply to customers',
  'draft.approve': 'Approve assistant drafts',
  'approvals.decide': 'Decide returns and refunds',
  'orders.manage': 'Manage orders and shipping',
  'orders.refund': 'Issue refunds',
  'products.stock': 'Adjust stock',
  'products.manage': 'Add, edit and remove products',
  'settings.write': 'Change assistant settings',
  'connections.write': 'Change connections',
  'team.manage': 'Manage the team',
  'audit.read': 'See the activity log',
  'simulate': 'Simulate customer messages',
};

String roleLabel(String r) => switch (r) { 'owner' => 'Owner', 'admin' => 'Admin', 'agent' => 'Agent', _ => 'Viewer' };
String roleTone(String r) => switch (r) { 'owner' => 'ai', 'admin' => 'accent', 'agent' => 'ok', _ => '' };

String generatePassword() {
  const chars = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  final r = Random.secure();
  return List.generate(14, (_) => chars[r.nextInt(chars.length)]).join();
}

class TeamScreen extends StatefulWidget {
  const TeamScreen({super.key});
  @override
  State<TeamScreen> createState() => _TeamScreenState();
}

class _TeamScreenState extends State<TeamScreen> {
  @override
  void initState() {
    super.initState();
    context.read<AppState>().loadTeam();
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final me = s.user['id'];
    final members = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (var i = 0; i < s.team.length; i++) Reveal(delay: i * 40, child: _Member(m: s.team[i], isMe: s.team[i]['id'] == me)),
    ]);
    final side = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [const _RoleGuide(), const Gap(16), const _Activity()]);
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        PageHeader(
          title: 'Team',
          subtitle: Text('${plural(s.team.length, 'person', 'people')} · you decide who can reply, approve money and change settings.', style: TypeX.ui(13.5, color: c.text3)),
          actions: [DkButton('Invite someone', icon: PhosphorIconsBold.userPlus, kind: BtnKind.primary, onPressed: () => showDialog<void>(context: context, barrierColor: Colors.black.withValues(alpha: .45), builder: (_) => const _InviteDialog()))],
        ),
        Expanded(
          child: s.team.isEmpty
              ? Center(child: CircularProgressIndicator(color: c.primary, strokeWidth: 3))
              : LayoutBuilder(builder: (context, box) {
                  if (box.maxWidth >= 1100) {
                    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Expanded(child: ListView(padding: const EdgeInsets.fromLTRB(24, 6, 12, 24), children: [members])),
                      SizedBox(width: 380, child: ListView(padding: const EdgeInsets.fromLTRB(12, 6, 24, 24), children: [side])),
                    ]);
                  }
                  return ListView(padding: const EdgeInsets.fromLTRB(20, 6, 20, 24), children: [members, const Gap(20), side]);
                }),
        ),
      ]),
    );
  }
}

class _Member extends StatelessWidget {
  const _Member({required this.m, required this.isMe});
  final J m;
  final bool isMe;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.read<AppState>();
    final active = m['active'] == true;
    final role = m['role'] as String;
    final locked = role == 'owner' && s.role != 'owner'; // admins cannot touch owners
    return Container(
      margin: const EdgeInsets.only(bottom: 10), padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(16), border: Border.all(color: c.line)),
      child: Opacity(
        opacity: active ? 1 : .55,
        child: Row(children: [
          Avatar(name: m['name'] as String, hue: m['hue'] as num, size: 46),
          const SizedBox(width: 14),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                Text(m['name'] as String, style: TypeX.ui(14.5, w: FontWeight.w800, color: c.text)),
                if (isMe) const Tag('You', small: true),
                Tag(roleLabel(role), tone: roleTone(role), small: true),
                if (!active) const Tag('Deactivated', tone: 'danger', small: true) else if (m['mustChange'] == true) const Tag('Has not set a password yet', tone: 'warn', small: true),
              ]),
              const SizedBox(height: 3),
              Text(m['email'] as String, style: TypeX.ui(12.5, color: c.text3), maxLines: 1, overflow: TextOverflow.ellipsis),
              const SizedBox(height: 2),
              Text(m['lastLoginAt'] == null ? 'Never signed in' : 'Last signed in ${relative(m['lastLoginAt'] as String?)}', style: TypeX.ui(12, color: c.text3)),
            ]),
          ),
          const SizedBox(width: 8),
          DkButton(locked ? 'Owner' : 'Manage', small: true, onPressed: locked ? null : () => showDialog<void>(context: context, barrierColor: Colors.black.withValues(alpha: .45), builder: (_) => _EditDialog(m: m, isMe: isMe))),
        ]),
      ),
    );
  }
}

class _RoleGuide extends StatelessWidget {
  const _RoleGuide();
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(18), border: Border.all(color: c.line)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('What each role can do', style: TypeX.display(17, color: c.text)),
        const Gap(14),
        for (final r in s.roleGuide)
          Padding(
            padding: const EdgeInsets.only(bottom: 14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Tag(roleLabel(r['role'] as String), tone: roleTone(r['role'] as String), small: true),
              const Gap(6),
              Text(r['blurb'] as String, style: TypeX.ui(12.5, color: c.text2, h: 1.45)),
              if ((r['role'] == 'agent') || (r['role'] == 'viewer' && false)) ...[
                const Gap(8),
                Wrap(spacing: 5, runSpacing: 5, children: [for (final p in (r['permissions'] as List).cast<String>()) Tag(_permNames[p] ?? p, small: true)]),
              ],
            ]),
          ),
        Text('Every approval, refund, settings change and sign-in is written to the activity log.', style: TypeX.ui(12, color: c.text3, h: 1.45)),
      ]),
    );
  }
}

class _Activity extends StatelessWidget {
  const _Activity();
  static String text(J a) {
    final t = a['target'] ?? '';
    final d = a['detail'];
    return switch (a['action']) {
      'login' => 'signed in',
      'login.fail' => 'failed sign-in for $t',
      'workspace.setup' => 'created the workspace',
      'password.change' => 'changed their password',
      'team.add' => 'added $t as ${d ?? ''}',
      'team.role' => 'changed $t: $d',
      'team.deactivate' => 'deactivated $t',
      'team.activate' => 'reactivated $t',
      'team.reset_password' => 'reset the password for $t',
      'approval.approved' => 'approved $t${d != null && d != '0' ? ' (৳$d)' : ''}',
      'approval.rejected' => 'rejected $t',
      'order.refund' => 'refunded order $t ($d)',
      'order.cancel' => 'cancelled order $t',
      'settings.update' => 'changed assistant settings: $d',
      'policy.update' => 'edited the $t policy',
      'integration.connect' => 'connected $t',
      'integration.disconnect' => 'disconnected $t',
      _ => '${a['action']} $t',
    };
  }

  static IconData icon(String action) {
    if (action.startsWith('login')) return action == 'login.fail' ? PhosphorIconsRegular.warningCircle : PhosphorIconsRegular.signIn;
    if (action.startsWith('team') || action.startsWith('workspace') || action.startsWith('password')) return PhosphorIconsRegular.users;
    if (action.startsWith('approval') || action.startsWith('order')) return PhosphorIconsRegular.sealCheck;
    return PhosphorIconsRegular.sliders;
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(18), border: Border.all(color: c.line)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Recent activity', style: TypeX.display(17, color: c.text)),
        const Gap(12),
        if (s.audit.isEmpty) Text('Nothing yet.', style: TypeX.ui(13, color: c.text3)),
        for (final a in s.audit.take(14))
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Container(width: 28, height: 28, decoration: BoxDecoration(color: a['action'] == 'login.fail' ? c.dangerSoft : c.sunken, borderRadius: BorderRadius.circular(8)), child: Icon(icon(a['action'] as String), size: 15, color: a['action'] == 'login.fail' ? c.danger : c.text2)),
              const SizedBox(width: 10),
              Expanded(child: Text.rich(TextSpan(children: [TextSpan(text: '${a['actor']} ', style: TypeX.ui(12.5, w: FontWeight.w800, color: c.text)), TextSpan(text: text(a), style: TypeX.ui(12.5, color: c.text2))]))),
              const SizedBox(width: 8),
              Text(relative(a['at'] as String?), style: TypeX.ui(11, color: c.text3)),
            ]),
          ),
      ]),
    );
  }
}

// ------------------------------------------------------------------ dialogs
class _DialogShell extends StatelessWidget {
  const _DialogShell({required this.title, required this.children});
  final String title;
  final List<Widget> children;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Dialog(
      backgroundColor: Colors.transparent, insetPadding: const EdgeInsets.all(20),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520, maxHeight: 720),
        child: Panel(
          radius: 24,
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [Expanded(child: Text(title, style: TypeX.display(21, color: c.text))), DkIconButton(PhosphorIconsBold.x, size: 32, onPressed: () => Navigator.pop(context))]),
              const Gap(16),
              ...children,
            ]),
          ),
        ),
      ),
    );
  }
}

class _PwField extends StatelessWidget {
  const _PwField({required this.controller, required this.label});
  final TextEditingController controller;
  final String label;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [Expanded(child: Text(label, style: TypeX.ui(12.5, w: FontWeight.w700, color: c.text2))), Hover(onTap: () => controller.text = generatePassword(), builder: (_, h, __) => Text('Generate', style: TypeX.ui(12.5, w: FontWeight.w800, color: h ? c.primaryHover : c.primary)))]),
      const SizedBox(height: 6),
      Row(children: [
        Expanded(child: DkField(controller: controller, mono: true, hint: 'At least 10 characters')),
        const SizedBox(width: 8),
        DkIconButton(PhosphorIconsRegular.copy, tooltip: 'Copy', onPressed: () { Clipboard.setData(ClipboardData(text: controller.text)); context.read<AppState>().toast('Copied. Share it privately'); }),
      ]),
    ]);
  }
}

class _RolePicker extends StatelessWidget {
  const _RolePicker({required this.value, required this.onChanged, required this.canOwner});
  final String value;
  final ValueChanged<String> onChanged;
  final bool canOwner;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.watch<AppState>();
    final blurb = (s.roleGuide.firstWhere((r) => r['role'] == value, orElse: () => {'blurb': ''})['blurb']) as String;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Role', style: TypeX.ui(12.5, w: FontWeight.w700, color: c.text2)),
      const SizedBox(height: 6),
      SingleChildScrollView(scrollDirection: Axis.horizontal, child: Seg<String>(items: [if (canOwner) ('owner', 'Owner'), ('admin', 'Admin'), ('agent', 'Agent'), ('viewer', 'Viewer')], value: value, onChanged: onChanged)),
      const SizedBox(height: 8),
      Text(blurb, style: TypeX.ui(12.5, color: c.text3, h: 1.45)),
    ]);
  }
}

class _InviteDialog extends StatefulWidget {
  const _InviteDialog();
  @override
  State<_InviteDialog> createState() => _InviteDialogState();
}

class _InviteDialogState extends State<_InviteDialog> {
  final name = TextEditingController();
  final email = TextEditingController();
  final pw = TextEditingController(text: generatePassword());
  String role = 'agent';
  String? error;
  bool busy = false;
  @override
  void dispose() { name.dispose(); email.dispose(); pw.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    return _DialogShell(title: 'Invite someone', children: [
      if (error != null) Container(margin: const EdgeInsets.only(bottom: 14), padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: c.dangerSoft, borderRadius: BorderRadius.circular(12)), child: Text(error!, style: TypeX.ui(13, w: FontWeight.w600, color: c.text))),
      DkField(controller: name, label: 'Name'),
      const Gap(12),
      DkField(controller: email, label: 'Email'),
      const Gap(16),
      _RolePicker(value: role, onChanged: (v) => setState(() => role = v), canOwner: s.canGrantOwner),
      const Gap(16),
      _PwField(controller: pw, label: 'Temporary password'),
      const Gap(6),
      Text('Share it with them privately. They will be asked to choose their own password the first time they sign in.', style: TypeX.ui(12.5, color: c.text3, h: 1.45)),
      const Gap(22),
      Row(mainAxisAlignment: MainAxisAlignment.end, children: [
        DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
        const Gap(8),
        DkButton(busy ? 'Adding…' : 'Add to team', icon: PhosphorIconsBold.userPlus, kind: BtnKind.primary, onPressed: busy ? null : () async {
          setState(() { busy = true; error = null; });
          final e = await s.invite(name.text.trim(), email.text.trim(), role, pw.text);
          if (!context.mounted) return;
          if (e == null) { Navigator.pop(context); } else { setState(() { busy = false; error = e; }); }
        }),
      ]),
    ]);
  }
}

class _EditDialog extends StatefulWidget {
  const _EditDialog({required this.m, required this.isMe});
  final J m;
  final bool isMe;
  @override
  State<_EditDialog> createState() => _EditDialogState();
}

class _EditDialogState extends State<_EditDialog> {
  late final name = TextEditingController(text: widget.m['name'] as String);
  final pw = TextEditingController(text: generatePassword());
  late String role = widget.m['role'] as String;
  late bool active = widget.m['active'] == true;
  String? error;
  bool busy = false;
  @override
  void dispose() { name.dispose(); pw.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final s = context.read<AppState>();
    final c = context.c;
    final m = widget.m;
    return _DialogShell(title: m['name'] as String, children: [
      if (error != null) Container(margin: const EdgeInsets.only(bottom: 14), padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: c.dangerSoft, borderRadius: BorderRadius.circular(12)), child: Text(error!, style: TypeX.ui(13, w: FontWeight.w600, color: c.text))),
      Text(m['email'] as String, style: TypeX.ui(13, color: c.text3)),
      const Gap(14),
      DkField(controller: name, label: 'Name'),
      const Gap(16),
      _RolePicker(value: role, onChanged: (v) => setState(() => role = v), canOwner: s.canGrantOwner || role == 'owner'),
      const Gap(16),
      Row(children: [
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('Can sign in', style: TypeX.ui(14, w: FontWeight.w700, color: c.text)), Text(widget.isMe ? 'You cannot deactivate your own account.' : 'Turn off to lock them out immediately.', style: TypeX.ui(12.5, color: c.text3))])),
        DkSwitch(value: active, onChanged: widget.isMe ? null : (v) => setState(() => active = v)),
      ]),
      const Gap(20),
      Row(mainAxisAlignment: MainAxisAlignment.end, children: [
        DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
        const Gap(8),
        DkButton(busy ? 'Saving…' : 'Save changes', icon: PhosphorIconsBold.check, kind: BtnKind.primary, onPressed: busy ? null : () async {
          setState(() { busy = true; error = null; });
          final patch = <String, dynamic>{};
          if (name.text.trim() != m['name']) patch['name'] = name.text.trim();
          if (role != m['role']) patch['role'] = role;
          if (active != (m['active'] == true)) patch['active'] = active;
          final e = patch.isEmpty ? null : await s.updateMember(m['id'] as String, patch);
          if (!context.mounted) return;
          if (e == null) { Navigator.pop(context); } else { setState(() { busy = false; error = e; }); }
        }),
      ]),
      const Gap(22),
      const Rule(),
      const Gap(18),
      Text('Reset password', style: TypeX.display(16, color: c.text)),
      const Gap(4),
      Text('Signs them out everywhere and asks them to choose a new password.', style: TypeX.ui(12.5, color: c.text3)),
      const Gap(12),
      _PwField(controller: pw, label: 'New temporary password'),
      const Gap(12),
      Align(
        alignment: Alignment.centerLeft,
        child: DkButton('Reset password', icon: PhosphorIconsRegular.key, onPressed: busy ? null : () async {
          setState(() { busy = true; error = null; });
          final e = await s.resetMemberPassword(m['id'] as String, pw.text);
          if (!context.mounted) return;
          if (e == null) { Navigator.pop(context); } else { setState(() { busy = false; error = e; }); }
        }),
      ),
    ]);
  }
}
