import 'package:flutter/material.dart';
import '../brand/icons.dart';
import 'package:provider/provider.dart';
import '../brand/theme.dart';
import '../core/api.dart';
import '../core/format.dart';
import '../core/state.dart';
import '../widgets/kit.dart';
import '../widgets/page.dart';
import 'inbox.dart' show bubbleStyle;

class ApprovalsScreen extends StatelessWidget {
  const ApprovalsScreen({super.key});
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final sel = s.approvals.where((a) => a['id'] == s.apprId).toList();
    return MasterDetail(
      hasSelection: sel.isNotEmpty,
      onBack: () => s.selectApproval(null),
      detailWidth: 440,
      master: Panel(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          PageHeader(
            title: 'Approvals',
            subtitle: Text('Requests the assistant cannot decide. Oldest deadline first.', style: TypeX.ui(13.5, color: c.text3)),
            actions: [Seg<String>(items: const [('pending', 'Pending'), ('decided', 'Decided')], value: s.apprStatus, onChanged: s.setApprStatus)],
          ),
          if (s.apprStatus == 'pending' && s.approvals.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 14),
              child: Row(children: [
                StatTile(value: '${s.approvals.length}', label: 'Waiting for you', icon: PhosphorIconsRegular.sealCheck, tone: 'warn'),
                const SizedBox(width: 8),
                StatTile(value: '${s.approvals.where((a) => due(a['dueAt'] as String?).tone == 'danger').length}', label: 'Overdue', icon: PhosphorIconsRegular.timer, tone: 'danger'),
                const SizedBox(width: 8),
                StatTile(value: taka(s.approvals.fold<num>(0, (t, a) => t + (a['amount'] as num))), label: 'Value at stake', icon: PhosphorIconsRegular.coins),
              ]),
            ),
          if (s.draftsWaiting > 0 && s.apprStatus == 'pending')
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 14),
              child: Hover(
                onTap: () { s.setConvTab('needs'); s.setSection(Section.inbox); },
                builder: (_, h, __) => Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(gradient: LinearGradient(colors: [c.primarySoft, c.isDark ? c.surface2 : const Color(0xFFF4EFFF)]), borderRadius: BorderRadius.circular(14), border: Border.all(color: h ? c.primary : c.primaryLine)),
                  child: Row(children: [
                    const AiMark(size: 30), const SizedBox(width: 12),
                    Expanded(child: Text('${plural(s.draftsWaiting, 'reply draft')} waiting in Review mode', style: TypeX.ui(13.5, w: FontWeight.w700, color: c.text))),
                    Icon(PhosphorIconsBold.arrowRight, size: 16, color: c.primary),
                  ]),
                ),
              ),
            ),
          Expanded(
            child: s.approvals.isEmpty
                ? Empty(s.apprStatus == 'pending' ? 'All caught up' : 'Nothing decided yet', body: s.apprStatus == 'pending' ? 'Returns, exchanges and price matches the assistant escalates will show up here.' : null, icon: PhosphorIconsDuotone.sealCheck)
                : ListView.builder(
                    padding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
                    itemCount: s.approvals.length,
                    itemBuilder: (_, i) => Reveal(delay: i * 40, child: _ApprovalRow(a: s.approvals[i], selected: s.apprId == s.approvals[i]['id'])),
                  ),
          ),
        ]),
      ),
      detail: sel.isEmpty
          ? const Panel(child: Empty('Select a request', body: 'The customer’s words, the order and the policy appear here.', icon: PhosphorIconsDuotone.sealCheck))
          : _Detail(a: sel.first),
    );
  }
}

