import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../logic/labels.dart';
import '../models/models.dart';
import '../models/money.dart';
import '../state/app_state.dart';
import 'home.dart' show PaymentTile;
import 'receipt.dart';

class CustomerScreen extends StatefulWidget {
  final String customerId;
  const CustomerScreen({super.key, required this.customerId});
  @override
  State<CustomerScreen> createState() => _CustomerScreenState();
}

class _CustomerScreenState extends State<CustomerScreen> {
  Customer? _c;
  Money _balance = Money.zero;
  List<QueuedPayment> _mine = const [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final app = context.read<AppState>();
    final c = await app.db.customer(widget.customerId);
    if (c == null) return;
    final bal = await app.db.estimatedBalance(c);
    final mine = await app.db.history(customerId: c.id, limit: 20);
    if (mounted) setState(() => (_c, _balance, _mine) = (c, bal, mine));
  }

  Future<void> _collect() async {
    final c = _c!;
    final paid = await Navigator.of(context)
        .push<QueuedPayment>(MaterialPageRoute(builder: (_) => CollectScreen(customer: c, balance: _balance)));
    if (paid != null && mounted) {
      await _load();
      if (!mounted) return;
      await Navigator.of(context)
          .push(MaterialPageRoute(builder: (_) => ReceiptScreen(clientTxnId: paid.clientTxnId)));
      await _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = _c;
    if (c == null) return Scaffold(appBar: AppBar(), body: const Center(child: CircularProgressIndicator()));
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: Text(c.name)),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _collect,
        icon: const Icon(Icons.payments),
        label: const Text('Collect payment'),
      ),
      body: ListView(padding: const EdgeInsets.only(bottom: 96), children: [
        Card(
          margin: const EdgeInsets.all(12),
          color: _balance.isPositive ? scheme.errorContainer : scheme.primaryContainer,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(_balance.isPositive ? 'Amount due' : (_balance.isNegative ? 'Advance credit' : 'All paid')),
              Text(
                _balance.isNegative ? Money(-_balance.paisa).format() : _balance.format(),
                style: Theme.of(context).textTheme.headlineLarge,
              ),
              Text('Status: ${c.billingStatus}'
                  '${c.oldestDueDate != null && _balance.isPositive ? ' · oldest due ${c.oldestDueDate}' : ''}'),
              if (_balance != c.balance)
                const Padding(
                  padding: EdgeInsets.only(top: 4),
                  child: Text('Includes payments collected on this phone since the last download.',
                      style: TextStyle(fontSize: 12)),
                ),
            ]),
          ),
        ),
        _Section('Customer', [
          _Row('Name', c.name),
          if (c.nameUr != null) _Row('نام', c.nameUr!, rtl: true),
          _Row('Customer ID', c.code),
          if (c.mobile != null) _Row('Mobile', c.mobile!),
          if (c.whatsapp != null && c.whatsapp != c.mobile) _Row('WhatsApp', c.whatsapp!),
          if (c.houseNo != null) _Row('House no', c.houseNo!),
          if (c.areaName != null) _Row('Area', c.areaName!),
          if (c.address != null) _Row('Address', c.address!),
          if (c.addressUr != null) _Row('پتہ', c.addressUr!, rtl: true),
        ]),
        for (final k in c.connections)
          _Section('Connection ${k.code}', [
            if (k.internetId != null) _Row('Internet ID', k.internetId!),
            _Row('Type', k.type),
            if (k.packageName != null) _Row('Package', k.packageName!),
            if (k.packageNameUr != null) _Row('پیکیج', k.packageNameUr!, rtl: true),
            if (k.monthlyCharge != null) _Row('Monthly', k.monthlyCharge!.format()),
            if (k.nextDueDate != null) _Row('Next due', k.nextDueDate!),
            _Row('Status', k.status),
          ]),
        _Section('Open bills', [
          if (c.openInvoices.isEmpty) const Padding(padding: EdgeInsets.all(8), child: Text('No unpaid bills')),
          for (final i in c.openInvoices)
            _Row('${i.number} · due ${i.dueDate}', '${i.outstanding.format()}  ${i.status}'),
        ]),
        if (_mine.isNotEmpty) ...[
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            child: Text('Collected by you', style: Theme.of(context).textTheme.titleSmall),
          ),
          for (final p in _mine) PaymentTile(payment: p),
        ],
      ]),
    );
  }
}

class _Section extends StatelessWidget {
  final String title;
  final List<Widget> children;
  const _Section(this.title, this.children);
  @override
  Widget build(BuildContext context) => Card(
        margin: const EdgeInsets.fromLTRB(12, 0, 12, 12),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 4),
            ...children,
          ]),
        ),
      );
}

