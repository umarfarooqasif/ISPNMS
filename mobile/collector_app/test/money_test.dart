import 'package:flutter_test/flutter_test.dart';
import 'package:isp_collector/models/money.dart';

void main() {
  test('parses whole and decimal amounts exactly', () {
    expect(Money.parse('1000').paisa, 100000);
    expect(Money.parse('1000.5').paisa, 100050);
    expect(Money.parse('1000.05').paisa, 100005);
    expect(Money.parse('0.10') + Money.parse('0.20'), Money.parse('0.30')); // no float drift
  });

  test('rejects anything that is not a plain amount', () {
    for (final bad in ['', 'abc', '1,000', '10.555', '1e3', '--5', '12.', '.5', ' ']) {
      expect(Money.tryParse(bad), isNull, reason: bad);
    }
    expect(Money.tryParse(null), isNull);
  });

  test('toApi always has two decimals', () {
    expect(Money.parse('500').toApi(), '500.00');
    expect(Money.parse('500.5').toApi(), '500.50');
    expect(Money(-70050).toApi(), '-700.50');
    expect(Money(5).toApi(), '0.05');
  });

  test('format groups thousands and hides zero paisa', () {
    expect(Money.parse('12500').format(), 'Rs 12,500');
    expect(Money.parse('1234567.5').format(), 'Rs 1,234,567.50');
    expect(Money.parse('999').format(), 'Rs 999');
    expect(Money(-100000).format(), '-Rs 1,000');
  });

  test('arithmetic and comparison', () {
    expect((Money.parse('1000') - Money.parse('250')).toApi(), '750.00');
    expect(Money.parse('5') > Money.parse('4.99'), isTrue);
    expect(Money.parse('-1').isNegative, isTrue);
    expect(Money.zero.isZero, isTrue);
  });
}
