import 'package:flutter_test/flutter_test.dart';
import 'package:isp_collector/data/stores.dart';
import 'package:isp_collector/data/sync_service.dart';
import 'package:isp_collector/models/models.dart';

import 'fakes.dart';

SyncService svc(FakeStore s, FakeServer api, {int batch = 50}) =>
    SyncService(payments: s, customers: s, api: api, batchSize: batch);

void main() {
  late FakeStore store;
  late FakeServer server;

  setUp(() {
    store = FakeStore();
    server = FakeServer();
  });

  test('offline payment stays pending and nothing is lost', () async {
    store.add(payment('txn-00000001'));
    server.offline = true;
    final r = await svc(store, server).uploadPending();
    expect(r.offline, isTrue);
    expect(store.byTxn('txn-00000001').state, PaymentState.pending);
    expect(server.stored, 0);
  });

  test('successful sync marks it synced and keeps both receipt numbers', () async {
    store.add(payment('txn-00000001', receipt: 'OFF-C01-0001'));
    final r = await svc(store, server).uploadPending();
    expect(r.synced, 1);
    final p = store.byTxn('txn-00000001');
    expect(p.state, PaymentState.synced);
    expect(p.serverReceiptNo, 'RC-000001');
    expect(p.clientReceiptNo, 'OFF-C01-0001'); // the paper number is never lost
    expect(p.displayReceipt, 'RC-000001');
  });

  test('receipt before sync: the paper number is shown until the server number exists', () {
    final p = payment('txn-00000001', receipt: 'OFF-C01-0009');
    expect(p.state, PaymentState.pending);
    expect(p.displayReceipt, 'OFF-C01-0009');
  });

  test('duplicate sync never creates a second payment on the server', () async {
    store.add(payment('txn-00000001'));
    await svc(store, server).uploadPending();
    // The phone lost the answer, so it believes the payment is still pending.
    final again = FakeStore()..add(payment('txn-00000001'));
    final r = await svc(again, server).uploadPending();
    expect(r.duplicates, 1);
    expect(server.stored, 1);
    expect(again.byTxn('txn-00000001').state, PaymentState.synced);
    expect(again.byTxn('txn-00000001').serverReceiptNo, 'RC-000001');
  });

  test('failed sync (response lost) is retried and still stored only once', () async {
    store.add(payment('txn-00000001'));
    server.dropResponse = true;
    final first = await svc(store, server).uploadPending();
    expect(first.offline, isTrue);
    expect(store.byTxn('txn-00000001').state, PaymentState.pending);
    expect(server.stored, 1); // the server did get it

    server.dropResponse = false;
    final retry = await svc(store, server).uploadPending();
    expect(retry.duplicates, 1);
    expect(store.byTxn('txn-00000001').state, PaymentState.synced);
    expect(server.stored, 1);
  });

  test('retry after coming back online uploads everything in order', () async {
    for (var i = 1; i <= 5; i++) {
      store.add(payment('txn-0000000$i', receipt: 'OFF-C01-000$i'));
    }
    server.offline = true;
    await svc(store, server).uploadPending();
    server.offline = false;
    final r = await svc(store, server).uploadPending();
    expect(r.synced, 5);
    expect(store.rows.every((p) => p.state == PaymentState.synced), isTrue);
    expect(server.receiptByTxn.keys.toList(), ['txn-00000001', 'txn-00000002', 'txn-00000003', 'txn-00000004', 'txn-00000005']);
  });

  test('a rejected payment is kept and flagged, and does not block the others', () async {
    store
      ..add(payment('txn-00000001'))
      ..add(payment('txn-00000002', receipt: 'OFF-C01-0002'))
      ..add(payment('txn-00000003', receipt: 'OFF-C01-0003'));
    server.rejectTxns.add('txn-00000002');
    final r = await svc(store, server).uploadPending();
    expect((r.synced, r.rejected), (2, 1));
    final bad = store.byTxn('txn-00000002');
    expect(bad.state, PaymentState.rejected);
    expect(bad.reason, 'not yours');
    expect(store.rows.length, 3); // nothing was deleted
    // A rejected payment is never re-sent.
    final calls = server.calls;
    await svc(store, server).uploadPending();
    expect(server.calls, calls);
  });

  test('a temporary server error leaves the payment pending for the next sync', () async {
    store.add(payment('txn-00000001'));
    server.errorTxns.add('txn-00000001');
    final r = await svc(store, server).uploadPending();
    expect(r.retry, 1);
    final p = store.byTxn('txn-00000001');
    expect(p.state, PaymentState.pending);
    expect(p.attempts, 1);

    server.errorTxns.clear();
    expect((await svc(store, server).uploadPending()).synced, 1);
  });

  test('a stubborn failing payment does not loop forever or block later ones', () async {
    store
      ..add(payment('txn-00000001'))
      ..add(payment('txn-00000002', receipt: 'OFF-C01-0002'));
    server.errorTxns.add('txn-00000001');
    final r = await svc(store, server, batch: 1).uploadPending();
    expect((r.synced, r.retry), (1, 1));
    expect(store.byTxn('txn-00000002').state, PaymentState.synced);
  });

  test('uploads in batches', () async {
    for (var i = 1; i <= 7; i++) {
      store.add(payment('txn-0000000$i', receipt: 'OFF-C01-000$i'));
    }
    final r = await svc(store, server, batch: 3).uploadPending();
    expect(r.synced, 7);
    expect(server.calls, 3);
  });

  test('download replaces the customer list only after every page arrived', () async {
    store.customers = [customer('old')];
    server.snapshot = [for (var i = 0; i < 5; i++) customer('c$i')];
    server.failSnapshotAtPage = 1;
    await expectLater(svc(store, server).downloadSnapshot(pageSize: 2), throwsA(isA<OfflineException>()));
    expect(store.customers.map((c) => c.id), ['old']); // untouched

    server.failSnapshotAtPage = -1;
    await svc(store, server).downloadSnapshot(pageSize: 2);
    expect(store.customers.length, 5);
    expect(store.stamp, DateTime.utc(2026, 10, 4, 8));
  });

  test('full sync uploads first and does not download when offline', () async {
    store.add(payment('txn-00000001'));
    server.offline = true;
    final r = await svc(store, server).fullSync();
    expect(r.offline, isTrue);
    expect(server.snapshotCalls, 0);

    server.offline = false;
    server.snapshot = [customer('c1')];
    await svc(store, server).fullSync();
    expect(store.byTxn('txn-00000001').state, PaymentState.synced);
    expect(store.customers.length, 1);
  });
}
