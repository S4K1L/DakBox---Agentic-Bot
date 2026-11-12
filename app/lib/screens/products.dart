import 'package:flutter/material.dart';
import '../brand/icons.dart';
import 'package:provider/provider.dart';
import '../brand/theme.dart';
import '../core/api.dart';
import '../core/format.dart';
import '../core/state.dart';
import '../widgets/kit.dart';
import '../widgets/page.dart';
import 'catalog_ui.dart';

String stockState(int n) => n == 0 ? 'out' : (n <= 10 ? 'low' : 'ok');

class ProductsScreen extends StatefulWidget {
  const ProductsScreen({super.key});
  @override
  State<ProductsScreen> createState() => _ProductsScreenState();
}

class _ProductsScreenState extends State<ProductsScreen> {
  String sort = 'best';

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final c = context.c;
    final rows = s.products.where((p) {
      final st = stockState(p['stock'] as int);
      if (s.productTab == 'low' && st != 'low') return false;
      if (s.productTab == 'out' && st != 'out') return false;
      if (s.productQuery.isNotEmpty && !('${p['name']} ${p['variant']} ${p['sku']}'.toLowerCase().contains(s.productQuery.toLowerCase()))) return false;
      return true;
    }).toList();
    rows.sort((a, b) => switch (sort) {
          'stock' => (a['stock'] as int).compareTo(b['stock'] as int),
          'name' => (a['name'] as String).compareTo(b['name'] as String),
          _ => (b['sold30'] as num).compareTo(a['sold30'] as num),
        });
    final low = s.products.where((p) => stockState(p['stock'] as int) == 'low').length;
    final out = s.products.where((p) => stockState(p['stock'] as int) == 'out').length;
    final value = s.products.fold<num>(0, (t, p) => t + (p['price'] as num) * (p['stock'] as int));
    final bestSku = s.products.isEmpty ? null : (s.products.toList()..sort((a, b) => (b['sold30'] as num).compareTo(a['sold30'] as num))).first['sku'];
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        PageHeader(
          title: 'Products and stock',
          subtitle: Wrap(spacing: 8, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
            Text('Live numbers the assistant quotes to customers. Changes save instantly.', style: TypeX.ui(13.5, color: c.text3)),
            const Tag('Sample catalog', tone: 'warn', small: true),
          ]),
          actions: [SearchBox(hint: 'Search products', width: 230, onChanged: s.setProductQuery), if (s.can('products.manage')) DkButton('Import from website', icon: PhosphorIconsRegular.globeHemisphereEast, onPressed: () => showImportSite(context)), if (s.can('products.manage')) DkButton('Add product', icon: PhosphorIconsBold.plus, kind: BtnKind.primary, onPressed: () => showDialog<void>(context: context, barrierColor: Colors.black.withValues(alpha: .45), builder: (_) => const _ProductDialog())), DkButton('Refresh', icon: PhosphorIconsRegular.arrowsClockwise, onPressed: () => s.loadProducts().then((_) => s.toast('Stock is up to date')))],
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(24, 0, 24, 14),
          child: Row(children: [
            StatTile(value: '${s.products.length}', label: 'Products', icon: PhosphorIconsRegular.package, active: s.productTab == 'all', onTap: () => s.setProductTab('all')),
            const SizedBox(width: 8),
            StatTile(value: '$low', label: 'Low stock (10 or fewer)', icon: PhosphorIconsRegular.warningCircle, tone: 'warn', active: s.productTab == 'low', onTap: () => s.setProductTab('low')),
            const SizedBox(width: 8),
            StatTile(value: '$out', label: 'Out of stock', icon: PhosphorIconsRegular.minusCircle, tone: 'danger', active: s.productTab == 'out', onTap: () => s.setProductTab('out')),
            const SizedBox(width: 8),
            StatTile(value: taka(value), label: 'Stock value at selling price', icon: PhosphorIconsRegular.coins, tone: 'ok'),
          ]),
        ),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 8),
          decoration: BoxDecoration(border: Border(top: BorderSide(color: c.line), bottom: BorderSide(color: c.line)), color: c.surface2),
          child: Row(children: [
            Text('${plural(rows.length, 'product')}${s.productTab == 'all' ? '' : s.productTab == 'low' ? ' with low stock' : ' out of stock'}', style: TypeX.ui(12.5, w: FontWeight.w700, color: c.text2)),
            const Spacer(),
            Text('Sort', style: TypeX.ui(12, color: c.text3)),
            const SizedBox(width: 8),
            Seg<String>(items: const [('best', 'Best selling'), ('stock', 'Lowest stock'), ('name', 'Name')], value: sort, onChanged: (v) => setState(() => sort = v), small: true),
          ]),
        ),
        Expanded(
          child: rows.isEmpty
              ? Empty(s.products.isEmpty ? 'No products yet' : 'No products match this view', body: s.products.isEmpty ? (s.can('products.manage') ? 'Add your first product. The assistant quotes its price and stock to customers.' : 'Ask an owner or admin to add products.') : null, icon: PhosphorIconsDuotone.package)
              : Container(
                  color: c.surface2,
                  child: LayoutBuilder(builder: (context, box) {
                    final cols = (box.maxWidth / 290).floor().clamp(1, 4);
                    return GridView.builder(
                      padding: const EdgeInsets.all(20),
                      gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(crossAxisCount: cols, mainAxisSpacing: 14, crossAxisSpacing: 14, mainAxisExtent: 286),
                      itemCount: rows.length,
                      itemBuilder: (_, i) => Reveal(delay: i * 40, child: _ProductCard(p: rows[i], best: rows[i]['sku'] == bestSku && (rows[i]['sold30'] as num) > 0)),
                    );
                  }),
                ),
        ),
      ]),
    );
  }
}

