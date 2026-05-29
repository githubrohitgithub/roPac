import 'dart:async';
import 'dart:io';

import 'package:audio_session/audio_session.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:just_audio/just_audio.dart';
import 'package:speech_to_text/speech_recognition_error.dart';
import 'package:speech_to_text/speech_to_text.dart';

import 'native_mac_audio.dart';
import 'ropac_local.dart';

enum VoiceStatus { idle, starting, listening, speaking, unavailable }

const _nearSpeechDb = -48.0;
const _quietDb = -58.0;
const _silenceBeforeSend = Duration(seconds: 5);
const _sttPauseFor = Duration(minutes: 5);
const _soundNotifyMinInterval = Duration(milliseconds: 120);

const _sttLocalePriorityMac = [
  'en_US',
  'en_GB',
  'en_IN',
  'en-IN',
  'hi_IN',
  'hi-IN',
];
const _sttLocalePriorityOther = ['en_US', 'hi', 'en_IN', 'en-IN'];

const _maleVoiceHints = [
  'rishi',
  'amit',
  'raj',
  'arjun',
  'kunal',
  'vikram',
  'male',
];

class VoiceService extends ChangeNotifier {
  VoiceService({
    RopacLocal? ropac,
    this.enableListening = true,
    this.systemVoiceOnly = false,
  }) : _ropac = ropac {
    _initialized = _init();
  }

  late final Future<void> _initialized;

  /// When false, only text-to-speech is used (no microphone / STT).
  final bool enableListening;

  /// Skip Piper/neural TTS — macOS system voice only (speak-aloud replies).
  final bool systemVoiceOnly;

  final RopacLocal? _ropac;
  final SpeechToText _speech = SpeechToText();
  final FlutterTts _tts = FlutterTts();
  final AudioPlayer _audioPlayer = AudioPlayer();
  bool _neuralTtsReady = false;

  VoiceStatus _status = VoiceStatus.idle;
  String _partialText = '';
  String? _error;
  bool _speakReplies = true;
  bool _ready = false;
  List<String?> _localeCandidates = [];
  int _localeIndex = 0;
  String _ttsLanguage = 'hi-IN';
  void Function(String text)? _onFinalText;
  bool _sentThisSession = false;
  bool _startingSession = false;

  double _inputLevelDb = -80;
  bool _hadNearVoice = false;
  DateTime? _quietSince;
  Timer? _quietCheckTimer;
  DateTime? _lastSoundNotify;
  Process? _macPlayback;

  VoiceStatus get status => _status;
  String get partialText => _partialText;
  String? get error => _error;
  String? get lastSpeakError => _lastSpeakError;

  String? _lastSpeakError;
  /// Last engine used: `piper`, `system`, or null.
  String? _lastSpeakEngine;
  String? _lastSpeakVoiceLabel;
  String? get lastSpeakEngine => _lastSpeakEngine;
  String? get lastSpeakVoiceLabel => _lastSpeakVoiceLabel;
  bool get speakReplies => _speakReplies;
  bool get isListening => _status == VoiceStatus.listening;
  bool get isStarting => _status == VoiceStatus.starting;
  bool get isMicSession =>
      _status == VoiceStatus.starting || _status == VoiceStatus.listening;
  bool get isAvailable => _ready;
  bool get hadNearVoice => _hadNearVoice;
  bool get neuralTtsReady => _neuralTtsReady;

  double get inputLevel {
    const floor = -70.0;
    const ceil = -22.0;
    final t = (_inputLevelDb - floor) / (ceil - floor);
    return t.clamp(0.0, 1.0);
  }

  String get listenLocaleId {
    if (_localeCandidates.isEmpty) return 'system default';
    final id = _localeCandidates[_localeIndex.clamp(
      0,
      _localeCandidates.length - 1,
    )];
    return id ?? 'system default';
  }

  set speakReplies(bool value) {
    _speakReplies = value;
    notifyListeners();
  }

