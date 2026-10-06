import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../logic/labels.dart';
import '../models/models.dart';
import '../models/money.dart';
import '../state/app_state.dart';
import 'customer.dart';
import 'receipt.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _tab = 0;

  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    final pages = const [CustomersTab(), TodayTab(), SyncTab()];
    return Scaffold(
      appBar: AppBar(
        title: Text(['Customers', 'Today', 'Sync'][_tab]),
        actions: [
          if (app.syncing)
            const Padding(
                padding: EdgeInsets.all(16),
                child: SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2)))
          else
            IconButton(
              tooltip: 'Sync now',
              icon: const Icon(Icons.sync),
              onPressed: () => app.syncNow(),
            ),
        ],
      ),
      body: Column(children: [
        if (app.pending > 0 || app.rejected > 0 || app.lastSyncProblem) const _Banner(),
        Expanded(child: pages[_tab]),
      ]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: [
          const NavigationDestination(icon: Icon(Icons.people_outline), label: 'Customers'),
          const NavigationDestination(icon: Icon(Icons.today_outlined), label: 'Today'),
          NavigationDestination(
            icon: Badge(
              isLabelVisible: app.pending + app.rejected > 0,
              label: Text('${app.pending + app.rejected}'),
              child: const Icon(Icons.cloud_sync_outlined),
            ),
            label: 'Sync',
          ),
        ],
      ),
    );
  }
}

class _Banner extends StatelessWidget {
  const _Banner();
  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    final scheme = Theme.of(context).colorScheme;
    final bad = app.rejected > 0;
    final text = bad
        ? '${app.rejected} payment(s) were rejected by the server. Open Sync.'
        : app.pending > 0
            ? '${app.pending} payment(s) waiting to upload (saved safely on this phone)'
            : (app.lastSyncMessage ?? '');
    return Material(
      color: bad ? scheme.errorContainer : scheme.secondaryContainer,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        child: Row(children: [
          Icon(bad ? Icons.warning_amber : Icons.cloud_off_outlined, size: 18),
          const SizedBox(width: 8),
          Expanded(child: Text(text, style: const TextStyle(fontSize: 13))),
        ]),
      ),
    );
  }
}

// ------------------------------------------------------------------ customers

class CustomersTab extends StatefulWidget {
  const CustomersTab({super.key});
  @override
  State<CustomersTab> createState() => _CustomersTabState();
}

class _CustomersTabState extends State<CustomersTab> {
  final _q = TextEditingController();
  List<Customer> _results = const [];
  int _gen = 0;

  @override
  void initState() {
    super.initState();
    _run();
  }

  Future<void> _run() async {
    final app = context.read<AppState>();
    final gen = ++_gen;
    final r = await app.db.searchCustomers(_q.text);
    if (mounted && gen == _gen) setState(() => _results = r);
  }

  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    final stamp = app.lastDownload == null
        ? 'Customers not downloaded yet. Tap sync while you have internet.'
        : '${app.customerCount} customers · downloaded ${DateFormat('d MMM, h:mm a').format(app.lastDownload!.toLocal())}';
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
        child: TextField(
          controller: _q,
          onChanged: (_) => _run(),
          textInputAction: TextInputAction.search,
          decoration: InputDecoration(
            prefixIcon: const Icon(Icons.search),
            hintText: 'Name, Internet ID, mobile, customer ID, house no',
            border: const OutlineInputBorder(),
            suffixIcon: _q.text.isEmpty
                ? null
                : IconButton(
                    icon: const Icon(Icons.clear),
                    onPressed: () {
                      _q.clear();
                      _run();
                    }),
          ),
        ),
      ),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
        child: Align(
            alignment: Alignment.centerLeft,
            child: Text(stamp, style: Theme.of(context).textTheme.bodySmall)),
      ),
      Expanded(
        child: _results.isEmpty
            ? const Center(child: Text('No customers found'))
            : ListView.separated(
                itemCount: _results.length,
                separatorBuilder: (_, __) => const Divider(height: 1),
                itemBuilder: (_, i) => CustomerTile(customer: _results[i]),
              ),
      ),
    ]);
  }
}

class CustomerTile extends StatelessWidget {
  final Customer customer;
  const CustomerTile({super.key, required this.customer});

  @override
  Widget build(BuildContext context) {
    final app = context.read<AppState>();
    final c = customer;
    return FutureBuilder<Money>(
      future: app.db.estimatedBalance(c),
      initialData: c.balance,
      builder: (context, snap) {
        final bal = snap.data ?? c.balance;
        return ListTile(
          title: Text(c.name),
          subtitle: Text([
            if (c.nameUr != null) c.nameUr!,
            [c.houseNo, c.areaName].whereType<String>().join(', '),
            if (c.connections.isNotEmpty) c.connections.map((k) => k.internetId ?? k.code).join(' · '),
          ].where((e) => e.isNotEmpty).join('\n')),
          isThreeLine: c.nameUr != null,
          trailing: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text(bal.isPositive ? bal.format() : (bal.isNegative ? 'Credit ${Money(-bal.paisa).format()}' : 'Paid'),
                style: TextStyle(
                    fontWeight: FontWeight.w600,
                    color: bal.isPositive ? Theme.of(context).colorScheme.error : Colors.green.shade700)),
            Text(c.billingStatus, style: Theme.of(context).textTheme.labelSmall),
          ]),
          onTap: () => Navigator.of(context)
              .push(MaterialPageRoute(builder: (_) => CustomerScreen(customerId: c.id))),
        );
      },
    );
  }
}