class _ProductCard extends StatelessWidget {
  const _ProductCard({required this.p, required this.best});
  final J p;
  final bool best;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.read<AppState>();
    final stock = p['stock'] as int;
    final st = stockState(stock);
    final pct = (stock / 40).clamp(0.0, 1.0);
    final col = st == 'ok' ? c.ok : (st == 'low' ? c.warn : c.danger);
    return Hover(
      builder: (_, h, __) => AnimatedContainer(
        duration: const Duration(milliseconds: 160),
        decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(18), border: Border.all(color: h ? c.line2 : c.line), boxShadow: h ? c.lift : c.shadow),
        clipBehavior: Clip.antiAlias,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(height: 112, width: double.infinity, child: Stack(children: [
            Positioned.fill(child: ProductPhoto(image: p['image'] as String?, kind: p['art'] as String?, size: 400, radius: 0)),
            if (best) Positioned(top: 10, left: 10, child: const Tag('Best seller', tone: 'ai', icon: PhosphorIconsFill.star, small: true)),
            if (s.can('products.manage')) Positioned(bottom: 8, right: 8, child: Hover(onTap: () => showDialog<void>(context: context, barrierColor: Colors.black.withValues(alpha: .45), builder: (_) => _ProductDialog(edit: p)), builder: (_, hh, __) => Container(width: 30, height: 30, decoration: BoxDecoration(color: hh ? c.surface : c.surface.withValues(alpha: .85), borderRadius: BorderRadius.circular(9), border: Border.all(color: c.line)), child: Icon(PhosphorIconsRegular.pencilSimple, size: 15, color: c.text2)))),
            Positioned(top: 10, right: 10, child: Tag(st == 'out' ? 'Out of stock' : (st == 'low' ? 'Low stock' : 'In stock'), tone: st == 'ok' ? 'ok' : (st == 'low' ? 'warn' : 'danger'), dot: true, small: true)),
          ])),
          Expanded(
            child: Padding(
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(p['name'] as String, style: TypeX.display(16, color: c.text, ls: -.01), maxLines: 1, overflow: TextOverflow.ellipsis),
              const SizedBox(height: 1),
              Text('${p['variant'] ?? ''}', style: TypeX.ui(12.5, color: c.text3), maxLines: 1, overflow: TextOverflow.ellipsis),
              const SizedBox(height: 8),
              Row(crossAxisAlignment: CrossAxisAlignment.end, children: [Text(taka(p['price'] as num), style: TypeX.display(19, color: c.text, ls: 0)), const Spacer(), Text(p['sku'] as String, style: TypeX.mono(10.5, color: c.text3))]),
              const SizedBox(height: 12),
              Row(children: [
                Text('$stock', style: TypeX.display(15, color: col, ls: 0)),
                const SizedBox(width: 4),
                Text(stock == 1 ? 'unit in stock' : 'units in stock', style: TypeX.ui(12, color: c.text3)),
              ]),
              const SizedBox(height: 6),
              ClipRRect(borderRadius: BorderRadius.circular(99), child: TweenAnimationBuilder<double>(tween: Tween(end: pct), duration: const Duration(milliseconds: 600), curve: Curves.easeOutCubic, builder: (_, v, __) => LinearProgressIndicator(value: v, minHeight: 6, color: col, backgroundColor: c.sunken))),
              const Spacer(),
              Row(children: [
                Icon(PhosphorIconsRegular.trendUp, size: 14, color: c.text3), const SizedBox(width: 5),
                Expanded(child: Text('${p['sold30']} sold in 30 days', style: TypeX.ui(12, color: c.text3), maxLines: 1, overflow: TextOverflow.ellipsis)),
                _Stepper(value: stock, onMinus: s.can('products.stock') && stock > 0 ? () => s.adjustStock(p['sku'] as String, -1) : null, onPlus: s.can('products.stock') ? () => s.adjustStock(p['sku'] as String, 1) : null),
              ]),
            ]),
            ),
          ),
        ]),
      ),
    );
  }
}