  Future<void> _init() async {
    try {
      if (enableListening) {
        _ready = await _speech.initialize(
          onError: _handleSpeechError,
          onStatus: _handleSpeechStatus,
        );
        if (_ready) {
          _localeCandidates = await _buildLocaleCandidates();
          _localeIndex = 0;
        }
      }
      if (_ropac != null && !systemVoiceOnly) {
        await _refreshNeuralTtsReady();
      } else {
        _neuralTtsReady = false;
      }
      // Mic session grabs CoreAudio; reply-only service must not block speaker output.
      if (enableListening) {
        await _configurePlaybackSession();
      }
      if (systemVoiceOnly) {
        await _configureSystemVoice();
      } else {
        await _configureIndianVoice();
      }
      await _tts.setVolume(1.0);
      await _tts.setSpeechRate(0.46);
      await _tts.setPitch(0.95);
      await _tts.awaitSpeakCompletion(true);
      await _audioPlayer.setVolume(1.0);
      _tts.setCompletionHandler(() {
        if (_status == VoiceStatus.speaking && !_neuralTtsReady) {
          _status = VoiceStatus.idle;
          notifyListeners();
        }
      });
    } catch (e) {
      _ready = false;
      _error = e.toString();
    }
    notifyListeners();
  }

  void _resetProximityState() {
    _hadNearVoice = false;
    _quietSince = null;
    _inputLevelDb = -80;
    _quietCheckTimer?.cancel();
    _quietCheckTimer = null;
    _lastSoundNotify = null;
  }

  void _notifyThrottled() {
    final now = DateTime.now();
    if (_lastSoundNotify != null &&
        now.difference(_lastSoundNotify!) < _soundNotifyMinInterval) {
      return;
    }
    _lastSoundNotify = now;
    notifyListeners();
  }

  void _onSoundLevel(double level) {
    if (_status != VoiceStatus.listening) return;

    final db = level.isFinite ? level : -80.0;
    _inputLevelDb = db;
    final near = db >= _nearSpeechDb;
    final quiet = db <= _quietDb;

    if (near) {
      _hadNearVoice = true;
      _quietSince = null;
      _error = null;
    } else if (quiet && _hadNearVoice) {
      _quietSince ??= DateTime.now();
    } else if (!quiet) {
      _quietSince = null;
    }

    _notifyThrottled();
    _scheduleQuietCheck();
  }

  void _scheduleQuietCheck() {
    _quietCheckTimer?.cancel();
    _quietCheckTimer = Timer(const Duration(milliseconds: 200), () {
      if (_status != VoiceStatus.listening || _sentThisSession) return;
      final since = _quietSince;
      if (since == null || !_hadNearVoice) return;
      if (DateTime.now().difference(since) >= _silenceBeforeSend) {
        _tryCompleteAfterQuiet();
      } else {
        _scheduleQuietCheck();
      }
    });
  }

  void _tryCompleteAfterQuiet() {
    final text = _partialText.trim();
    if (text.isNotEmpty) {
      _completeWithText(text);
      return;
    }
    if (_hadNearVoice) {
      _error = 'Heard you pause — say a bit more, then pause again.';
      notifyListeners();
    }
  }

  void _handleSpeechError(SpeechRecognitionError e) {
    final code = e.errorMsg;
    if (code == 'error_listen_failed') {
      if (_startingSession) {
        unawaited(_retryNextLocale());
      }
      return;
    }
    if (code == 'error_no_match') {
      final text = _partialText.trim();
      if (text.isNotEmpty && _status == VoiceStatus.listening && _hadNearVoice) {
        _completeWithText(text);
        return;
      }
      _error = _hadNearVoice
          ? 'Could not make out words — speak clearer, near the mic.'
          : 'Speak closer to the laptop (about 30–50 cm).';
      _endSession(failed: true);
      return;
    }
    if (code == 'error_speech_timeout') {
      final text = _partialText.trim();
      if (text.isNotEmpty && _hadNearVoice) {
        _completeWithText(text);
        return;
      }
      _error = _hadNearVoice
          ? 'No speech heard. Tap mic and try again.'
          : 'No voice near mic — move closer and speak.';
      _endSession(failed: true);
      return;
    }
    _error = _friendlyError(code);
    notifyListeners();
  }

