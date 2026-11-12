import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../brand/icons.dart';
import '../brand/theme.dart';
import '../core/api.dart';
import '../core/format.dart';
import '../core/state.dart';
import '../widgets/kit.dart';
import 'guide_ui.dart';

const importGuide = [
  'Type your shop’s website address. Dakbox looks at the site and shows what it found before anything is saved.',
  'Shopify and WooCommerce shops are read directly. Other websites are read from their sitemap and the product details every shop publishes for Google (name, price, photo).',
  'Websites rarely say how many items you have, only “in stock” or “sold out”. You choose the stock number given to in-stock products, and can change any product afterwards.',
  'Dakbox checks the website again every 6 hours and on Sync now, so prices and sold-out status follow your shop. Stock you counted yourself is never overwritten.',
  'It cannot read shops that draw their products with JavaScript only, sites behind a login, or sites that ask bots to stay out (robots.txt). For those, add products by hand.',
];

Future<void> showImportSite(BuildContext context, {String? url}) =>
    showDialog<void>(context: context, barrierColor: Colors.black.withValues(alpha: .45), builder: (_) => Theme(data: Theme.of(context), child: _ImportDialog(url: url)));

enum _Step { enter, looking, preview, importing, done }

class _ImportDialog extends StatefulWidget {
  const _ImportDialog({this.url});
  final String? url;
  @override
  State<_ImportDialog> createState() => _ImportDialogState();
}

class _ImportDialogState extends State<_ImportDialog> {
  late final url = TextEditingController(text: widget.url ?? '');
  final stock = TextEditingController(text: '10');
  _Step step = _Step.enter;
  String? error;
  J? found, result;
  bool okCurrency = false;

  @override
  void initState() {
    super.initState();
    if ((widget.url ?? '').isNotEmpty) WidgetsBinding.instance.addPostFrameCallback((_) => look());
  }

  @override
  void dispose() { url.dispose(); stock.dispose(); super.dispose(); }

  Future<void> look() async {
    final u = url.text.trim();
    if (u.isEmpty) { setState(() => error = 'Type the address of your website first.'); return; }
    setState(() { step = _Step.looking; error = null; });
    final r = await context.read<AppState>().discoverSite(u);
    if (!mounted) return;
    if (r['error'] != null) { setState(() { step = _Step.enter; error = r['error'] as String; }); return; }
    setState(() { found = r; step = _Step.preview; okCurrency = false; });
  }

