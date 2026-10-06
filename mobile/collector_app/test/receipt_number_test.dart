import 'package:flutter_test/flutter_test.dart';
import 'package:isp_collector/logic/receipt_number.dart';

void main() {
  test('format is OFF-<collector>-<counter>', () {
    expect(formatOfflineReceipt('C01', 42), 'OFF-C01-0042');
    expect(formatOfflineReceipt('c-01', 7), 'OFF-C01-0007');
    expect(formatOfflineReceipt('', 1), 'OFF-X-0001');
  });

  test('numbers are unique as the counter rises and never exceed the server limit', () {
    final seen = {for (var i = 1; i <= 5000; i++) formatOfflineReceipt('C01', i)};
    expect(seen.length, 5000);
    expect(formatOfflineReceipt('A' * 60, 12345).length, lessThanOrEqualTo(40));
  });
}
