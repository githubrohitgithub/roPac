import 'dart:convert';
import 'dart:io';

import '../models/chat_message.dart';
import 'model_disk_scan.dart';

class RopacException implements Exception {
  RopacException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// User stopped a chat request before the bridge returned.
class ChatCancelledException implements Exception {
  @override
  String toString() => 'Chat cancelled';
}

/// Result of a streaming chat turn.
class ChatStreamResult {
  const ChatStreamResult({
    required this.reply,
    this.memorySuggestions = const [],
    this.ragMetadata,
  });

  final String reply;
  final List<String> memorySuggestions;
  final Map<String, dynamic>? ragMetadata;
}

/// Talks to RoPac via local Python subprocess only — no HTTP, no cloud.
class RopacLocal {
  RopacLocal(this.ropacRoot);

  final String ropacRoot;
  Process? _activeProcess;
  bool _cancelled = false;

  String get _python => '$ropacRoot/.venv/bin/python';
  String get _bridge => '$ropacRoot/bridge.py';

  bool get hasActiveRequest => _activeProcess != null;

  Future<Map<String, dynamic>> health() async {
    return _invoke({'action': 'health'});
  }

  Future<Map<String, dynamic>> cryptoStatus() async {
    final data = await _invoke({'action': 'crypto_status'});
    final crypto = data['crypto'];
    if (crypto is Map) {
      return Map<String, dynamic>.from(crypto);
    }
    return {'enabled': false, 'unlocked': true};
  }

  /// App launch: install crypto deps check, enable encryption, unlock session.
  Future<Map<String, dynamic>> personalDataSetup({String? password}) async {
    final payload = <String, dynamic>{'action': 'personal_data_setup'};
    if (password != null && password.isNotEmpty) {
      payload['password'] = password;
    }
    final data = await _invoke(payload);
    return Map<String, dynamic>.from(data);
  }

  Future<void> unlockVault(String password) async {
    await _invoke({'action': 'unlock_vault', 'password': password});
  }

  Future<void> lockVault() async {
    try {
      await _invoke({'action': 'lock_vault'});
    } catch (_) {}
  }

  /// True when encryption is off, or session vault is unlocked.
  /// True when this message needs encrypted memory/docs (backend heuristic).
  Future<bool> messageNeedsPersonalVault(String message) async {
    final data = await _invoke({
      'action': 'needs_personal_vault',
      'message': message,
    });
    return data['needed'] == true;
  }

  Future<bool> ensureVaultUnlocked({String? password}) async {
    final status = await cryptoStatus();
    if (status['enabled'] != true) return true;
    if (status['unlocked'] == true) return true;
    if (password != null && password.isNotEmpty) {
      await unlockVault(password);
      final again = await cryptoStatus();
      return again['unlocked'] == true;
    }
    return false;
  }

  Future<bool> getSpeakAloudEnabled() async {
    final data = await _invoke({'action': 'settings'});
    final settings = data['settings'];
    if (settings is Map && settings['speak_aloud_enabled'] == true) {
      return true;
    }
    return false;
  }

  Future<void> setSpeakAloudEnabled(bool enabled) async {
    await _invoke({
      'action': 'set_settings',
      'speak_aloud_enabled': enabled,
    });
  }

  Future<Map<String, dynamic>> getSettings() async {
    final data = await _invoke({'action': 'settings'});
    final settings = data['settings'];
    if (settings is Map) {
      return Map<String, dynamic>.from(settings);
    }
    return {};
  }

  Future<void> setChatModelSettings({String? chatProvider}) async {
    final payload = <String, dynamic>{'action': 'set_settings'};
    if (chatProvider != null) {
      payload['chat_provider'] = chatProvider;
    }
    await _invoke(payload);
  }

  Future<Map<String, dynamic>> startModel() async {
    return _invoke({'action': 'start_model'}).timeout(
      const Duration(minutes: 3),
      onTimeout: () => throw RopacException(
        'Model load timed out (3 min). Large models need time — '
        'keep Ollama open and try Start again, or send a chat message to finish loading.',
      ),
    );
  }

  Future<Map<String, dynamic>> stopModel() async {
    return _invoke({'action': 'stop_model'});
  }

  Future<Map<String, dynamic>> listModels() async {
    return _invoke({'action': 'list_models'});
  }

