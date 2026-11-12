import 'package:flutter/material.dart';
import '../brand/icons.dart';
import '../brand/theme.dart';
import '../widgets/kit.dart';

/// Numbered "how to connect" steps. Used on every connection so nobody has to guess where a key comes from.
class GuideSteps extends StatelessWidget {
  const GuideSteps({super.key, required this.steps, this.where});
  final List<String> steps;
  final String? where;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (where != null) Padding(padding: const EdgeInsets.only(bottom: 10), child: Row(children: [Icon(PhosphorIconsRegular.mapPin, size: 14, color: c.text3), const SizedBox(width: 6), Expanded(child: Text('Where: $where', style: TypeX.ui(12.5, w: FontWeight.w700, color: c.text2)))])),
      for (var i = 0; i < steps.length; i++)
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(width: 22, height: 22, alignment: Alignment.center, decoration: BoxDecoration(color: c.primarySoft, shape: BoxShape.circle), child: Text('${i + 1}', style: TypeX.ui(11.5, w: FontWeight.w800, color: c.primary))),
            const SizedBox(width: 10),
            Expanded(child: Padding(padding: const EdgeInsets.only(top: 2), child: Text(steps[i], style: TypeX.ui(13, color: c.text2, h: 1.5)))),
          ]),
        ),
    ]);
  }
}

/// A collapsed-by-default box holding the steps, for use inside dialogs and pages.
class HowToConnect extends StatefulWidget {
  const HowToConnect({super.key, required this.steps, this.where, this.open = false, this.title = 'How to connect'});
  final List<String> steps;
  final String? where, title;
  final bool open;
  @override
  State<HowToConnect> createState() => _HowToConnectState();
}

class _HowToConnectState extends State<HowToConnect> {
  late bool open = widget.open;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      margin: const EdgeInsets.only(bottom: 14),
      decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(14), border: Border.all(color: c.line)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Hover(
          onTap: () => setState(() => open = !open),
          builder: (_, h, __) => Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            child: Row(children: [
              Icon(PhosphorIconsFill.lightbulb, size: 16, color: c.primary), const SizedBox(width: 8),
              Expanded(child: Text(widget.title ?? 'How to connect', style: TypeX.ui(13.5, w: FontWeight.w800, color: h ? c.primary : c.text))),
              Icon(open ? PhosphorIconsBold.caretUp : PhosphorIconsBold.caretDown, size: 14, color: c.text3),
            ]),
          ),
        ),
        if (open) Padding(padding: const EdgeInsets.fromLTRB(14, 0, 14, 4), child: GuideSteps(steps: widget.steps, where: widget.where)),
      ]),
    );
  }
}

const metaGuide = [
  'Go to developers.facebook.com and create an app (or open the one you have). Add the products you need: WhatsApp, Messenger and/or Instagram.',
  'Come back to the Meta app card on this page and press Set up Meta app. Enter the App ID and App secret (App settings, Basic), your public https address, and press Generate for a verify token.',
  'Meta only delivers messages to a public https address. While developing, use a tunnel (for example ngrok or Cloudflare Tunnel) and paste its https address.',
  'In the Meta dashboard, open the webhook settings of each product. Paste the Callback URL and the Verify token from Dakbox, then subscribe to the messages field (Messenger also: message_deliveries, message_reads).',
  'Press Connect a real account on a channel card and paste what it asks for: WhatsApp needs the Phone number ID, the Business Account ID and a System User token; Messenger needs the Page ID and a Page access token; Instagram needs the account ID and a token.',
  'Send a test message to that account. It should appear in the Inbox. If not, the Recent webhook activity list explains why (bad signature, unknown account, or nothing arriving).',
];

const webChatGuide = [
  'Web chat needs no account. Your website visitors chat through this business’s widget page (shown under Assistant, Try it, Embed on your site).',
  'To put it on your site, link or embed that page (for example in an iframe) from your website.',
  'Everything else works the same: the assistant answers, and staff see the chat in the Inbox.',
];

const groupGuides = <String, List<String>>{
  'Couriers': [
    'A courier connection lets you book a real parcel from an order, collect cash on delivery, and follow the parcel to the door.',
    'Pick a courier card below and press Connect. Each Connect window lists exactly where to find the details it asks for.',
    'Dakbox checks the details with the courier before it saves anything, and stores them encrypted. They are never shown again.',
    'Then open an order, press Book a courier, check the cash amount, and confirm. Until a courier is connected, orders only get a labelled demo parcel.',
    'Pathao, RedX, Paperfly and eCourier are not built yet because their API documentation could not be read. Ask them for it.',
  ],
  'Payments': [
    'Cash on delivery needs no setup. Online payments (cards, bKash and others) are sent as a secure payment link in the chat or from an order.',
    'Pick a provider below and press Connect. Start with Sandbox so no real money moves, and make a test payment.',
    'Each gateway needs a public https address to reach you. Set it once under Channels, Meta app: it is shared with WhatsApp and Messenger.',
    'Use Setup URLs on a connected card to see the addresses to paste into the provider’s panel.',
    'A payment only counts after the provider confirms it directly to Dakbox. A redirect or webhook alone is never believed.',
  ],
  'SMS': [
    'SMS tells customers when an order is placed, shipped, delivered or refunded. Pick SSL Wireless or Alpha SMS below and press Connect.',
    'You need your own account with that company first: Dakbox does not sell SMS. Each Connect window says where to find the key.',
    'After connecting, open the Notifications tab and switch on SMS for the events you want. Automatic messages wait overnight (quiet hours) and are capped per number and per day.',
    'Use Send test SMS on a connected card to check it. “Accepted” means the company took the message; only Alpha SMS reports “Delivered”.',
  ],
  'Store': [
    'Dakbox keeps its own catalog, stock and orders, so you do not need a store platform to use it. Orders come from chats, the website chat and your team.',
    'To bring in products from your website (Shopify, WooCommerce or any shop website), connect it below. Dakbox shows what it found before saving anything.',
  ],
};

const notificationsGuide = [
  'Each row is an event. Switch on the channel you want to tell the customer by.',
  'SMS only goes out if an SMS provider is connected (Connections, SMS). With none connected the message shows as “Not sent” on the order.',
  'Automatic SMS wait until 08:00 Bangladesh time during quiet hours. Change the hours and the per-number limits under Connections, SMS.',
  'WhatsApp and Email here are records only for now; the assistant’s replies in chat are separate and always on.',
];

const overviewGuide = [
  'Channels are where customers write to you (WhatsApp, Messenger, Instagram, your website). Couriers, Payments and SMS are the services your team and the assistant use after that.',
  'Start with one channel and Sandbox or test modes. Every Connect window lists where to find the details, and checks them with the other company before saving.',
  'Secrets are stored encrypted and never shown again. Only owners and admins can connect or disconnect.',
  'Meta channels and online payments need a public https address (a real domain or a tunnel such as ngrok). Set it once under Channels, Meta app.',
  'Nothing here is live until the card says Connected. Cards marked “Not built” are honest placeholders.',
];
