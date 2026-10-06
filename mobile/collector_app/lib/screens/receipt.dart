import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../logic/labels.dart';
import '../models/models.dart';
import '../models/money.dart';
import '../state/app_state.dart';

/// Receipt for a payment collected on this phone. Available immediately, with no signal.
/// Until the payment uploads, the number is the provisional one (OFF-...); after upload the
/// permanent server receipt number is shown, with the provisional one kept for reference.
class ReceiptScreen extends StatefulWidget {
  final String clientTxnId;
  const ReceiptScreen({super.key, required this.clientTxnId});
  @override
  State<ReceiptScreen> createState() => _ReceiptScreenState();
}

class _ReceiptScreenState extends State<ReceiptScreen> {
  QueuedPayment? _p;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final p = await context.read<AppState>().db.payment(widget.clientTxnId);
    if (mounted) setState(() => _p = p);
  }

  String _text(QueuedPayment p) {
    final when = DateFormat('d MMM yyyy, h:mm a').format(DateTime.parse(p.collectedAt).toLocal());
    return [
      'Receipt ${p.displayReceipt}',
      if (p.serverReceiptNo != null) '(paper no. ${p.clientReceiptNo})',
      p.customerName,
      'ID ${p.customerCode}',
      'Amount ${p.amount.format()} (${methodLabel(p.method)})',
      if (p.balanceAfter != null)
        p.balanceAfter!.isPositive
            ? 'Balance after: ${p.balanceAfter!.format()}'
            : 'Balance after: ${p.balanceAfter!.isNegative ? 'credit ${Money(-p.balanceAfter!.paisa).format()}' : 'paid'}',
      when,
    ].join('\n');
  }

  @override
  Widget build(BuildContext context) {
    final p = _p;
    if (p == null) return Scaffold(appBar: AppBar(), body: const Center(child: CircularProgressIndicator()));
    final scheme = Theme.of(context).colorScheme;
    final (label, color) = switch (p.state) {
      PaymentState.synced => ('Uploaded to the office system', Colors.green.shade700),
      PaymentState.pending => ('Saved on this phone, not uploaded yet', Colors.orange.shade800),
      PaymentState.rejected => ('REJECTED by the server', scheme.error),
    };
    final when = DateFormat('d MMM yyyy, h:mm a').format(DateTime.parse(p.collectedAt).toLocal());
    return Scaffold(
      appBar: AppBar(title: const Text('Receipt')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Center(child: Text('PAYMENT RECEIVED', style: Theme.of(context).textTheme.titleMedium)),
              const SizedBox(height: 12),
              Center(child: Text(p.amount.format(), style: Theme.of(context).textTheme.displaySmall)),
              const Divider(height: 32),
              _line('Receipt no', p.displayReceipt),
              if (p.serverReceiptNo != null) _line('Paper receipt no', p.clientReceiptNo),
              _line('Customer', p.customerName),
              _line('Customer ID', p.customerCode),
              _line('Method', methodLabel(p.method)),
              _line('Date', when),
              if (p.balanceAfter != null)
                _line(
                    'Balance after',
                    p.balanceAfter!.isPositive
                        ? p.balanceAfter!.format()
                        : (p.balanceAfter!.isNegative
                            ? 'Credit ${Money(-p.balanceAfter!.paisa).format()}'
                            : 'Paid in full')),
              if (p.notes != null) _line('Note', p.notes!),
            ]),
          ),
        ),
        const SizedBox(height: 8),
        Row(children: [
          Icon(p.state == PaymentState.synced ? Icons.check_circle : Icons.info_outline, color: color, size: 18),
          const SizedBox(width: 8),
          Expanded(child: Text(label, style: TextStyle(color: color, fontWeight: FontWeight.w600))),
        ]),
        if (p.state == PaymentState.rejected) ...[
          const SizedBox(height: 8),
          Text('${p.reason ?? 'The server could not accept this payment.'}\n'
              'Keep the cash and this receipt and hand both to the office.'),
        ],
        if (p.state == PaymentState.pending && p.lastError != null) ...[
          const SizedBox(height: 4),
          Text('Last upload attempt: ${p.lastError}', style: Theme.of(context).textTheme.bodySmall),
        ],
        const SizedBox(height: 16),
        OutlinedButton.icon(
          onPressed: () async {
            await Clipboard.setData(ClipboardData(text: _text(p)));
            if (context.mounted) {
              ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Receipt copied')));
            }
          },
          icon: const Icon(Icons.copy),
          label: const Text('Copy receipt text'),
        ),
        const SizedBox(height: 8),
        // Bluetooth thermal printing (58/80 mm, Urdu shaping) is built in the next phase.
        const OutlinedButton(
          onPressed: null,
          child: Text('Print receipt (coming in the printing update)'),
        ),
      ]),
    );
  }

  Widget _line(String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 130, child: Text(k, style: Theme.of(context).textTheme.bodySmall)),
          Expanded(child: Text(v, style: const TextStyle(fontWeight: FontWeight.w600))),
        ]),
      );
}