  Future<Map<String, dynamic>> pullModel(String baseModel) async {
    return _invoke({
      'action': 'pull_model',
      'base_model': baseModel,
    });
  }

  Future<Map<String, dynamic>> setBaseModel(
    String baseModel, {
    bool pullIfMissing = false,
  }) async {
    return _invoke({
      'action': 'set_base_model',
      'base_model': baseModel,
      'pull_if_missing': pullIfMissing,
    });
  }

  Future<String> chat(
    String message, {
    List<ChatMessage> history = const [],
    bool autoLearn = true,
    bool freshSession = false,
    String chatProvider = 'local',
    String? openaiApiKey,
    String? ownerPassword,
    List<String> attachmentPaths = const [],
  }) async {
    final payload = <String, dynamic>{
      'action': 'chat',
      'message': message,
      'history': history.map((m) => m.toJson()).toList(),
      'auto_learn': autoLearn,
      'chat_provider': chatProvider,
    };
    if (freshSession) {
      payload['fresh_session'] = true;
    }
    if (openaiApiKey != null && openaiApiKey.isNotEmpty) {
      payload['openai_api_key'] = openaiApiKey;
    }
    if (ownerPassword != null && ownerPassword.isNotEmpty) {
      payload['password'] = ownerPassword;
    }
    if (attachmentPaths.isNotEmpty) {
      payload['attachment_paths'] = attachmentPaths;
    }
    final data = await _invokeCancellable(payload);
    return data['reply'] as String? ?? '';
  }


  /// Stream assistant reply chunks (Ollama streaming via bridge NDJSON).
  Future<Map<String, dynamic>> parseAttachment(String filePath) async {
    final data = await _invoke({
      'action': 'parse_attachment',
      'path': filePath,
    });
    final attachment = data['attachment'];
    if (attachment is Map) {
      return Map<String, dynamic>.from(attachment);
    }
    return {'ok': false, 'error': 'Invalid attachment response'};
  }

  Future<ChatStreamResult> chatStreaming(
    String message, {
    List<ChatMessage> history = const [],
    bool autoLearn = true,
    bool freshSession = false,
    String chatProvider = 'local',
    String? openaiApiKey,
    String? ownerPassword,
    List<String> attachmentPaths = const [],
    required void Function(String chunk) onChunk,
  }) async {
    if (!File(_bridge).existsSync()) {
      throw RopacException('bridge.py not found in $ropacRoot');
    }
    if (!File(_python).existsSync()) {
      throw RopacException(
        'Python venv missing. Run ./setup.sh in $ropacRoot first.',
      );
    }

    final payload = <String, dynamic>{
      'action': 'chat_stream',
      'message': message,
      'history': history.map((m) => m.toJson()).toList(),
      'auto_learn': autoLearn,
      'chat_provider': chatProvider,
    };
    if (freshSession) {
      payload['fresh_session'] = true;
    }
    if (openaiApiKey != null && openaiApiKey.isNotEmpty) {
      payload['openai_api_key'] = openaiApiKey;
    }
    if (ownerPassword != null && ownerPassword.isNotEmpty) {
      payload['password'] = ownerPassword;
    }
    if (attachmentPaths.isNotEmpty) {
      payload['attachment_paths'] = attachmentPaths;
    }

    _cancelled = false;
    final process = await Process.start(
      _python,
      [_bridge, jsonEncode(payload)],
      workingDirectory: ropacRoot,
      environment: _bridgeEnvironment(),
      runInShell: false,
    );
    _activeProcess = process;

    final buffer = StringBuffer();
    String? finalReply;
    var memorySuggestions = <String>[];
    Map<String, dynamic>? ragMetadata;

    try {
      await for (final line
          in process.stdout.transform(utf8.decoder).transform(const LineSplitter())) {
        if (_cancelled) {
          process.kill(ProcessSignal.sigterm);
          throw ChatCancelledException();
        }
        final trimmed = line.trim();
        if (trimmed.isEmpty) continue;

        final data = jsonDecode(trimmed) as Map<String, dynamic>;
        if (data['ok'] == false) {
          throw RopacException(data['error']?.toString() ?? 'Stream failed');
        }
        if (data['type'] == 'chunk') {
          final text = data['text'] as String? ?? '';
          if (text.isNotEmpty) {
            buffer.write(text);
            onChunk(text);
          }
        }
        if (data['type'] == 'memory_suggestions') {
          memorySuggestions = (data['facts'] as List<dynamic>? ?? [])
              .map((e) => e.toString())
              .where((e) => e.trim().isNotEmpty)
              .toList();
        }
        if (data['ok'] == true && data['reply'] != null) {
          finalReply = data['reply'] as String;
          final fromOk = data['memory_suggestions'];
          if (fromOk is List && fromOk.isNotEmpty) {
            memorySuggestions = fromOk.map((e) => e.toString()).toList();
          }
          if (data['rag_metadata'] != null) {
            ragMetadata = Map<String, dynamic>.from(data['rag_metadata'] as Map);
          }
        }
      }

      final stderr = await process.stderr.transform(utf8.decoder).join();
      final code = await process.exitCode;
      if (_cancelled) throw ChatCancelledException();
      if (code != 0) {
        var msg = stderr.trim();
        if (msg.isEmpty) msg = 'Bridge stream failed (exit $code)';
        throw RopacException(msg);
      }
    } finally {
      _activeProcess = null;
    }

    return ChatStreamResult(
      reply: finalReply ?? buffer.toString(),
      memorySuggestions: memorySuggestions,
      ragMetadata: ragMetadata,
    );
  }