  void _handleSpeechStatus(String s) {
    if (s == 'listening') {
      if (_startingSession || _status == VoiceStatus.starting) {
        _status = VoiceStatus.listening;
        _error = null;
        notifyListeners();
      }
      return;
    }
    if ((s == 'done' || s == 'notListening') &&
        (_status == VoiceStatus.listening || _status == VoiceStatus.starting)) {
      if (_startingSession) return;
      if (!_hadNearVoice) {
        _endSession(failed: false);
        return;
      }
      final text = _partialText.trim();
      if (text.isNotEmpty) {
        _completeWithText(text);
      } else if (s == 'done') {
        _endSession(failed: false);
      }
    }
  }

  void _endSession({required bool failed}) {
    _startingSession = false;
    _quietCheckTimer?.cancel();
    _onFinalText = null;
    _partialText = '';
    _status = VoiceStatus.idle;
    _resetProximityState();
    notifyListeners();
  }

  void _completeWithText(String text) {
    if (_sentThisSession) return;
    _sentThisSession = true;
    final trimmed = text.trim();
    if (trimmed.isEmpty) return;

    _startingSession = false;
    _quietCheckTimer?.cancel();
    unawaited(_speech.stop());
    _partialText = '';
    _status = VoiceStatus.idle;
    _resetProximityState();
    final cb = _onFinalText;
    _onFinalText = null;
    notifyListeners();
    cb?.call(trimmed);
  }

  String _friendlyError(String code) {
    return switch (code) {
      'error_permission' =>
        'Microphone denied — allow RoPac in System Settings → Privacy.',
      'error_language_not_supported' =>
        'Add English/Hindi dictation in System Settings → Keyboard → Dictation.',
      'error_language_unavailable' =>
        'Speech language unavailable. Enable Dictation on this Mac.',
      _ => 'Speech error: $code',
    };
  }

  Future<void> _ensureMicReleased() async {
    if (_speech.isListening) {
      await _speech.stop();
    }
    await Future<void>.delayed(const Duration(milliseconds: 400));
  }

  Future<List<String?>> _buildLocaleCandidates() async {
    final locales = await _speech.locales();
    final ids = locales.map((l) => l.localeId).toList();
    final priority = Platform.isMacOS
        ? _sttLocalePriorityMac
        : _sttLocalePriorityOther;
    final ordered = <String>[];
    for (final want in priority) {
      for (final id in ids) {
        if (_localeMatches(id, want) && !ordered.contains(id)) {
          ordered.add(id);
        }
      }
    }
    for (final id in ids) {
      if (!ordered.contains(id)) ordered.add(id);
    }
    return [null, ...ordered];
  }

  bool _localeMatches(String id, String want) {
    final a = id.toLowerCase().replaceAll('-', '_');
    final b = want.toLowerCase().replaceAll('-', '_');
    return a == b || a.startsWith('${b}_') || a.startsWith(b);
  }

  Future<void> _configurePlaybackSession() async {
    if (!Platform.isMacOS && !Platform.isIOS) return;
    try {
      final session = await AudioSession.instance;
      await session.configure(
        const AudioSessionConfiguration(
          avAudioSessionCategory: AVAudioSessionCategory.playback,
          avAudioSessionMode: AVAudioSessionMode.spokenAudio,
          avAudioSessionCategoryOptions:
              AVAudioSessionCategoryOptions.duckOthers,
        ),
      );
      await session.setActive(true);
    } catch (e) {
      debugPrint('audio_session: $e');
    }
  }

  Future<void> _releasePlaybackSession() async {
    if (!Platform.isMacOS && !Platform.isIOS) return;
    try {
      final session = await AudioSession.instance;
      await session.setActive(false);
    } catch (e) {
      debugPrint('audio_session release: $e');
    }
  }

  /// Default macOS / system voice for speak-aloud (no custom Piper model).
  Future<void> _configureSystemVoice() async {
    try {
      if (Platform.isMacOS) {
        await _tts.setLanguage('en-US');
      } else if (Platform.isAndroid) {
        await _tts.setLanguage('en-US');
      }
    } catch (e) {
      debugPrint('system voice config: $e');
    }
  }