  Future<void> run() async {
    final n = int.tryParse(stock.text.trim());
    if (n == null || n < 0 || n > 10000) { setState(() => error = 'Stock must be a number from 0 to 10000.'); return; }
    setState(() { step = _Step.importing; error = null; });
    final r = await context.read<AppState>().importSite(found!['url'] as String, n, okCurrency);
    if (!mounted) return;
    if (r['error'] != null) { setState(() { step = _Step.preview; error = r['error'] as String; }); return; }
    setState(() { result = r; step = _Step.done; });
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Dialog(
      backgroundColor: Colors.transparent, insetPadding: const EdgeInsets.all(20),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 580),
        child: Panel(
          radius: 24, shadow: true,
          child: Padding(
            padding: const EdgeInsets.all(22),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Container(width: 36, height: 36, decoration: BoxDecoration(color: c.primarySoft, borderRadius: BorderRadius.circular(11)), child: Icon(PhosphorIconsBold.globeHemisphereEast, size: 18, color: c.primary)),
                const SizedBox(width: 12),
                Expanded(child: Text('Import products from your website', style: TypeX.display(20, color: c.text))),
                DkIconButton(PhosphorIconsBold.x, size: 32, onPressed: () => Navigator.pop(context)),
              ]),
              const Gap(14),
              Flexible(child: SingleChildScrollView(child: switch (step) {
                _Step.enter || _Step.looking => _enter(c),
                _Step.preview || _Step.importing => _preview(c),
                _Step.done => _done(c),
              })),
            ]),
          ),
        ),
      ),
    );
  }

  Widget _err(Cx c) => error == null ? const SizedBox() : Container(
        margin: const EdgeInsets.only(top: 12), padding: const EdgeInsets.all(12), width: double.infinity,
        decoration: BoxDecoration(color: c.dangerSoft, borderRadius: BorderRadius.circular(12)),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Icon(PhosphorIconsFill.warningCircle, size: 16, color: c.danger), const SizedBox(width: 8), Expanded(child: Text(error!, style: TypeX.ui(13, color: c.text, h: 1.45)))]),
      );

  Widget _enter(Cx c) {
    final busy = step == _Step.looking;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Dakbox reads the product list from your shop’s website, so you do not retype it. Nothing is saved until you confirm.', style: TypeX.ui(13.5, color: c.text2, h: 1.5)),
      const Gap(16),
      DkField(controller: url, label: 'Website address', hint: 'myshop.com', mono: true, onSubmitted: (_) => busy ? null : look()),
      const Gap(12),
      Wrap(spacing: 8, runSpacing: 8, children: const [Tag('Shopify', tone: 'accent', small: true), Tag('WooCommerce', tone: 'accent', small: true), Tag('Most other shop websites', tone: 'accent', small: true), Tag('A single product page', tone: 'accent', small: true)]),
      _err(c),
      const Gap(14),
      const HowToConnect(title: 'What can and cannot be read', steps: importGuide),
      Row(mainAxisAlignment: MainAxisAlignment.end, children: [
        DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
        const Gap(8),
        DkButton(busy ? 'Looking at the site…' : 'Find products', icon: PhosphorIconsBold.magnifyingGlass, kind: BtnKind.primary, onPressed: busy ? null : look),
      ]),
    ]);
  }

  Widget _preview(Cx c) {
    final f = found!;
    final busy = step == _Step.importing;
    final usable = f['usable'] as int;
    final items = (f['items'] as List).cast<J>();
    final cur = f['currency'] as String?;
    final needsOk = cur != null && cur != 'BDT';
    final warnings = (f['warnings'] as List).cast<String>();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Container(
        padding: const EdgeInsets.all(14), width: double.infinity,
        decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(14), border: Border.all(color: c.line)),
        child: Row(children: [
          Container(width: 40, height: 40, alignment: Alignment.center, decoration: BoxDecoration(color: c.okSoft, borderRadius: BorderRadius.circular(12)), child: Icon(PhosphorIconsFill.checkCircle, size: 22, color: c.ok)),
          const SizedBox(width: 12),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${plural(usable, 'product')} found on ${f['host']}', style: TypeX.ui(15, w: FontWeight.w800, color: c.text)),
            const SizedBox(height: 2),
            Text('${f['kindLabel']}${(f['outOfStock'] as int) > 0 ? ' · ${f['outOfStock']} sold out' : ''}${cur != null ? ' · prices in $cur' : ''}', style: TypeX.ui(12.5, color: c.text3)),
          ])),
          if (f['connected'] == true) const Tag('Already connected: this updates it', tone: 'accent', small: true),
        ]),
      ),
      for (final w in warnings)
        Container(
          margin: const EdgeInsets.only(top: 10), padding: const EdgeInsets.all(12), width: double.infinity,
          decoration: BoxDecoration(color: c.warnSoft, borderRadius: BorderRadius.circular(12)),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Icon(PhosphorIconsFill.warning, size: 16, color: c.warn), const SizedBox(width: 8), Expanded(child: Text(w, style: TypeX.ui(12.5, color: c.text, h: 1.45)))]),
        ),
      const Gap(14),
      Label('A look at what will be added'),
      const Gap(8),
      Container(
        decoration: BoxDecoration(border: Border.all(color: c.line), borderRadius: BorderRadius.circular(14)),
        clipBehavior: Clip.antiAlias,
        child: Column(children: [
          for (var i = 0; i < items.length; i++)
            Container(
              decoration: BoxDecoration(border: i == 0 ? null : Border(top: BorderSide(color: c.line))), padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: Row(children: [
                ProductPhoto(image: items[i]['image'] as String?, kind: 'box', size: 40, radius: 10),
                const SizedBox(width: 12),
                Expanded(child: Text('${items[i]['name']}${items[i]['variant'] != null ? ' · ${items[i]['variant']}' : ''}', maxLines: 1, overflow: TextOverflow.ellipsis, style: TypeX.ui(13.5, w: FontWeight.w600, color: c.text))),
                const SizedBox(width: 8),
                if (items[i]['inStock'] == false) const Tag('Sold out', tone: 'danger', small: true),
                const SizedBox(width: 10),
                Text(taka(items[i]['price'] as num), style: TypeX.mono(13, color: c.text2)),
              ]),
            ),
          if (usable > items.length) Container(width: double.infinity, color: c.surface2, padding: const EdgeInsets.symmetric(vertical: 8), child: Center(child: Text('and ${usable - items.length} more', style: TypeX.ui(12.5, color: c.text3)))),
        ]),
      ),
      const Gap(16),
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(width: 150, child: DkField(controller: stock, label: 'Stock for in-stock items', mono: true)),
        const SizedBox(width: 14),
        Expanded(child: Padding(padding: const EdgeInsets.only(top: 22), child: Text((f['stockKnown'] as int) > 0 ? 'The site gives real numbers for ${f['stockKnown']} of them; those are used. The rest get this number.' : 'The site says only “in stock” or “sold out”, not how many. Enter a number you can really supply. Sold-out items get 0.', style: TypeX.ui(12.5, color: c.text3, h: 1.45)))),
      ]),
      if (needsOk) ...[
        const Gap(12),
        Hover(
          onTap: () => setState(() => okCurrency = !okCurrency),
          builder: (_, __, ___) => Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(okCurrency ? PhosphorIconsFill.checkSquare : PhosphorIconsRegular.square, size: 20, color: okCurrency ? c.primary : c.text3),
            const SizedBox(width: 8),
            Expanded(child: Text('I understand the prices are in $cur and will be copied as Taka numbers.', style: TypeX.ui(13, w: FontWeight.w600, color: c.text))),
          ]),
        ),
      ],
      _err(c),
      const Gap(16),
      Row(mainAxisAlignment: MainAxisAlignment.end, children: [
        DkButton('Back', kind: BtnKind.ghost, onPressed: busy ? null : () => setState(() { step = _Step.enter; error = null; })),
        const Gap(8),
        DkButton(busy ? 'Importing…' : 'Import ${plural(usable, 'product')}', icon: PhosphorIconsBold.downloadSimple, kind: BtnKind.primary, onPressed: busy || usable == 0 || (needsOk && !okCurrency) ? null : run),
      ]),
    ]);
  }

  Widget _done(Cx c) {
    final r = result!;
    Widget stat(String v, String l, Color col) => Expanded(child: Container(
          padding: const EdgeInsets.symmetric(vertical: 14), margin: const EdgeInsets.only(right: 8),
          decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(14), border: Border.all(color: c.line)),
          child: Column(children: [Text(v, style: TypeX.display(24, color: col)), const SizedBox(height: 2), Text(l, style: TypeX.ui(12, color: c.text3))]),
        ));
    final why = (r['skippedWhy'] as Map?)?.entries.map((e) => '${e.value} with ${e.key}').join(', ');
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [Icon(PhosphorIconsFill.checkCircle, size: 22, color: c.ok), const SizedBox(width: 8), Text('Your website is connected', style: TypeX.ui(15, w: FontWeight.w800, color: c.text))]),
      const Gap(14),
      Row(children: [stat('${r['added']}', 'added', c.ok), stat('${r['updated']}', 'updated', c.primary), stat('${r['skipped']}', 'skipped', c.text3)]),
      if (why != null && why.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 10), child: Text('Skipped: $why.', style: TypeX.ui(12.5, color: c.text3))),
      const Gap(12),
      Text('Dakbox will check the website again every 6 hours. You can also press Sync now under Connections, Store, or disconnect it there. Imported products stay either way.', style: TypeX.ui(13, color: c.text2, h: 1.5)),
      const Gap(16),
      Row(mainAxisAlignment: MainAxisAlignment.end, children: [DkButton('Done', kind: BtnKind.primary, onPressed: () => Navigator.pop(context))]),
    ]);
  }
}