// ------------------------------------------------------------------ today

class TodayTab extends StatefulWidget {
  const TodayTab({super.key});
  @override
  State<TodayTab> createState() => _TodayTabState();
}

class _TodayTabState extends State<TodayTab> {
  Future<(List<QueuedPayment>, List<QueuedPayment>)> _load(AppState app) async =>
      (await app.db.paymentsOn(DateTime.now()), await app.db.history(limit: 200));

  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    // Rebuilds whenever counts change (a payment was added or synced).
    return FutureBuilder(
      key: ValueKey('${app.pending}-${app.rejected}-${app.customerCount}-${app.syncing}'),
      future: _load(app),
      builder: (context, snap) {
        if (!snap.hasData) return const Center(child: CircularProgressIndicator());
        final (today, all) = snap.data!;
        final total = today.fold<Money>(Money.zero, (a, p) => a + p.amount);
        final byMethod = <String, Money>{};
        for (final p in today) {
          byMethod[p.method] = (byMethod[p.method] ?? Money.zero) + p.amount;
        }
        return ListView(children: [
          Card(
            margin: const EdgeInsets.all(12),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text("Today's collection", style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 4),
                Text(total.format(), style: Theme.of(context).textTheme.headlineMedium),
                Text('${today.length} payment(s)'),
                if (byMethod.isNotEmpty) const Divider(),
                for (final e in byMethod.entries)
                  Row(mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [Text(methodLabel(e.key)), Text(e.value.format())]),
              ]),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
            child: Text('Collection history', style: Theme.of(context).textTheme.titleSmall),
          ),
          if (all.isEmpty) const Padding(padding: EdgeInsets.all(24), child: Center(child: Text('Nothing collected yet'))),
          for (final p in all) PaymentTile(payment: p),
        ]);
      },
    );
  }
}

class PaymentTile extends StatelessWidget {
  final QueuedPayment payment;
  const PaymentTile({super.key, required this.payment});

  @override
  Widget build(BuildContext context) {
    final p = payment;
    final (icon, color, label) = switch (p.state) {
      PaymentState.synced => (Icons.check_circle, Colors.green.shade700, 'Uploaded'),
      PaymentState.pending => (Icons.schedule, Colors.orange.shade800, 'Waiting to upload'),
      PaymentState.rejected => (Icons.error, Theme.of(context).colorScheme.error, 'Rejected'),
    };
    final when = DateFormat('d MMM, h:mm a').format(DateTime.parse(p.collectedAt).toLocal());
    return ListTile(
      leading: Icon(icon, color: color),
      title: Text('${p.customerName}  ·  ${p.amount.format()}'),
      subtitle: Text('${p.displayReceipt} · ${methodLabel(p.method)} · $when\n$label'
          '${p.state == PaymentState.rejected && p.reason != null ? ': ${p.reason}' : ''}'),
      isThreeLine: true,
      onTap: () => Navigator.of(context)
          .push(MaterialPageRoute(builder: (_) => ReceiptScreen(clientTxnId: p.clientTxnId))),
    );
  }
}

// ------------------------------------------------------------------ sync

class SyncTab extends StatelessWidget {
  const SyncTab({super.key});

  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    return FutureBuilder<List<QueuedPayment>>(
      key: ValueKey('${app.pending}-${app.rejected}-${app.syncing}'),
      future: app.db.history(limit: 500),
      builder: (context, snap) {
        final all = snap.data ?? const <QueuedPayment>[];
        final waiting = all.where((p) => p.state == PaymentState.pending).toList();
        final rejected = all.where((p) => p.state == PaymentState.rejected).toList();
        return ListView(children: [
          Card(
            margin: const EdgeInsets.all(12),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(app.syncing ? 'Syncing…' : (app.lastSyncMessage ?? 'Ready to sync'),
                    style: TextStyle(
                        color: app.lastSyncProblem ? Theme.of(context).colorScheme.error : null)),
                const SizedBox(height: 8),
                Text('${app.customerCount} customers on this phone'),
                Text(app.lastDownload == null
                    ? 'Never downloaded'
                    : 'Last download: ${DateFormat('d MMM, h:mm a').format(app.lastDownload!.toLocal())}'),
                const SizedBox(height: 12),
                FilledButton.icon(
                  onPressed: app.syncing ? null : () => app.syncNow(),
                  icon: const Icon(Icons.sync),
                  label: const Text('Upload payments and refresh customers'),
                ),
                const SizedBox(height: 8),
                const Text('Do this with internet before you leave, and again when you are back.',
                    style: TextStyle(fontSize: 12)),
              ]),
            ),
          ),
          if (rejected.isNotEmpty) ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: Text('Rejected by the server (${rejected.length})',
                  style: TextStyle(
                      fontWeight: FontWeight.bold, color: Theme.of(context).colorScheme.error)),
            ),
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 4, 16, 8),
              child: Text(
                  'The cash was collected but the server cannot record it as sent. Keep the cash and '
                  'the paper receipt and give both to the office with the details below.'),
            ),
            for (final p in rejected) PaymentTile(payment: p),
          ],
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: Text('Waiting to upload (${waiting.length})',
                style: const TextStyle(fontWeight: FontWeight.bold)),
          ),
          if (waiting.isEmpty)
            const Padding(padding: EdgeInsets.all(16), child: Text('Nothing waiting.')),
          for (final p in waiting) PaymentTile(payment: p),
        ]);
      },
    );
  }
}