  Future<void> _configureIndianVoice() async {
    final raw = await _tts.getVoices;
    if (raw == null) return;

    final voices = <Map<String, String>>[];
    for (final v in raw) {
      if (v is! Map) continue;
      voices.add({
        'name': '${v['name'] ?? ''}',
        'locale': '${v['locale'] ?? ''}',
      });
    }

    bool isHindi(Map<String, String> v) =>
        v['locale']!.toLowerCase().contains('hi');

    bool isIndianEn(Map<String, String> v) {
      final loc = v['locale']!.toLowerCase();
      return loc.contains('en-in') || loc.contains('en_in');
    }

    bool isMaleHint(Map<String, String> v) {
      final n = v['name']!.toLowerCase();
      return _maleVoiceHints.any(n.contains);
    }

    Map<String, String>? find(bool Function(Map<String, String>) test) {
      for (final v in voices) {
        if (test(v)) return v;
      }
      return null;
    }

    final chosen = find((v) => isHindi(v) && isMaleHint(v)) ??
        find((v) => isHindi(v)) ??
        find((v) => isIndianEn(v) && isMaleHint(v)) ??
        find((v) => isIndianEn(v)) ??
        (voices.isNotEmpty ? voices.first : null);

    if (chosen != null) {
      final name = chosen['name'] ?? '';
      final locale = chosen['locale'] ?? 'hi-IN';
      _ttsLanguage = locale.toLowerCase().contains('hi') ? 'hi-IN' : 'en-IN';
      await _tts.setLanguage(_ttsLanguage);
      if (name.isNotEmpty) {
        await _tts.setVoice({'name': name, 'locale': locale});
      }
    } else {
      await _tts.setLanguage('hi-IN');
    }
  }

  Future<void> toggleListening({
    required void Function(String text) onFinalText,
  }) async {
    if (!_ready) {
      _error = 'Speech not available. Allow microphone in System Settings.';
      notifyListeners();
      return;
    }

    if (isMicSession) {
      await _ensureMicReleased();
      final text = _partialText.trim();
      final hadNear = _hadNearVoice;
      _startingSession = false;
      _sentThisSession = true;
      _endSession(failed: false);
      if (text.isNotEmpty && hadNear) onFinalText(text);
      return;
    }

    if (_status == VoiceStatus.speaking) {
      await _tts.stop();
    }

    _onFinalText = onFinalText;
    _error = null;
    _partialText = '';
    _sentThisSession = false;
    _localeIndex = 0;
    _resetProximityState();
    _startingSession = true;
    _status = VoiceStatus.starting;
    notifyListeners();

    await _startListen();
  }

  Future<void> _startListen() async {
    await _ensureMicReleased();

    final localeId = _localeCandidates.isNotEmpty
        ? _localeCandidates[_localeIndex.clamp(
            0,
            _localeCandidates.length - 1,
          )]
        : null;

    try {
      await _speech.listen(
        onResult: (result) {
          _partialText = result.recognizedWords;
          _error = null;
          notifyListeners();
          if (result.finalResult && _partialText.trim().isNotEmpty) {
            _completeWithText(_partialText);
          }
        },
        onSoundLevelChange: _onSoundLevel,
        listenOptions: SpeechListenOptions(
          partialResults: true,
          listenMode: ListenMode.dictation,
          cancelOnError: false,
          listenFor: const Duration(minutes: 10),
          pauseFor: _sttPauseFor,
          localeId: localeId,
        ),
      );
    } catch (e) {
      await _retryNextLocale();
      return;
    }

    await Future<void>.delayed(const Duration(milliseconds: 500));

    if (_speech.isListening) {
      _startingSession = false;
      _status = VoiceStatus.listening;
      _error = null;
      notifyListeners();
      return;
    }

    await _retryNextLocale();
  }