typedef Cx = DK;

// ====================================================================== Connections, Store
class CatalogPanel extends StatefulWidget {
  const CatalogPanel({super.key});
  @override
  State<CatalogPanel> createState() => _CatalogPanelState();
}

class _CatalogPanelState extends State<CatalogPanel> {
  final url = TextEditingController();
  String? syncing;

  @override
  void dispose() { url.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final can = s.can('products.manage');
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      HowToConnect(title: 'How to bring your website’s products into Dakbox', steps: importGuide, open: s.catalogSources.isEmpty),
      Container(
        padding: const EdgeInsets.all(16), margin: const EdgeInsets.only(bottom: 14),
        decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(18), border: Border.all(color: c.line)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Container(width: 38, height: 38, decoration: BoxDecoration(gradient: c.brand, borderRadius: BorderRadius.circular(11)), child: const Icon(PhosphorIconsBold.globeHemisphereEast, size: 19, color: Colors.white)),
            const SizedBox(width: 12),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Connect your website', style: TypeX.ui(14.5, w: FontWeight.w800, color: c.text)),
              Text('Shopify, WooCommerce or any website with product pages.', style: TypeX.ui(12.5, color: c.text3)),
            ])),
          ]),
          const Gap(14),
          Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
            Expanded(child: DkField(controller: url, hint: 'myshop.com', mono: true, onSubmitted: (_) => _go(context))),
            const SizedBox(width: 10),
            DkButton('Find products', icon: PhosphorIconsBold.magnifyingGlass, kind: BtnKind.primary, onPressed: can ? () => _go(context) : null),
          ]),
          if (!can) Padding(padding: const EdgeInsets.only(top: 8), child: Text('Only owners and admins can connect a website.', style: TypeX.ui(12.5, color: c.text3))),
        ]),
      ),
      if (s.catalogSources.isNotEmpty) ...[
        Padding(padding: const EdgeInsets.only(bottom: 8), child: Label('Connected websites')),
        for (final src in s.catalogSources) _SourceCard(src: src, busy: syncing == src['id'], onSync: () => _sync(context, src)),
      ],
    ]);
  }

  void _go(BuildContext context) {
    final u = url.text.trim();
    url.clear();
    showImportSite(context, url: u.isEmpty ? null : u);
  }

  Future<void> _sync(BuildContext context, J src) async {
    final s = context.read<AppState>();
    setState(() => syncing = src['id'] as String);
    final r = await s.syncSite(src['id'] as String);
    if (!mounted) return;
    setState(() => syncing = null);
    s.toast(r['error'] != null ? r['error'] as String : 'Synced: ${r['added']} added, ${r['updated']} updated');
  }
}