  Future<String> saveMemorySuggestions(
    List<String> facts, {
    String? password,
  }) async {
    final payload = <String, dynamic>{
      'action': 'save_memory_suggestions',
      'facts': facts,
    };
    if (password != null && password.isNotEmpty) {
      payload['password'] = password;
    }
    final data = await _invoke(payload);
    return data['message'] as String? ?? 'Saved';
  }

  void cancelActiveRequest() {
    _cancelled = true;
    final proc = _activeProcess;
    _activeProcess = null;
    proc?.kill(ProcessSignal.sigterm);
  }

  Future<void> interruptGeneration() async {
    cancelActiveRequest();
    try {
      await _invoke({'action': 'interrupt'});
    } catch (_) {}
  }

  Future<List<String>> getFacts() async {
    final data = await _invoke({'action': 'memory'});
    return (data['facts'] as List<dynamic>? ?? [])
        .map((e) => e.toString())
        .toList();
  }

  Future<List<Map<String, dynamic>>> getSources() async {
    final data = await _invoke({'action': 'sources'});
    return (data['documents'] as List<dynamic>? ?? [])
        .map((e) => Map<String, dynamic>.from(e as Map))
        .toList();
  }

  Future<String> remember(String fact, String password) async {
    final data = await _invoke({
      'action': 'remember',
      'fact': fact,
      'password': password,
    });
    return data['message'] as String? ?? 'Done';
  }

  Future<String> forget(String query, String password) async {
    final data = await _invoke({
      'action': 'forget',
      'query': query,
      'password': password,
    });
    return data['message'] as String? ?? 'Done';
  }

  Future<String> trainFile(String filePath, String ownerPassword) async {
    final data = await _invoke({
      'action': 'train',
      'path': filePath,
      'password': ownerPassword,
    });
    return data['message'] as String? ?? 'Trained';
  }

  /// Rebuild embedding vectors for all trained files (after model change or upgrade).
  Future<String> reindexEmbeddings(
    String ownerPassword, {
    bool force = false,
  }) async {
    final data = await _invoke({
      'action': 'reindex_embeddings',
      'password': ownerPassword,
      'force': force,
    });
    final indexed = data['indexed'];
    final failed = data['failed'];
    final model = data['embed_model'];
    if (data['ok'] == true) {
      return 'Reindexed $indexed document(s) with $model.';
    }
    final err = data['error'] as String?;
    if (err != null && err.isNotEmpty) {
      throw RopacException(err);
    }
    return 'Reindexed $indexed, failed $failed (model: $model).';
  }

  /// Remove all trained RAG documents and their extracted memory facts.
  Future<String> forgetAllTrained(String ownerPassword) async {
    final data = await _invoke({
      'action': 'forget_all_trained',
      'password': ownerPassword,
    });
    return data['message'] as String? ?? 'Forgot trained files';
  }

