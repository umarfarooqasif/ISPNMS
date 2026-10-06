import '../models/models.dart';

/// Offline customer search. Works on the downloaded snapshot, no network needed.
///
/// Matches by name (English or Urdu), customer code, Internet ID, mobile (any format), house
/// number, address and area. Every word typed must match something, in any order.
class CustomerSearch {
  /// Lower-cases, strips Arabic diacritics/tatweel and unifies look-alike Urdu/Arabic letters so
  /// "علي" and "علی" find each other.
  static String normalize(String input) {
    var s = input.toLowerCase().trim();
    s = s.replaceAll(RegExp('[\u064B-\u065F\u0670\u0640]'), ''); // harakat, dagger alif, tatweel
    s = s
        .replaceAll('\u064A', '\u06CC') // Arabic yeh -> Farsi/Urdu yeh
        .replaceAll('\u0649', '\u06CC') // alef maksura -> yeh
        .replaceAll('\u0643', '\u06A9'); // Arabic kaf -> Urdu kaf
    return s.replaceAll(RegExp(r'\s+'), ' ');
  }

  /// "0300-1234567", "+92 300 1234567" and "03001234567" all become digits only, with a leading
  /// Pakistani country code folded to 0, so they compare equal.
  static String digits(String input) {
    var d = input.replaceAll(RegExp(r'\D'), '');
    if (d.startsWith('0092')) d = '0${d.substring(4)}';
    if (d.startsWith('92') && d.length >= 11) d = '0${d.substring(2)}';
    return d;
  }

  /// Text a customer is searched against (built once when the snapshot is stored).
  static String haystack(Customer c) {
    final parts = <String>[
      c.name,
      c.nameUr ?? '',
      c.code,
      c.houseNo ?? '',
      c.address ?? '',
      c.addressUr ?? '',
      c.areaName ?? '',
      for (final k in c.connections) ...[k.internetId ?? '', k.code],
    ];
    final mobiles = [c.mobile, c.whatsapp].whereType<String>().map(digits).where((d) => d.isNotEmpty);
    return '${normalize(parts.join(' '))} ${mobiles.join(' ')}';
  }

  static final _phoneChars = RegExp(r'^[\d+\-() ]+$');

  static bool matches(String haystack, String query) {
    final raw = query.trim();
    // A phone number may be typed with spaces ("+92 300 1234567"), so judge the whole query first.
    if (_phoneChars.hasMatch(raw)) {
      final d = digits(raw);
      if (d.length >= 4) return haystack.contains(d);
    }
    final q = normalize(raw);
    if (q.isEmpty) return true;
    for (final word in q.split(' ')) {
      if (!haystack.contains(word)) return false;
    }
    return true;
  }
}