class _Row extends StatelessWidget {
  final String label;
  final String value;
  final bool rtl;
  const _Row(this.label, this.value, {this.rtl = false});
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 120, child: Text(label, style: Theme.of(context).textTheme.bodySmall)),
          Expanded(
            child: Text(value,
                textDirection: rtl ? TextDirection.rtl : null,
                textAlign: rtl ? TextAlign.right : TextAlign.start),
          ),
        ]),
      );
}

// ------------------------------------------------------------------ collect

class CollectScreen extends StatefulWidget {
  final Customer customer;
  final Money balance;
  const CollectScreen({super.key, required this.customer, required this.balance});
  @override
  State<CollectScreen> createState() => _CollectScreenState();
}

class _CollectScreenState extends State<CollectScreen> {
  late final TextEditingController _amount;
  final _notes = TextEditingController();
  String _method = 'COLLECTOR_CASH';
  String? _connectionId;
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    final due = widget.balance.isPositive ? widget.balance : Money.zero;
    _amount = TextEditingController(text: due.isZero ? '' : due.toApi());
  }

  Future<void> _save() async {
    final amount = Money.tryParse(_amount.text);
    if (amount == null || !amount.isPositive) {
      setState(() => _error = 'Enter a valid amount, for example 1500 or 1500.50');
      return;
    }
    // Large overpayments are usually a typo (an extra zero): ask before saving.
    if (amount > widget.balance.max(Money.zero) + const Money(100000) && amount > const Money(500000)) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (_) => AlertDialog(
          title: const Text('Check the amount'),
          content: Text('${amount.format()} is much more than the ${widget.balance.max(Money.zero).format()} due. '
              'Save it anyway? The extra will be kept as advance credit.'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Go back')),
            FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Save')),
          ],
        ),
      );
      if (ok != true) return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final p = await context.read<AppState>().collect(
            customer: widget.customer,
            amount: amount,
            method: _method,
            connectionId: _connectionId,
            notes: _notes.text.trim().isEmpty ? null : _notes.text.trim(),
          );
      if (mounted) Navigator.of(context).pop(p);
    } catch (e) {
      setState(() {
        _busy = false;
        _error = 'Could not save the payment on this phone: $e';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.customer;
    final billable = c.connections.where((k) => k.status != 'DISCONNECTED').toList();
    return Scaffold(
      appBar: AppBar(title: const Text('Collect payment')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Text(c.name, style: Theme.of(context).textTheme.titleLarge),
        Text('Due now: ${widget.balance.max(Money.zero).format()}'),
        const SizedBox(height: 16),
        TextField(
          controller: _amount,
          autofocus: true,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          style: Theme.of(context).textTheme.headlineSmall,
          decoration: const InputDecoration(labelText: 'Amount received (Rs)', border: OutlineInputBorder()),
        ),
        const SizedBox(height: 16),
        DropdownButtonFormField<String>(
          value: _method,
          decoration: const InputDecoration(labelText: 'Payment method', border: OutlineInputBorder()),
          items: [for (final m in collectorMethods) DropdownMenuItem(value: m, child: Text(methodLabel(m)))],
          onChanged: (v) => setState(() => _method = v ?? _method),
        ),
        if (billable.length > 1) ...[
          const SizedBox(height: 16),
          DropdownButtonFormField<String?>(
            value: _connectionId,
            decoration: const InputDecoration(labelText: 'For connection (optional)', border: OutlineInputBorder()),
            items: [
              const DropdownMenuItem(value: null, child: Text('Whole account (oldest bill first)')),
              for (final k in billable)
                DropdownMenuItem(value: k.id, child: Text('${k.internetId ?? k.code} ${k.packageName ?? ''}')),
            ],
            onChanged: (v) => setState(() => _connectionId = v),
          ),
        ],
        const SizedBox(height: 16),
        TextField(
          controller: _notes,
          decoration: const InputDecoration(labelText: 'Note (optional)', border: OutlineInputBorder()),
        ),
        if (_error != null) ...[
          const SizedBox(height: 12),
          Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
        ],
        const SizedBox(height: 24),
        FilledButton.icon(
          onPressed: _busy ? null : _save,
          icon: const Icon(Icons.check),
          label: const Padding(padding: EdgeInsets.all(12), child: Text('Save payment')),
        ),
        const SizedBox(height: 8),
        const Text('Saved on this phone immediately. It uploads by itself when there is internet.',
            style: TextStyle(fontSize: 12)),
      ]),
    );
  }
}