class _SourceCard extends StatelessWidget {
  const _SourceCard({required this.src, required this.busy, required this.onSync});
  final J src;
  final bool busy;
  final VoidCallback onSync;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.read<AppState>();
    final err = src['lastError'] as String?;
    final can = s.can('products.manage');
    return Container(
      margin: const EdgeInsets.only(bottom: 10), padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(18), border: Border.all(color: err != null ? c.danger.withValues(alpha: .4) : c.primaryLine)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Container(width: 38, height: 38, decoration: BoxDecoration(color: c.primarySoft, borderRadius: BorderRadius.circular(11)), child: Icon(PhosphorIconsBold.storefront, size: 19, color: c.primary)),
          const SizedBox(width: 12),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(src['host'] as String, style: TypeX.ui(14.5, w: FontWeight.w800, color: c.text), maxLines: 1, overflow: TextOverflow.ellipsis),
            Text('${src['kindLabel']} · ${plural(src['products'] as int, 'product')} · synced ${src['lastSyncAt'] == null ? 'never' : relative(src['lastSyncAt'] as String)}', style: TypeX.ui(12.5, color: c.text3)),
          ])),
          Tag(err != null ? 'Last sync failed' : 'Connected', tone: err != null ? 'danger' : 'ok', dot: true, small: true),
        ]),
        if (err != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(err, style: TypeX.ui(12.5, color: c.danger, h: 1.45)))
        else if (src['lastNote'] != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text('Last sync: ${src['lastNote']}.', style: TypeX.ui(12.5, color: c.text3, h: 1.45))),
        const Gap(12),
        _OrdersLine(src: src),
        const Gap(12),
        Wrap(spacing: 8, runSpacing: 8, children: [
          DkButton(busy ? 'Syncing…' : 'Sync now', icon: PhosphorIconsRegular.arrowsClockwise, kind: BtnKind.soft, small: true, onPressed: can && !busy ? onSync : null),
          DkButton((src['ordersCount'] as int) > 0 ? 'Order sync' : 'Set up order sync', icon: PhosphorIconsRegular.shoppingBag, kind: BtnKind.soft, small: true, onPressed: can ? () => showOrderSync(context, src) : null),
          DkButton('Disconnect', kind: BtnKind.ghost, small: true, onPressed: can ? () => _confirm(context) : null),
        ]),
      ]),
    );
  }

  Future<void> _confirm(BuildContext context) async {
    final s = context.read<AppState>();
    final c = context.c;
    final ok = await showDialog<bool>(
      context: context, barrierColor: Colors.black.withValues(alpha: .45),
      builder: (ctx) => Dialog(
        backgroundColor: Colors.transparent, insetPadding: const EdgeInsets.all(20),
        child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 440), child: Panel(radius: 24, shadow: true, child: Padding(padding: const EdgeInsets.all(22), child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Disconnect ${src['host']}?', style: TypeX.display(19, color: c.text)),
          const Gap(10),
          Text('Dakbox stops checking this website. The ${plural(src['products'] as int, 'product')} already imported stay in Products with their current prices and stock, and keep working in orders. Connecting the same website again picks them up instead of duplicating them.', style: TypeX.ui(13.5, color: c.text2, h: 1.5)),
          const Gap(18),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(ctx, false)), const Gap(8), DkButton('Disconnect', kind: BtnKind.danger, onPressed: () => Navigator.pop(ctx, true))]),
        ])))),
      ),
    );
    if (ok != true) return;
    final r = await s.disconnectSite(src['id'] as String);
    s.toast(r['error'] != null ? r['error'] as String : 'Website disconnected. Its products were kept');
  }
}