class _ApprovalRow extends StatelessWidget {
  const _ApprovalRow({required this.a, required this.selected});
  final J a;
  final bool selected;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.read<AppState>();
    final cust = a['customer'] as J;
    final pending = a['status'] == 'pending';
    final d = due(a['dueAt'] as String?);
    final amount = a['amount'] as num;
    final type = a['type'] as String;
    final tone = type == 'Return' ? 'danger' : (type == 'Exchange' ? 'accent' : 'ai');
    final accent = !pending ? (a['status'] == 'approved' ? c.ok : c.text3) : (d.tone == 'danger' ? c.danger : (d.tone == 'warn' ? c.warn : c.primary));
    return Hover(
      onTap: () => s.selectApproval(a['id'] as int),
      builder: (_, h, __) => AnimatedContainer(
        duration: const Duration(milliseconds: 140), margin: const EdgeInsets.only(bottom: 8), clipBehavior: Clip.antiAlias,
        decoration: BoxDecoration(color: selected ? c.primarySoft : (h ? c.surface2 : c.surface), borderRadius: BorderRadius.circular(16), border: Border.all(color: selected ? c.primary : (h ? c.line2 : c.line), width: selected ? 1.4 : 1)),
        child: IntrinsicHeight(
          child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Container(width: 4, color: accent),
            Expanded(child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 13, 14, 13),
              child: Row(children: [
                Avatar(name: cust['name'] as String, hue: cust['hue'] as num, size: 44, channel: a['channel'] as String?),
                const SizedBox(width: 12),
                Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    Flexible(child: Text(cust['name'] as String, style: TypeX.ui(14.5, w: FontWeight.w800, color: c.text), maxLines: 1, overflow: TextOverflow.ellipsis)),
                    const SizedBox(width: 8),
                    Tag(type, tone: tone, small: true),
                  ]),
                  const SizedBox(height: 4),
                  Text('${a['reason'] ?? ''}', style: TypeX.ui(13, color: c.text2, h: 1.35), maxLines: 2, overflow: TextOverflow.ellipsis),
                  const SizedBox(height: 4),
                  Text('${a['order']} · ${a['item']}', style: TypeX.ui(12, color: c.text3), maxLines: 1, overflow: TextOverflow.ellipsis),
                ])),
                const SizedBox(width: 10),
                Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                  Text(amount > 0 ? taka(amount) : '—', style: TypeX.display(16, color: c.text, ls: 0)),
                  const SizedBox(height: 7),
                  if (pending) Tag(d.text, tone: d.tone, icon: PhosphorIconsBold.clock, small: true) else Tag(a['status'] == 'approved' ? 'Approved' : 'Rejected', tone: a['status'] == 'approved' ? 'ok' : 'danger', small: true),
                ]),
              ]),
            )),
          ]),
        ),
      ),
    );
  }
}