  /// Clear on-screen conversation context, chat log, and attachment cache.
  Future<String> clearChatSession() async {
    final data = await _invoke({'action': 'clear_chat_session'});
    return data['message'] as String? ?? 'Chat cleared';
  }

  /// Wipe memory, RAG, embeddings, sessions, and chat history.
  Future<String> hardResetLocalData(String ownerPassword) async {
    final data = await _invoke({
      'action': 'hard_reset_local_data',
      'password': ownerPassword,
    });
    return data['message'] as String? ?? 'Hard reset complete';
  }

  Future<Map<String, dynamic>> ttsStatus() async {
    return _invoke({'action': 'tts_status'});
  }

  Future<String> synthesizeSpeech(String text) async {
    final data = await _invoke({'action': 'tts_speak', 'text': text});
    return data['audio_path'] as String? ?? '';
  }

  /// Synthesize offline neural voice and play via system audio (macOS: afplay).
  Future<void> speakAndPlay(String text) async {
    await _invoke({'action': 'tts_speak_and_play', 'text': text});
  }

  /// Piper (Amy / Rohan) or system `say` via Python bridge.
  Future<String> speakAloud(
    String text, {
    bool preferPiper = true,
  }) async {
    final data = await _invoke({
      'action': 'speak_aloud',
      'text': text,
      'prefer_piper': preferPiper,
    });
    if (data['spoken'] != true) {
      throw RopacException('Speak aloud failed');
    }
    final engine = data['engine'] as String? ?? 'unknown';
    final label = data['label'] as String?;
    if (label != null && label.isNotEmpty) {
      return '$engine:$label';
    }
    return engine;
  }

  static String _defaultOllamaModelsDir(String ropacRoot) {
    return ModelDiskScan.defaultModelsDir(ropacRoot);
  }

  static void _applyOllamaPath(Map<String, String> env) {
    const candidates = [
      '/opt/homebrew/bin/ollama',
      '/usr/local/bin/ollama',
      '/Applications/Ollama.app/Contents/Resources/ollama',
    ];
    for (final path in candidates) {
      if (File(path).existsSync()) {
        env['OLLAMA_BIN'] = path;
        break;
      }
    }
    final pathKey = env['PATH'] ?? '';
    const prefix = '/opt/homebrew/bin:/usr/local/bin';
    if (!pathKey.contains('/opt/homebrew/bin')) {
      env['PATH'] = pathKey.isEmpty ? prefix : '$prefix:$pathKey';
    }
  }

  Map<String, String> _bridgeEnvironment() {
    final env = Map<String, String>.from(Platform.environment);
    env['PYTHONUTF8'] = '1';
    final home = env['HOME'];
    if (home == null || home.isEmpty) {
      final user = env['USER'];
      if (user != null && user.isNotEmpty) {
        env['HOME'] = '/Users/$user';
      }
    }

    final envFile = File('$ropacRoot/ropac.env');
    if (envFile.existsSync()) {
      for (final raw in envFile.readAsLinesSync()) {
        var line = raw.trim();
        if (line.isEmpty || line.startsWith('#')) continue;
        final eq = line.indexOf('=');
        if (eq <= 0) continue;
        final key = line.substring(0, eq).trim();
        // Paths always come from ropacRoot (avoids stale ropac.env after move/rename).
        if (key == 'ROPAC_DIR' ||
            key == 'OLLAMA_MODELS' ||
            key == 'TTS_DIR' ||
            key.startsWith('HF_') ||
            key == 'TORCH_HOME' ||
            key == 'TRANSFORMERS_CACHE') {
          continue;
        }
        env[key] = line.substring(eq + 1).trim();
      }
    }

    final root = ropacRoot;
    env['ROPAC_DIR'] = root;
    env['OLLAMA_MODELS'] = _defaultOllamaModelsDir(root);
    _applyOllamaPath(env);
    env['TTS_DIR'] = '$root/data/tts';
    env['HF_HOME'] = '$root/data/tts/huggingface';
    env['HF_HUB_CACHE'] = '$root/data/tts/huggingface/hub';
    env['TRANSFORMERS_CACHE'] = '$root/data/tts/huggingface/transformers';
    env['TORCH_HOME'] = '$root/data/tts/torch';
    return env;
  }

