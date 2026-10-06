import 'package:isp_collector/data/stores.dart';
import 'package:isp_collector/models/models.dart';
import 'package:isp_collector/models/money.dart';

QueuedPayment payment(String txn, {String receipt = 'OFF-C01-0001', String amount = '500.00'}) =>
    QueuedPayment(
      clientTxnId: txn,
      clientReceiptNo: receipt,
      customerId: 'cust-1',
      customerName: 'Ali Khan',
      customerCode: 'CU-000001',
      amount: Money.parse(amount),
      method: 'COLLECTOR_CASH',
      collectedAt: '2026-10-03T05:00:00.000Z',
    );

Customer customer(String id, {String name = 'Ali Khan'}) => Customer(
      id: id,
      code: 'CU-$id',
      name: name,
      balance: Money.parse('1000'),
      amountDue: Money.parse('1000'),
      credit: Money.zero,
      billingStatus: 'DUE',
    );

/// In-memory stand-in for the SQLite store with the same rules (no delete, only sync fields move).
class FakeStore implements PaymentStore, CustomerStore {
  final List<QueuedPayment> rows = [];
  List<Customer> customers = [];
  DateTime? stamp;

  void add(QueuedPayment p) => rows.add(p);

  QueuedPayment byTxn(String txn) => rows.firstWhere((p) => p.clientTxnId == txn);

  void _update(String txn, QueuedPayment Function(QueuedPayment) f) {
    final i = rows.indexWhere((p) => p.clientTxnId == txn);
    rows[i] = f(rows[i]);
  }

  QueuedPayment _copy(QueuedPayment p,
          {PaymentState? state, String? srv, String? payId, String? code, String? reason, int? attempts, String? err}) =>
      QueuedPayment(
        clientTxnId: p.clientTxnId,
        clientReceiptNo: p.clientReceiptNo,
        customerId: p.customerId,
        customerName: p.customerName,
        customerCode: p.customerCode,
        amount: p.amount,
        method: p.method,
        collectedAt: p.collectedAt,
        connectionId: p.connectionId,
        notes: p.notes,
        balanceAfter: p.balanceAfter,
        seq: p.seq,
        state: state ?? p.state,
        serverReceiptNo: srv ?? p.serverReceiptNo,
        serverPaymentId: payId ?? p.serverPaymentId,
        code: code,
        reason: reason,
        attempts: attempts ?? p.attempts,
        lastError: err,
      );

  @override
  Future<List<QueuedPayment>> pendingPayments({int limit = 50}) async =>
      rows.where((p) => p.state == PaymentState.pending).take(limit).toList();

  @override
  Future<void> markSynced(String t, {String? serverReceiptNo, String? serverPaymentId}) async =>
      _update(t, (p) => _copy(p, state: PaymentState.synced, srv: serverReceiptNo, payId: serverPaymentId));

  @override
  Future<void> markRejected(String t, {String? code, String? reason}) async =>
      _update(t, (p) => _copy(p, state: PaymentState.rejected, code: code, reason: reason));

  @override
  Future<void> recordFailedAttempt(String t, String error) async =>
      _update(t, (p) => _copy(p, attempts: p.attempts + 1, err: error));

  @override
  Future<void> replaceCustomers(List<Customer> c, DateTime generatedAt) async {
    customers = List.of(c);
    stamp = generatedAt;
  }
}

/// A server that behaves like the real one: remembers client transaction ids.
class FakeServer implements RemoteApi {
  final Map<String, String> receiptByTxn = {}; // txn -> server receipt
  final Set<String> rejectTxns = {};
  final Set<String> errorTxns = {};
  bool offline = false;
  bool dropResponse = false; // server stores the payments but the phone never hears back
  int calls = 0;
  int snapshotCalls = 0;
  List<Customer> snapshot = [];
  int failSnapshotAtPage = -1;

  int get stored => receiptByTxn.length;

  @override
  Future<List<SyncResult>> syncPayments(List<QueuedPayment> batch) async {
    calls++;
    if (offline) throw OfflineException();
    final out = <SyncResult>[];
    for (final p in batch) {
      if (rejectTxns.contains(p.clientTxnId)) {
        out.add(SyncResult(clientTxnId: p.clientTxnId, status: 'REJECTED', code: 'NOT_ASSIGNED', reason: 'not yours'));
      } else if (errorTxns.contains(p.clientTxnId)) {
        out.add(SyncResult(clientTxnId: p.clientTxnId, status: 'ERROR', code: 'SERVER_ERROR', reason: 'try later'));
      } else if (receiptByTxn.containsKey(p.clientTxnId)) {
        out.add(SyncResult(
            clientTxnId: p.clientTxnId, status: 'DUPLICATE', receiptNumber: receiptByTxn[p.clientTxnId], paymentId: 'pay-${p.clientTxnId}'));
      } else {
        final r = 'RC-${(receiptByTxn.length + 1).toString().padLeft(6, '0')}';
        receiptByTxn[p.clientTxnId] = r;
        out.add(SyncResult(clientTxnId: p.clientTxnId, status: 'SYNCED', receiptNumber: r, paymentId: 'pay-${p.clientTxnId}'));
      }
    }
    if (dropResponse) throw OfflineException('connection dropped');
    return out;
  }

  @override
  Future<SnapshotPage> fetchSnapshot({required int offset, required int limit}) async {
    snapshotCalls++;
    if (offline) throw OfflineException();
    if (failSnapshotAtPage >= 0 && offset ~/ limit == failSnapshotAtPage) throw OfflineException();
    final page = snapshot.skip(offset).take(limit).toList();
    return SnapshotPage(DateTime.utc(2026, 10, 4, 8), snapshot.length, offset, page);
  }
}