class _OrdersLine extends StatelessWidget {
  const _OrdersLine({required this.src});
  final J src;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final err = src['ordersError'] as String?;
    final n = src['ordersCount'] as int;
    final (icon, col, text) = err != null
        ? (PhosphorIconsFill.warningCircle, c.danger, err)
        : n > 0
            ? (PhosphorIconsFill.checkCircle, c.ok, '${plural(n, 'website order')} received, the last ${relative(src['ordersAt'] as String?)}')
            : (PhosphorIconsRegular.shoppingBag, c.text3, 'Orders placed on this website do not reach Dakbox yet. Set up order sync to receive them.');
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Icon(icon, size: 15, color: col), const SizedBox(width: 8), Expanded(child: Text(text, style: TypeX.ui(12.5, color: err != null ? c.danger : c.text2, h: 1.45)))]);
  }
}

Future<void> showOrderSync(BuildContext context, J src) =>
    showDialog<void>(context: context, barrierColor: Colors.black.withValues(alpha: .45), builder: (_) => Theme(data: Theme.of(context), child: _OrderSync(src: src)));

class _OrderSync extends StatefulWidget {
  const _OrderSync({required this.src});
  final J src;
  @override
  State<_OrderSync> createState() => _OrderSyncState();
}

class _OrderSyncState extends State<_OrderSync> {
  J? info;
  String? error;
  bool reveal = false, busy = false;
  final signing = TextEditingController();
  Timer? _poll;

  String get id => widget.src['id'] as String;

  @override
  void initState() {
    super.initState();
    _load();
    // While this window is open, keep the status fresh so “nothing received yet” turns green when the test order lands.
    _poll = Timer.periodic(const Duration(seconds: 4), (_) => _load(quiet: true));
  }

  @override
  void dispose() { _poll?.cancel(); signing.dispose(); super.dispose(); }

  Future<void> _load({bool quiet = false}) async {
    final s = context.read<AppState>();
    final r = await s.ordersSetup(id);
    if (!mounted) return;
    if (quiet) {
      if (r['error'] == null) { setState(() => info = r); s.loadCatalogSources(); }
      return;
    }
    setState(() { if (r['error'] != null) { error = r['error'] as String; } else { info = r; } });
  }

