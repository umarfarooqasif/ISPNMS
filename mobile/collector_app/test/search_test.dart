import 'package:flutter_test/flutter_test.dart';
import 'package:isp_collector/logic/search.dart';
import 'package:isp_collector/models/models.dart';
import 'package:isp_collector/models/money.dart';

Customer c({String name = 'Ali Khan', String? ur, String? mobile, String? house, String? internetId}) => Customer(
      id: '1',
      code: 'CU-000042',
      name: name,
      nameUr: ur,
      mobile: mobile,
      houseNo: house,
      areaName: 'Housing Colony',
      address: 'Street 3, Habib Park',
      balance: Money.zero,
      amountDue: Money.zero,
      credit: Money.zero,
      billingStatus: 'PAID',
      connections: [
        Connection(id: 'k1', code: 'CN-000001', internetId: internetId, type: 'INTERNET', status: 'ACTIVE'),
      ],
    );

bool hit(Customer cust, String q) => CustomerSearch.matches(CustomerSearch.haystack(cust), q);

void main() {
  final ali = c(ur: 'علی خان', mobile: '0300-1234567', house: 'B-12', internetId: 'ali.khan1');

  test('finds by name, any case, any word order', () {
    expect(hit(ali, 'ali'), isTrue);
    expect(hit(ali, 'KHAN ali'), isTrue);
    expect(hit(ali, 'bilal'), isFalse);
  });

  test('finds by customer id, internet id, house number, area and address', () {
    expect(hit(ali, 'cu-000042'), isTrue);
    expect(hit(ali, 'ali.khan1'), isTrue);
    expect(hit(ali, 'b-12'), isTrue);
    expect(hit(ali, 'housing'), isTrue);
    expect(hit(ali, 'habib park'), isTrue);
  });

  test('finds by mobile in any format', () {
    for (final q in ['03001234567', '0300-1234567', '+92 300 1234567', '923001234567', '1234567']) {
      expect(hit(ali, q), isTrue, reason: q);
    }
    expect(hit(ali, '03009999999'), isFalse);
  });

  test('finds Urdu names, treating look-alike Arabic and Urdu letters as equal', () {
    expect(hit(ali, 'علی'), isTrue);
    expect(hit(ali, 'علي'), isTrue); // Arabic yeh typed on an Arabic keyboard
    expect(hit(ali, 'خان'), isTrue);
    expect(hit(ali, 'بلال'), isFalse);
  });

  test('empty query matches everyone; every word must match', () {
    expect(hit(ali, ''), isTrue);
    expect(hit(ali, 'ali zzz'), isFalse);
  });
}
