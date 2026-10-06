import '../models/models.dart';
import 'stores.dart';

class UploadReport {
  int synced = 0; // newly stored on the server
  int duplicates = 0; // server already had them (harmless, now marked synced)
  int rejected = 0; // server will never accept them: needs the office
  int retry = 0; // temporary server error: will be retried
  bool offline = false; // could not reach the server at all
  int get uploaded => synced + duplicates;
  bool get nothingToDo => synced + duplicates + rejected + retry == 0 && !offline;
}

/// Moves payments up and customers down. Safe to call at any time, any number of times:
/// the server de-duplicates by client transaction id, so a lost response only means a harmless retry.
class SyncService {
  final PaymentStore payments;
  final CustomerStore customers;
  final RemoteApi api;
  final int batchSize;

  SyncService({
    required this.payments,
    required this.customers,
    required this.api,
    this.batchSize = 50,
  });

  bool _busy = false;

  /// Uploads every pending payment, oldest first, in batches.
  Future<UploadReport> uploadPending() async {
    final report = UploadReport();
    if (_busy) return report;
    _busy = true;
    try {
      // Items answered ERROR stay pending; remember them so one stubborn item cannot loop forever.
      final skip = <String>{};
      while (true) {
        final pending = (await payments.pendingPayments(limit: batchSize + skip.length))
            .where((p) => !skip.contains(p.clientTxnId))
            .take(batchSize)
            .toList();
        if (pending.isEmpty) break;

        final List<SyncResult> results;
        try {
          results = await api.syncPayments(pending);
        } on OfflineException {
          report.offline = true; // everything stays PENDING
          break;
        }

        final byTxn = {for (final r in results) r.clientTxnId: r};
        for (final p in pending) {
          final r = byTxn[p.clientTxnId];
          if (r == null) {
            // No answer for this item: leave it pending and try again next time.
            await payments.recordFailedAttempt(p.clientTxnId, 'no answer from server');
            skip.add(p.clientTxnId);
            report.retry++;
            continue;
          }
          switch (r.status) {
            case 'SYNCED':
              await payments.markSynced(p.clientTxnId,
                  serverReceiptNo: r.receiptNumber, serverPaymentId: r.paymentId);
              report.synced++;
            case 'DUPLICATE':
              await payments.markSynced(p.clientTxnId,
                  serverReceiptNo: r.receiptNumber, serverPaymentId: r.paymentId);
              report.duplicates++;
            case 'REJECTED':
              await payments.markRejected(p.clientTxnId, code: r.code, reason: r.reason);
              report.rejected++;
            default: // ERROR or anything unknown: keep it, retry later
              await payments.recordFailedAttempt(p.clientTxnId, r.reason ?? r.status);
              skip.add(p.clientTxnId);
              report.retry++;
          }
        }
      }
    } finally {
      _busy = false;
    }
    return report;
  }

  /// Downloads all assigned customers. The old list is replaced only after every page arrived,
  /// so a connection that drops half way never leaves the phone with a partial customer list.
  Future<DateTime> downloadSnapshot({int pageSize = 300}) async {
    var page = await api.fetchSnapshot(offset: 0, limit: pageSize);
    final generatedAt = page.generatedAt;
    final all = <Customer>[...page.customers];
    while (page.customers.isNotEmpty && all.length < page.total) {
      page = await api.fetchSnapshot(offset: all.length, limit: pageSize);
      all.addAll(page.customers);
    }
    await customers.replaceCustomers(all, generatedAt);
    return generatedAt;
  }

  /// What the collector does before leaving and when signal returns: send first, then refresh.
  Future<UploadReport> fullSync() async {
    final report = await uploadPending();
    if (!report.offline) {
      await downloadSnapshot();
    }
    return report;
  }
}