  Future<void> _act(Future<J> Function() f) async {
    setState(() { busy = true; error = null; });
    final r = await f();
    if (!mounted) return;
    setState(() { busy = false; if (r['error'] != null) { error = r['error'] as String; } else { info = r; } });
  }

  void _copy(String v, String what) { Clipboard.setData(ClipboardData(text: v)); context.read<AppState>().toast('$what copied'); }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.read<AppState>();
    final i = info;
    final kind = widget.src['kind'] as String;
    return Dialog(
      backgroundColor: Colors.transparent, insetPadding: const EdgeInsets.all(20),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 620, maxHeight: 760),
        child: Panel(
          radius: 24, shadow: true,
          child: Padding(
            padding: const EdgeInsets.all(22),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Container(width: 36, height: 36, decoration: BoxDecoration(color: c.primarySoft, borderRadius: BorderRadius.circular(11)), child: Icon(PhosphorIconsBold.shoppingBag, size: 18, color: c.primary)),
                const SizedBox(width: 12),
                Expanded(child: Text('Get ${widget.src['host']}’s orders in Dakbox', style: TypeX.display(19, color: c.text))),
                DkIconButton(PhosphorIconsBold.x, size: 32, onPressed: () => Navigator.pop(context)),
              ]),
              const Gap(12),
              Flexible(
                child: SingleChildScrollView(
                  child: i == null
                      ? Padding(padding: const EdgeInsets.symmetric(vertical: 30), child: Center(child: error != null ? Text(error!, style: TypeX.ui(13, color: c.danger)) : CircularProgressIndicator(color: c.primary)))
                      : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text('When a customer orders on the website, the website sends the order to Dakbox at once. The order appears in Orders as “From website”, linked to the customer by phone, and Dakbox’s stock goes down to match the shop.', style: TypeX.ui(13.5, color: c.text2, h: 1.5)),
                          if (i['publicUrlSet'] != true) _box(c, c.warnSoft, PhosphorIconsFill.warning, c.warn, 'Dakbox needs a public https address before a website can reach it. Set it under Connections, Channels, Meta app (it is shared), or use a tunnel while testing. The address below is a placeholder until then.'),
                          const Gap(14),
                          _steps(c, kind),
                          const Gap(14),
                          _copyRow(c, 'Address to send orders to', i['url'] as String, 'Address'),
                          const Gap(10),
                          if (kind == 'shopify') ...[
                            Label('Shopify’s signing secret'),
                            const Gap(6),
                            Row(children: [
                              Expanded(child: DkField(controller: signing, hint: i['secretSet'] == true ? 'Saved. Paste a new one to replace it' : 'Paste the key Shopify shows', mono: true, obscure: true)),
                              const SizedBox(width: 8),
                              DkButton('Save', kind: BtnKind.primary, onPressed: busy ? null : () async { final v = signing.text.trim(); if (v.length < 8) { setState(() => error = 'That does not look like a signing secret.'); return; } await _act(() => s.saveOrdersSetup(id, {'signingSecret': v})); signing.clear(); }),
                            ]),
                            Padding(padding: const EdgeInsets.only(top: 6), child: Text(i['secretSet'] == true ? 'Saved. Dakbox accepts orders signed with it, and refuses everything else.' : 'Until this is saved, Dakbox refuses every request from the shop.', style: TypeX.ui(12, color: i['secretSet'] == true ? c.ok : c.text3))),
                          ] else ...[
                            _copyRow(c, 'Secret', i['secret'] as String? ?? '', 'Secret', hidden: !reveal, trailing: DkIconButton(reveal ? PhosphorIconsRegular.eyeSlash : PhosphorIconsRegular.eye, size: 30, onPressed: () => setState(() => reveal = !reveal))),
                            Align(alignment: Alignment.centerLeft, child: Padding(padding: const EdgeInsets.only(top: 6), child: Hover(onTap: busy ? null : () => _act(() => s.newOrdersSecret(id)), builder: (_, h, __) => Text('Make a new secret (the old one stops working at once)', style: TypeX.ui(12, w: FontWeight.w700, color: h ? c.primaryHover : c.primary))))),
                          ],
                          const Gap(16),
                          Row(children: [
                            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              Text('Text the customer “order placed”', style: TypeX.ui(13.5, w: FontWeight.w700, color: c.text)),
                              Text('Uses your SMS connection and the Notifications settings. Turn off if the shop already messages customers.', style: TypeX.ui(12, color: c.text3, h: 1.4)),
                            ])),
                            const SizedBox(width: 12),
                            DkSwitch(value: i['notifySms'] == true, onChanged: busy ? null : (v) => _act(() => s.saveOrdersSetup(id, {'notifySms': v}))),
                          ]),
                          const Gap(16),
                          _status(c, i),
                          if (error != null) _box(c, c.dangerSoft, PhosphorIconsFill.warningCircle, c.danger, error!),
                        ]),
                ),
              ),
              const Gap(16),
              Row(mainAxisAlignment: MainAxisAlignment.end, children: [DkButton('Done', kind: BtnKind.primary, onPressed: () => Navigator.pop(context))]),
            ]),
          ),
        ),
      ),
    );
  }

  Widget _box(DK c, Color bg, IconData icon, Color fg, String text) => Container(
        margin: const EdgeInsets.only(top: 12), padding: const EdgeInsets.all(12), width: double.infinity,
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(12)),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Icon(icon, size: 16, color: fg), const SizedBox(width: 8), Expanded(child: Text(text, style: TypeX.ui(12.5, color: c.text, h: 1.45)))]),
      );

  Widget _status(DK c, J i) {
    final err = i['ordersError'] as String?;
    final n = (i['ordersCount'] ?? 0) as int;
    return Container(
      width: double.infinity, padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: err != null ? c.dangerSoft : (n > 0 ? c.okSoft : c.surface2), borderRadius: BorderRadius.circular(12), border: Border.all(color: c.line)),
      child: Text(err ?? (n > 0 ? '${plural(n, 'order')} received, the last ${relative(i['ordersAt'] as String?)}.' : 'Nothing received yet. Place a test order on the website, then come back: this line turns green.'), style: TypeX.ui(12.5, w: FontWeight.w600, color: c.text)),
    );
  }

  Widget _copyRow(DK c, String label, String value, String what, {bool hidden = false, Widget? trailing}) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Label(label),
        const Gap(6),
        Container(
          padding: const EdgeInsets.fromLTRB(12, 4, 4, 4), decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(12), border: Border.all(color: c.line)),
          child: Row(children: [
            Expanded(child: Text(hidden ? '•' * 24 : value, maxLines: 1, overflow: TextOverflow.ellipsis, style: TypeX.mono(12.5, color: c.text))),
            ?trailing,
            DkIconButton(PhosphorIconsRegular.copy, tooltip: 'Copy', size: 30, onPressed: () => _copy(value, what)),
          ]),
        ),
      ]);

  Widget _steps(DK c, String kind) {
    final steps = switch (kind) {
      'shopify' => const [
          'In Shopify admin open Settings, Notifications, Webhooks and press Create webhook.',
          'Event: Order creation. Format: JSON. URL: the address below. Save. Repeat for Order payment and Order cancellation so payments and cancellations follow.',
          'At the bottom of that page Shopify says your webhooks are signed with a key. Copy that key and paste it into the box below, then Save.',
        ],
      'woo' => const [
          'In WordPress open WooCommerce, Settings, Advanced, Webhooks and press Add webhook.',
          'Name: Dakbox. Status: Active. Topic: Order created. Delivery URL and Secret: the two values below. Save. Add a second webhook with Topic Order updated so payments and cancellations follow.',
          'WooCommerce sends a test message when you save. Then place a test order on the website.',
        ],
      _ => const [
          'Your website, plugin or tool sends each order to the address below as JSON, with a signature so Dakbox knows it is yours.',
          'Header X-Dakbox-Signature: sha256=<HMAC-SHA256 of the raw body in hex, keyed with the secret below>. Body: {"id":"A-1","number":"A-1","paid":false,"payment_method":"Cash on delivery","name":"…","phone":"01712345678","address":"…","city":"Dhaka","shipping":110,"total":9910,"lines":[{"sku":"…","name":"…","price":1450,"qty":2}]}. Send "cancelled": true or "paid": true later to update it.',
        ],
    };
    return GuideSteps(steps: steps);
  }
}