  Future<void> _retryNextLocale() async {
    if (!_startingSession) return;

    await _ensureMicReleased();

    if (_localeIndex + 1 >= _localeCandidates.length) {
      _startingSession = false;
      _error =
          'Could not start listening. Enable Dictation + mic for RoPac in System Settings.';
      _status = VoiceStatus.idle;
      _resetProximityState();
      notifyListeners();
      return;
    }

    _localeIndex++;
    _error = 'Retrying ($listenLocaleId)…';
    notifyListeners();
    await Future<void>.delayed(const Duration(milliseconds: 350));
    if (_startingSession) {
      await _startListen();
    }
  }

  /// Quick test when enabling speak-aloud — Piper first, system voice fallback.
  Future<bool> speakQuickTest(String text) async {
    await _ensureReady();
    _lastSpeakError = null;
    _lastSpeakEngine = null;
    final prepared = _textForSpeech(text);
    if (prepared.isEmpty) return false;
    return _speakPiperWithFallback(prepared);
  }

  Future<void> _ensureReady() async {
    try {
      await _initialized.timeout(const Duration(seconds: 8));
    } catch (_) {
      debugPrint('VoiceService init timeout — speaking anyway');
    }
  }

  String _textForSpeech(String text) {
    if (!systemVoiceOnly) return _prepareForSpeech(text);
    var t = text.trim();
    if (t.isEmpty) return t;
    t = t.replaceAll(RegExp(r'```[\s\S]*?```'), ' ');
    t = t.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (t.length > 2500) t = '${t.substring(0, 2500).trim()}…';
    return t;
  }

  /// Returns false if nothing was heard (toggle off, TTS error, or empty text).
  Future<bool> speak(String text) async {
    await _ensureReady();
    if (!_speakReplies || text.trim().isEmpty) return false;
    if (isMicSession) {
      await _ensureMicReleased();
      _startingSession = false;
      _endSession(failed: false);
    }

    final prepared = _textForSpeech(text);
    if (prepared.isEmpty) {
      _lastSpeakError = 'Nothing to speak after text cleanup';
      return false;
    }

    _status = VoiceStatus.speaking;
    _error = null;
    _lastSpeakEngine = null;
    notifyListeners();

    final ok = await _speakPiperWithFallback(prepared);
    _status = VoiceStatus.idle;
    notifyListeners();
    return ok;
  }

  /// Piper + system voice via Python bridge (reliable), then in-app fallbacks.
  Future<bool> _speakPiperWithFallback(String prepared) async {
    if (_ropac != null) {
      try {
        final raw = await _ropac!
            .speakAloud(prepared, preferPiper: true)
            .timeout(const Duration(minutes: 3));
        _lastSpeakVoiceLabel = null;
        if (raw.startsWith('piper:')) {
          _lastSpeakEngine = 'piper';
          _lastSpeakVoiceLabel = raw.substring('piper:'.length);
        } else {
          _lastSpeakEngine = raw.startsWith('piper') ? 'piper' : 'system';
        }
        debugPrint('Speak aloud via bridge: $raw');
        return true;
      } catch (e) {
        _lastSpeakError = e.toString();
        debugPrint('Bridge speak_aloud failed: $e');
      }
    }

    if (Platform.isMacOS) {
      await _releasePlaybackSession();
      final ok = await _speakSystemVoiceMacOS(prepared);
      if (ok) {
        _lastSpeakEngine = 'system';
        return true;
      }
    } else {
      final ok = await _speakSystem(prepared);
      if (ok) {
        _lastSpeakEngine = 'system';
        return ok;
      }
    }

    _lastSpeakError ??= _error ?? NativeMacAudio.lastError ?? 'All TTS failed';
    return false;
  }

  Future<void> _refreshNeuralTtsReady() async {
    if (_ropac == null) return;
    try {
      final st = await _ropac
          .ttsStatus()
          .timeout(const Duration(seconds: 6));
      _neuralTtsReady = st['ready'] == true;
    } catch (e) {
      debugPrint('ttsStatus: $e');
      _neuralTtsReady = false;
    }
  }

