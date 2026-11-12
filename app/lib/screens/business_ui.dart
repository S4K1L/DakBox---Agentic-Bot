import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../brand/icons.dart';
import '../brand/theme.dart';
import '../core/format.dart';
import '../core/state.dart';
import '../widgets/kit.dart';
import '../widgets/page.dart';
import 'console_ui.dart' show UsageMeter;

/// The business owner's own panel: details, plan and use, who is on the team (managed under Team), and a copy of their data.
class BusinessScreen extends StatefulWidget {
  const BusinessScreen({super.key});
  @override
  State<BusinessScreen> createState() => _BusinessScreenState();
}

class _BusinessScreenState extends State<BusinessScreen> {
  final name = TextEditingController();
  bool filled = false;
  bool busy = false;

  @override
  void initState() {
    super.initState();
    context.read<AppState>().loadBusiness();
  }

  @override
  void dispose() { name.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final b = s.business;
    if (b == null) return Panel(child: Center(child: CircularProgressIndicator(color: c.primary, strokeWidth: 3)));
    if (!filled) { name.text = b['name'] as String; filled = true; }
    final canEdit = b['canEdit'] == true;
    final plan = b['plan'] as Map;
    final seats = b['seats'] as Map, products = b['products'] as Map, ai = b['ai'] as Map;
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        PageHeader(
          title: 'My business',
          subtitle: Text('${b['name']} · you are ${b['yourRole']}. Add and manage your staff under Team.', style: TypeX.ui(13.5, color: c.text3)),
          actions: [if (s.can('team.manage')) DkButton('Manage team', icon: PhosphorIconsRegular.usersThree, kind: BtnKind.primary, onPressed: () => s.setSection(Section.team))],
        ),
        Expanded(
          child: Align(
            alignment: Alignment.topCenter,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 820),
              child: ListView(padding: const EdgeInsets.fromLTRB(24, 6, 24, 28), children: [
                SectionCard('Details', icon: PhosphorIconsRegular.storefront, margin: const EdgeInsets.only(bottom: 14), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                    Expanded(child: DkField(controller: name, label: 'Business name')),
                    const SizedBox(width: 8),
                    if (canEdit) DkButton(busy ? 'Saving…' : 'Save', kind: BtnKind.primary, onPressed: busy ? null : () async {
                      setState(() => busy = true);
                      final r = await s.renameBusiness(name.text.trim());
                      if (!mounted) return;
                      setState(() => busy = false);
                      s.toast(r['error'] != null ? r['error'] as String : 'Saved.', error: r['error'] != null);
                    }),
                  ]),
                  if (!canEdit) Padding(padding: const EdgeInsets.only(top: 8), child: Text('Only an owner can change these details.', style: TypeX.ui(12, color: c.text3))),
                  const Gap(12),
                  Kv('Address name', '${b['slug']}', mono: true),
                  Kv('Status', '${b['status']}'),
                  Kv('Started', shortDate(b['createdAt'] as String?)),
                  Kv('Owner${(b['owners'] as List).length == 1 ? '' : 's'}', (b['owners'] as List).join(', ')),
                ])),
                SectionCard('Plan and use', icon: PhosphorIconsRegular.creditCard, margin: const EdgeInsets.only(bottom: 14), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [Text('${plan['name']} plan', style: TypeX.ui(15, w: FontWeight.w800, color: c.text)), if (plan['platformAi'] == true) const Padding(padding: EdgeInsets.only(left: 8), child: Tag('Platform AI included', tone: 'ai', small: true))]),
                  const Gap(12),
                  Row(children: [
                    UsageMeter('Team members', seats['used'] as int, seats['limit'] as int?), const SizedBox(width: 16),
                    UsageMeter('Products', products['used'] as int, products['limit'] as int?), const SizedBox(width: 16),
                    UsageMeter('AI replies this month', ai['used'] as int, ai['limited'] == true ? ai['limit'] as int? : null),
                  ]),
                  const Gap(12),
                  Text('Need more room? Ask the Dakbox administrator to change your plan.', style: TypeX.ui(12.5, color: c.text3)),
                ])),
                SectionCard('Your team', icon: PhosphorIconsRegular.usersThree, margin: const EdgeInsets.only(bottom: 14), child: Row(children: [
                  Expanded(child: Text('${plural(b['people'] as int, 'person', 'people')} work in ${b['name']}. Owners and admins add staff, choose each person’s role and switch people off under Team.', style: TypeX.ui(13.5, color: c.text2, h: 1.45))),
                  const SizedBox(width: 12),
                  if (s.can('team.manage')) DkButton('Open Team', small: true, onPressed: () => s.setSection(Section.team)),
                ])),
                if (canEdit)
                  SectionCard('Your data', icon: PhosphorIconsRegular.downloadSimple, child: Row(children: [
                    Expanded(child: Text('Download a copy of your products, customers, conversations and orders as spreadsheet files. Stored keys and passwords are never included.', style: TypeX.ui(13.5, color: c.text2, h: 1.45))),
                    const SizedBox(width: 12),
                    DkButton('Download', icon: PhosphorIconsRegular.downloadSimple, small: true, onPressed: () async { final e = await s.exportMyData(); s.toast(e ?? 'Your download is starting.', error: e != null); }),
                  ])),
              ]),
            ),
          ),
        ),
      ]),
    );
  }
}