  Future<Map<String, dynamic>> _invokeCancellable(
    Map<String, dynamic> payload,
  ) async {
    if (!File(_bridge).existsSync()) {
      throw RopacException('bridge.py not found in $ropacRoot');
    }
    if (!File(_python).existsSync()) {
      throw RopacException(
        'Python venv missing. Run ./setup.sh in $ropacRoot first.',
      );
    }

    _cancelled = false;
    final requestJson = jsonEncode(payload);
    final process = await Process.start(
      _python,
      [_bridge, requestJson],
      workingDirectory: ropacRoot,
      environment: _bridgeEnvironment(),
      runInShell: false,
    );
    _activeProcess = process;

    final stdout = await process.stdout.transform(utf8.decoder).join();
    final stderr = await process.stderr.transform(utf8.decoder).join();
    final code = await process.exitCode;
    _activeProcess = null;

    if (_cancelled) {
      throw ChatCancelledException();
    }

    return _parseBridgeOutput(stdout, stderr, code);
  }

  Future<Map<String, dynamic>> _invoke(Map<String, dynamic> payload) async {
    if (!File(_bridge).existsSync()) {
      throw RopacException('bridge.py not found in $ropacRoot');
    }
    if (!File(_python).existsSync()) {
      throw RopacException(
        'Python venv missing. Run ./setup.sh in $ropacRoot first.',
      );
    }

    final result = await Process.run(
      _python,
      [_bridge, jsonEncode(payload)],
      workingDirectory: ropacRoot,
      environment: _bridgeEnvironment(),
      runInShell: false,
    );
    return _parseBridgeOutput(
      result.stdout.toString(),
      result.stderr.toString(),
      result.exitCode,
    );
  }

  Map<String, dynamic> _parseBridgeOutput(
    String stdout,
    String stderr,
    int code,
  ) {
    if (code != 0) {
      var msg = stderr.trim();
      if (msg.isEmpty) msg = stdout.trim();
      try {
        final j = jsonDecode(stdout) as Map<String, dynamic>;
        if (j['error'] != null) msg = j['error'].toString();
      } catch (_) {}
      throw RopacException(msg.isEmpty ? 'Bridge failed (exit $code)' : msg);
    }

    try {
      final data = jsonDecode(stdout.trim()) as Map<String, dynamic>;
      if (data['ok'] != true) {
        throw RopacException(data['error']?.toString() ?? 'Unknown error');
      }
      return data;
    } catch (e) {
      if (e is RopacException) rethrow;
      throw RopacException('Invalid bridge response: $stdout');
    }
  }
}

class RopacPaths {
  static const _configName = 'ropac_root.txt';

  static String configFile() {
    final home = Platform.environment['HOME'] ?? '';
    return '$home/Library/Application Support/com.ropac.ropac_ui/$_configName';
  }

  static Future<String?> _readPortableMarker(String root) async {
    final marker = File('$root/data/ropac_root.txt');
    if (!await marker.exists()) return null;
    final p = (await marker.readAsString()).trim();
    if (p.isNotEmpty && File('$p/bridge.py').existsSync()) return p;
    if (File('$root/bridge.py').existsSync()) return root;
    return null;
  }

  static Future<String> loadRoot() async {
    final file = File(configFile());
    if (await file.exists()) {
      final p = (await file.readAsString()).trim();
      if (p.isNotEmpty && File('$p/bridge.py').existsSync()) return p;
      final fromMarker = await _readPortableMarker(p);
      if (fromMarker != null) return fromMarker;
    }

    final home = Platform.environment['HOME'] ?? '';
    for (final guess in [
      '$home/ropac',
      '$home/Documents/ropac',
      '$home/Desktop/ropac',
    ]) {
      final fromMarker = await _readPortableMarker(guess);
      if (fromMarker != null) return fromMarker;
      if (File('$guess/bridge.py').existsSync()) return guess;
    }

    final sibling = Directory('${Directory.current.path}/..');
    final normalized = sibling.absolute.path;
    final fromSibling = await _readPortableMarker(normalized);
    if (fromSibling != null) return fromSibling;
    if (File('$normalized/bridge.py').existsSync()) return normalized;
    return normalized;
  }

  static Future<void> saveRoot(String path) async {
    final file = File(configFile());
    await file.parent.create(recursive: true);
    await file.writeAsString(path.trim());
  }
}