  String _prepareForSpeech(String text) {
    var t = text.trim();
    if (t.isEmpty) return t;
    t = t.replaceAll(RegExp(r'```[\s\S]*?```'), ' ');
    t = t.replaceAll(RegExp(r'`([^`]+)`'), r'$1');
    t = t.replaceAll(RegExp(r'\[([^\]]+)\]\([^)]+\)'), r'$1');
    t = t.replaceAll(RegExp(r'[*_#>|]'), ' ');
    // Emojis confuse Piper; strip common ranges.
    t = t.replaceAll(
      RegExp(
        r'[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]',
        unicode: true,
      ),
      ' ',
    );
    t = t.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (t.length > 2500) {
      t = '${t.substring(0, 2500).trim()}…';
    }
    return t;
  }

  Future<bool> _speakNeural(String text) async {
    _lastSpeakError = null;
    try {
      final path = await _ropac!
          .synthesizeSpeech(text)
          .timeout(const Duration(minutes: 2));
      if (path.isEmpty || !File(path).existsSync()) {
        _lastSpeakError = 'Piper synthesis produced no WAV file';
        debugPrint('Neural TTS: missing WAV at $path');
        return false;
      }

      final wav = File(path);
      if (await wav.length() < 44) {
        _lastSpeakError = 'Piper WAV file too small';
        return false;
      }

      if (Platform.isMacOS) {
        await _releasePlaybackSession();
        if (await _playWavMacOS(path)) {
          debugPrint('Neural TTS played via afplay');
          return true;
        }
        if (await NativeMacAudio.playWav(path)) {
          debugPrint('Neural TTS played via native AVAudioEngine');
          return true;
        }
        _lastSpeakError = NativeMacAudio.lastError ??
            'Piper WAV ready but playback failed (afplay + native)';
        return false;
      }
      if (Platform.isLinux) {
        final r = await Process.run('aplay', [path]);
        if (r.exitCode == 0) return true;
        _lastSpeakError = 'aplay exit ${r.exitCode}';
        return false;
      }
      return _playWavJustAudio(path);
    } on TimeoutException {
      _lastSpeakError = 'Piper synthesis timed out';
      return false;
    } catch (e) {
      _lastSpeakError = 'Piper: $e';
      debugPrint('Neural TTS failed: $e');
      return false;
    }
  }

  /// Play WAV with macOS `afplay` from the **app process** (Terminal test uses shell).
  Future<bool> _playWavMacOS(String path, {bool runInShell = false}) async {
    await _stopMacPlayback();
    await _releasePlaybackSession();
    try {
      final result = await Process.run(
        '/usr/bin/afplay',
        [path],
        runInShell: runInShell,
      );
      debugPrint(
        'afplay exit=${result.exitCode} shell=$runInShell path=$path',
      );
      return result.exitCode == 0;
    } catch (e) {
      debugPrint('afplay failed (shell=$runInShell): $e');
      return false;
    }
  }

  Future<bool> _playWavJustAudio(String path) async {
    await _audioPlayer.stop();
    await _audioPlayer.setVolume(1.0);
    await _audioPlayer.setFilePath(path);
    await _audioPlayer.play();
    final duration = _audioPlayer.duration;
    if (duration != null && duration > Duration.zero) {
      await _audioPlayer.positionStream
          .firstWhere(
            (p) => p >= duration - const Duration(milliseconds: 80),
          )
          .timeout(const Duration(minutes: 3));
    } else {
      await _audioPlayer.processingStateStream
          .firstWhere((s) => s == ProcessingState.completed)
          .timeout(const Duration(minutes: 3));
    }
    return true;
  }

  Future<bool> _speakSystem(String text) async {
    if (Platform.isMacOS) {
      return _speakMacOSSay(text);
    }
    try {
      final hasDevanagari = RegExp(r'[\u0900-\u097F]').hasMatch(text);
      if (hasDevanagari && !_ttsLanguage.toLowerCase().contains('hi')) {
        await _tts.setLanguage('hi-IN');
      }
      await _tts.setVolume(1.0);
      await _tts.speak(text);
      return true;
    } catch (e) {
      _error = 'System voice failed: $e';
      debugPrint(_error);
      _status = VoiceStatus.idle;
      notifyListeners();
      return false;
    }
  }