class _Stepper extends StatelessWidget {
  const _Stepper({required this.value, required this.onMinus, required this.onPlus});
  final int value;
  final VoidCallback? onMinus, onPlus;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    Widget b(IconData i, VoidCallback? f) => Hover(onTap: f, pressScale: .9, builder: (_, h, __) => Container(width: 28, height: 28, decoration: BoxDecoration(color: h && f != null ? c.sunken : c.sunken.withValues(alpha: 0), borderRadius: BorderRadius.circular(8)), child: Icon(i, size: 15, color: f == null ? c.text3.withValues(alpha: .5) : c.text2)));
    return Container(
      decoration: BoxDecoration(border: Border.all(color: c.line2), borderRadius: BorderRadius.circular(10)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [b(PhosphorIconsBold.minus, onMinus), SizedBox(width: 30, child: Text('$value', textAlign: TextAlign.center, style: TypeX.mono(13, w: FontWeight.w700, color: c.text))), b(PhosphorIconsBold.plus, onPlus)]),
    );
  }
}


class _ProductDialog extends StatefulWidget {
  const _ProductDialog({this.edit});
  final J? edit;
  @override
  State<_ProductDialog> createState() => _ProductDialogState();
}

class _ProductDialogState extends State<_ProductDialog> {
  late final Map<String, TextEditingController> f = {
    for (final k in ['name', 'variant', 'sku', 'price', 'stock', 'description', 'keywords']) k: TextEditingController(text: '${widget.edit?[k] ?? ''}'),
  };
  late String art = (widget.edit?['art'] as String?) ?? 'box';
  String? error;
  bool busy = false, confirmDelete = false;

