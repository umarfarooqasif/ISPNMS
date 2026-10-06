# Collector app (Flutter)

Offline-first field collection for the ISP billing system. See `docs/phase4.md` in the repo root.

```bash
flutter pub get
flutter test            # unit tests (money, search, receipt numbers, offline sync rules)
flutter analyze
flutter run             # on a device; enter your server address on the login screen
flutter build apk --release
```

Android needs no extra setup for this phase. `flutter_secure_storage` requires `minSdkVersion 23`
(set `minSdk = 23` in `android/app/build.gradle` after running `flutter create .` once; see below).

## First-time project files

This folder contains the Dart sources and `pubspec.yaml`. Generate the platform folders once:

```bash
cd mobile/collector_app
flutter create . --org com.example.isp --project-name isp_collector --platforms android,ios
```

`flutter create .` keeps the existing `lib/`, `test/` and `pubspec.yaml`.