class _Detail extends StatelessWidget {
  const _Detail({required this.a});
  final J a;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.read<AppState>();
    final cust = a['customer'] as J;
    final said = a['said'] as String? ?? '';
    final tr = a['saidTr'] as String?;
    final pending = a['status'] == 'pending';
    final amount = a['amount'] as num;
    final isPrice = a['type'] == 'Price match';
    final phone = SinglePane.of(context);
    return Panel(
      child: Column(children: [
        Container(
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 16), decoration: BoxDecoration(border: Border(bottom: BorderSide(color: c.line))),
          child: Row(children: [
            if (phone) ...[DkIconButton(PhosphorIconsBold.arrowLeft, onPressed: () => s.selectApproval(null)), const SizedBox(width: 6)],
            Avatar(name: cust['name'] as String, hue: cust['hue'] as num, size: 46, channel: a['channel'] as String?),
            const SizedBox(width: 14),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${a['type']} request', style: TypeX.display(19, color: c.text)),
              const SizedBox(height: 3),
              Text('${cust['name']} · ${a['order']}', style: TypeX.ui(12.5, color: c.text3), maxLines: 1, overflow: TextOverflow.ellipsis),
            ])),
            if (pending) Tag(due(a['dueAt'] as String?).text, tone: due(a['dueAt'] as String?).tone, icon: PhosphorIconsBold.clock),
          ]),
        ),
        Expanded(
          child: Container(
            color: c.surface2,
            child: ListView(padding: const EdgeInsets.all(16), children: [
            SectionCard('Customer said', icon: PhosphorIconsRegular.chatText, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Container(padding: const EdgeInsets.fromLTRB(14, 10, 14, 10), decoration: BoxDecoration(color: c.surface2, borderRadius: const BorderRadius.only(topLeft: Radius.circular(5), topRight: Radius.circular(16), bottomLeft: Radius.circular(16), bottomRight: Radius.circular(16)), border: Border.all(color: c.line)), child: SelectableText(said, style: bubbleStyle(said, c.text))),
              if (tr != null) Padding(padding: const EdgeInsets.only(top: 8), child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Padding(padding: const EdgeInsets.only(top: 2), child: Icon(PhosphorIconsRegular.translate, size: 13, color: c.text3)), const SizedBox(width: 6), Expanded(child: Text(tr, style: TypeX.ui(12.5, color: c.text3)))])),
              if (a['attachment'] != null) Padding(padding: const EdgeInsets.only(top: 12), child: Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9), decoration: BoxDecoration(color: c.sunken, borderRadius: BorderRadius.circular(10)), child: Row(mainAxisSize: MainAxisSize.min, children: [Icon(PhosphorIconsRegular.paperclip, size: 16, color: c.text2), const SizedBox(width: 8), Text(a['attachment'] as String, style: TypeX.ui(12.5, w: FontWeight.w600, color: c.text2))]))),
            ])),
            SectionCard('Item', icon: PhosphorIconsRegular.package, child: Row(children: [
              Container(width: 40, height: 40, decoration: BoxDecoration(color: c.sunken, borderRadius: BorderRadius.circular(11)), child: Icon(PhosphorIconsRegular.package, size: 20, color: c.text2)),
              const SizedBox(width: 12),
              Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(a['item'] as String, style: TypeX.ui(14, w: FontWeight.w700, color: c.text)), Text('Order ${a['order']}', style: TypeX.ui(12.5, color: c.text3))])),
              Text(amount > 0 ? taka(amount) : '—', style: TypeX.mono(14, w: FontWeight.w700, color: c.text)),
            ])),
            SectionCard('Policy the assistant found', icon: PhosphorIconsFill.bookOpenText, child: Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(color: c.primarySoft, borderRadius: BorderRadius.circular(14), border: Border.all(color: c.primaryLine)),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [Icon(PhosphorIconsFill.bookOpenText, size: 14, color: c.primary), const SizedBox(width: 6), Text('CITED FROM STORE POLICY', style: TypeX.ui(10.5, w: FontWeight.w800, color: c.primary, ls: .8))]),
                const Gap(8),
                Text((a['policy'] as String?) ?? 'No policy matched. Decide with your own judgment.', style: TypeX.ui(13, color: c.text2, h: 1.5)),
              ]),
            )),
            SectionCard('Assistant recommendation', icon: PhosphorIconsFill.sparkle, margin: EdgeInsets.zero, child: Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(color: c.isDark ? c.surface2 : const Color(0xFFFFF8E6), borderRadius: BorderRadius.circular(14), border: Border.all(color: DK.saffron.withValues(alpha: .35))),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const AiMark(size: 22), const SizedBox(width: 10),
                Expanded(child: Text(isPrice ? 'Needs a person. No link was provided. The adjustment is within the ৳1,000 limit if verified.' : 'Eligible under the cited policy. Approving sends the customer a confirmation in their language.', style: TypeX.ui(13, color: c.text2, h: 1.5))),
              ]),
            )),
          ]),
          ),
        ),
        Container(
          padding: const EdgeInsets.all(16), decoration: BoxDecoration(color: c.surface, border: Border(top: BorderSide(color: c.line))),
          child: pending && !s.can('approvals.decide')
              ? Row(children: [Icon(PhosphorIconsFill.lockSimple, size: 18, color: c.text3), const SizedBox(width: 10), Expanded(child: Text('Only owners and admins can decide returns, refunds and price matches.', style: TypeX.ui(13, color: c.text2, h: 1.45)))])
              : pending
              ? Column(children: [
                  Row(children: [
                    Expanded(child: DkButton(amount > 0 ? 'Approve ${taka(amount)}' : 'Approve', icon: PhosphorIconsBold.check, kind: BtnKind.primary, expand: true, onPressed: () => s.decide(a['id'] as int, 'approved'))),
                    const SizedBox(width: 8),
                    DkButton('Reject', kind: BtnKind.danger, onPressed: () => s.decide(a['id'] as int, 'rejected')),
                  ]),
                  if (a['conversationId'] != null) ...[const Gap(8), DkButton('Open the conversation', icon: PhosphorIconsRegular.chatCircleText, kind: BtnKind.ghost, expand: true, onPressed: () { s.setSection(Section.inbox); s.selectConversation(a['conversationId'] as String); })],
                ])
              : Row(children: [
                  Tag(a['status'] == 'approved' ? 'Approved' : 'Rejected', tone: a['status'] == 'approved' ? 'ok' : 'danger', dot: true),
                  const SizedBox(width: 10),
                  Expanded(child: Text(a['decidedAt'] != null ? 'Decided ${dateTime(a['decidedAt'] as String?)}' : '', style: TypeX.ui(12.5, color: c.text3))),
                ]),
        ),
      ]),
    );
  }
}
