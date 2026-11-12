import 'dart:js_interop';

@JS('window.open')
external JSAny? _windowOpen(JSString url, JSString target);

/// Hand a one-time file address to the browser, which saves the file. True when the browser took it.
bool openDownload(String url) {
  try { _windowOpen(url.toJS, '_self'.toJS); return true; } catch (_) { return false; }
}