  /// Default macOS system voice — `say` first (FlutterTts often silent in GUI apps).
  Future<bool> _speakSystemVoiceMacOS(String text) async {
    await _stopMacPlayback();
    await _releasePlaybackSession();
    await NativeMacAudio.stop();

    var chunk = text;
    if (chunk.length > 800) {
      chunk = '${chunk.substring(0, 800).trim()}…';
    }
    if (chunk.trim().isEmpty) return false;

    if (await _speakMacOSSay(chunk, useDefaultVoice: true)) {
      return true;
    }

    try {
      await _tts.stop();
      await _tts.setVolume(1.0);
      final r = await _tts.speak(chunk);
      if (r == 1) {
        debugPrint('Spoke via FlutterTts (system default)');
        return true;
      }
    } catch (e) {
      debugPrint('FlutterTts failed: $e');
    }

    return false;
  }

  /// macOS: `/usr/bin/say` via native shell, Dart Process, then temp file.
  Future<bool> _speakMacOSSay(
    String text, {
    bool useDefaultVoice = false,
  }) async {
    await _stopMacPlayback();
    await _releasePlaybackSession();
    if (Platform.isMacOS) {
      await NativeMacAudio.stop();
    }
    final hasDevanagari = RegExp(r'[\u0900-\u097F]').hasMatch(text);
    final voice = useDefaultVoice
        ? ''
        : (hasDevanagari ? 'Lekha' : 'Rishi');
    var chunk = text;
    if (chunk.length > 800) {
      chunk = '${chunk.substring(0, 800).trim()}…';
    }
    if (chunk.trim().isEmpty) return false;

    if (voice.isNotEmpty &&
        await NativeMacAudio.shellSay(chunk, voice: voice)) {
      debugPrint('Spoke via native shellSay');
      return true;
    }
    if (voice.isEmpty &&
        await NativeMacAudio.shellSay(chunk, voice: '')) {
      debugPrint('Spoke via native shellSay (default voice)');
      return true;
    }
    _lastSpeakError = NativeMacAudio.lastError;

    try {
      final args = voice.isEmpty ? <String>[chunk] : ['-v', voice, chunk];
      final r = await Process.run('/usr/bin/say', args);
      if (r.exitCode == 0) {
        debugPrint('Spoke via Dart Process.run say');
        return true;
      }
      _lastSpeakError = 'say exit ${r.exitCode}: ${r.stderr}';
    } catch (e) {
      _lastSpeakError = 'say failed: $e';
      debugPrint(_lastSpeakError);
    }

    try {
      final tmp = File(
        '${Directory.systemTemp.path}/ropac_say_${DateTime.now().millisecondsSinceEpoch}.txt',
      );
      await tmp.writeAsString(chunk);
      final args = voice.isEmpty
          ? <String>['-f', tmp.path]
          : <String>['-v', voice, '-f', tmp.path];
      final r = await Process.run('/usr/bin/say', args);
      await tmp.delete();
      if (r.exitCode == 0) {
        debugPrint('Spoke via say -f tempfile');
        return true;
      }
      _lastSpeakError = 'say -f exit ${r.exitCode}';
    } catch (e) {
      _lastSpeakError = 'say -f failed: $e';
    }

    return false;
  }

  Future<void> _stopMacPlayback() async {
    final proc = _macPlayback;
    _macPlayback = null;
    if (proc == null) return;
    proc.kill(ProcessSignal.sigterm);
    try {
      await proc.exitCode.timeout(const Duration(milliseconds: 400));
    } catch (_) {
      proc.kill(ProcessSignal.sigkill);
    }
  }

  Future<void> stopAll() async {
    await _ensureMicReleased();
    if (Platform.isMacOS) {
      await NativeMacAudio.stop();
    }
    await _stopMacPlayback();
    await _audioPlayer.stop();
    await _tts.stop();
    _startingSession = false;
    _partialText = '';
    _onFinalText = null;
    _sentThisSession = false;
    _status = VoiceStatus.idle;
    _resetProximityState();
    notifyListeners();
  }

  @override
  void dispose() {
    _quietCheckTimer?.cancel();
    _speech.stop();
    _audioPlayer.dispose();
    _tts.stop();
    super.dispose();
  }
}