  @override
  void dispose() { for (final c in f.values) { c.dispose(); } super.dispose(); }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = context.read<AppState>();
    final editing = widget.edit != null;
    Widget field(String k, String label, {String? hint, bool mono = false, int lines = 1, bool enabled = true}) => Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(label, style: TypeX.ui(12.5, w: FontWeight.w700, color: c.text2)),
            const SizedBox(height: 6),
            Opacity(opacity: enabled ? 1 : .55, child: IgnorePointer(ignoring: !enabled, child: DkField(controller: f[k]!, hint: hint, mono: mono, maxLines: lines))),
          ]),
        );
    return Dialog(
      backgroundColor: Colors.transparent, insetPadding: const EdgeInsets.all(20),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520, maxHeight: 780),
        child: Panel(radius: 24, child: SingleChildScrollView(padding: const EdgeInsets.all(24), child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [Expanded(child: Text(editing ? 'Edit product' : 'Add a product', style: TypeX.display(21, color: c.text))), DkIconButton(PhosphorIconsBold.x, size: 32, onPressed: () => Navigator.pop(context))]),
          const Gap(14),
          if (error != null) Container(margin: const EdgeInsets.only(bottom: 14), padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: c.dangerSoft, borderRadius: BorderRadius.circular(12)), child: Text(error!, style: TypeX.ui(12.5, w: FontWeight.w600, color: c.text, h: 1.4))),
          field('name', 'Name', hint: 'Camp Stove'),
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(child: field('variant', 'Variant (optional)', hint: 'Single burner')),
            const SizedBox(width: 12),
            Expanded(child: field('sku', 'SKU', hint: 'NW-CS-1', mono: true, enabled: !editing)),
          ]),
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(child: field('price', 'Price (৳)', hint: '3200', mono: true)),
            const SizedBox(width: 12),
            Expanded(child: field('stock', 'Units in stock', hint: '12', mono: true)),
          ]),
          field('description', 'What the assistant may say about it (optional)', hint: 'Folding gas stove, boils 1 L in 4 minutes.', lines: 3),
          field('keywords', 'Words customers use for it (optional)', hint: 'stove burner cooking chula, one per space'),
          Text('Look', style: TypeX.ui(12.5, w: FontWeight.w700, color: c.text2)),
          const Gap(8),
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final k in const ['box', 'bottle', 'tent', 'boot', 'jacket'])
              Hover(
                onTap: () => setState(() => art = k),
                builder: (_, h, __) => Container(padding: const EdgeInsets.all(4), decoration: BoxDecoration(borderRadius: BorderRadius.circular(14), border: Border.all(color: art == k ? c.primary : (h ? c.line2 : c.line), width: art == k ? 2 : 1)), child: ProductArt(kind: k, size: 52, radius: 10)),
              ),
          ]),
          const Gap(6),
          Text('Product photos are not supported yet: pick the closest picture.', style: TypeX.ui(11.5, color: c.text3)),
          const Gap(20),
          Row(children: [
            if (editing) ...[
              DkButton(confirmDelete ? 'Really delete' : 'Delete', icon: PhosphorIconsRegular.minusCircle, kind: BtnKind.danger, onPressed: busy ? null : () async {
                if (!confirmDelete) { setState(() => confirmDelete = true); return; }
                setState(() { busy = true; error = null; });
                final r = await s.deleteProduct(widget.edit!['sku'] as String);
                if (!mounted) return;
                if (r['error'] != null) { setState(() { busy = false; error = r['error'] as String; confirmDelete = false; }); } else { Navigator.pop(context); s.toast('Product deleted'); }
              }),
              const Spacer(),
            ] else const Spacer(),
            DkButton('Cancel', kind: BtnKind.ghost, onPressed: () => Navigator.pop(context)),
            const Gap(8),
            DkButton(busy ? 'Saving…' : (editing ? 'Save changes' : 'Add product'), icon: PhosphorIconsBold.check, kind: BtnKind.primary, onPressed: busy ? null : () async {
              final price = int.tryParse(f['price']!.text.trim()), stock = int.tryParse(f['stock']!.text.trim());
              if (f['name']!.text.trim().isEmpty || f['sku']!.text.trim().isEmpty) { setState(() => error = 'Name and SKU are required.'); return; }
              if (price == null || price < 1) { setState(() => error = 'Price must be a whole number of taka, at least 1.'); return; }
              if (stock == null || stock < 0) { setState(() => error = 'Stock must be a whole number, 0 or more.'); return; }
              setState(() { busy = true; error = null; confirmDelete = false; });
              final body = {'name': f['name']!.text.trim(), 'variant': f['variant']!.text.trim(), 'sku': f['sku']!.text.trim(), 'price': price, 'stock': stock, 'description': f['description']!.text.trim(), 'keywords': f['keywords']!.text.trim(), 'art': art};
              final r = await s.saveProduct(body, sku: widget.edit?['sku'] as String?);
              if (!mounted) return;
              if (r['error'] != null) { setState(() { busy = false; error = r['error'] as String; }); } else { Navigator.pop(context); s.toast(editing ? 'Product updated' : 'Product added'); }
            }),
          ]),
        ]))),
      ),
    );
  }
}
