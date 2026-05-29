import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';

import 'model_disk_scan.dart';
import 'ollama_tags_client.dart';
import 'ropac_local.dart';

enum ModelRunState { stopped, starting, ready, stopping }

class ModelPreset {
  const ModelPreset({
    required this.id,
    required this.label,
    required this.tier,
    this.installed = false,
  });

  final String id;
  final String label;
  final String tier;
  final bool installed;

  factory ModelPreset.fromJson(Map<String, dynamic> json) {
    return ModelPreset(
      id: json['id']?.toString() ?? '',
      label: json['label']?.toString() ?? json['id']?.toString() ?? '',
      tier: json['tier']?.toString() ?? '',
      installed: json['installed'] == true,
    );
  }
}

class InstalledModelEntry {
  const InstalledModelEntry({
    required this.name,
    required this.ref,
    required this.path,
  });

  final String name;
  final String ref;
  final String path;

  factory InstalledModelEntry.fromJson(Map<String, dynamic> json) {
    return InstalledModelEntry(
      name: json['name']?.toString() ?? '',
      ref: json['ref']?.toString() ?? json['name']?.toString() ?? '',
      path: json['path']?.toString() ?? '',
    );
  }
}

class ModelCatalogEntry {
  const ModelCatalogEntry({
    required this.id,
    required this.label,
    required this.tier,
    required this.installed,
    this.isExtra = false,
  });

  final String id;
  final String label;
  final String tier;
  final bool installed;
  final bool isExtra;
}

class ModelController extends ChangeNotifier {
  ModelRunState state = ModelRunState.stopped;
  String statusMessage = 'Press Start to load the model';
  String modelName = 'roPac';
  String baseModel = 'qwen2.5-coder:latest';
  String baseModelPath = '';
  String ollamaModelsDir = '';
  List<ModelPreset> presets = const [];
  List<String> installedExtra = const [];
  List<InstalledModelEntry> installedEntries = const [];
  Set<String> installedModels = const {};
  bool catalogLoading = false;
  bool backgroundScanning = false;
  bool switchingModel = false;
  String? downloadingId;

  bool _weStartedOllama = false;

  bool get isReady => state == ModelRunState.ready;
  bool get isBusy =>
      state == ModelRunState.starting ||
      state == ModelRunState.stopping ||
      switchingModel ||
      downloadingId != null;

  bool get hasLocalFileBase =>
      baseModel.isNotEmpty && File(baseModel).existsSync();

  List<ModelPreset> get downloadablePresets =>
      presets.where((p) => !isInstalled(p.id)).toList();

  bool isInstalled(String id) {
    if (id.isNotEmpty && File(id).existsSync()) return true;
    if (installedModels.contains(id)) return true;
    for (final p in presets) {
      if (p.id == id && p.installed) return true;
    }
    final base = id.split(':').first;
    for (final name in installedModels) {
      if (name.split(':').first == base) return true;
    }
    return false;
  }

  List<ModelCatalogEntry> get catalogEntries {
    final out = <ModelCatalogEntry>[];
    final seen = <String>{};
    for (final p in presets) {
      seen.add(p.id);
      out.add(ModelCatalogEntry(
        id: p.id,
        label: p.label,
        tier: p.tier,
        installed: p.installed || installedModels.contains(p.id),
      ));
    }
    for (final id in installedExtra) {
      if (seen.contains(id)) continue;
      seen.add(id);
      out.add(ModelCatalogEntry(
        id: id,
        label: id,
        tier: 'Installed',
        installed: true,
        isExtra: true,
      ));
    }
    return out;
  }

  Future<void> loadCatalog(RopacLocal ropac) async {
    ollamaModelsDir = ModelDiskScan.defaultModelsDir(ropac.ropacRoot);
    catalogLoading = true;
    notifyListeners();

    try {
      final data = await ropac.listModels();
      _applyCatalog(data);
    } catch (e) {
      statusMessage = 'Model list: $e';
    }

    final fromOllamaApp = await OllamaTagsClient.listBaseModels(
      customModel: modelName,
    );
    if (fromOllamaApp.isNotEmpty) {
      _mergeOllamaApiNames(fromOllamaApp, ropac.ropacRoot);
    }

    _mergeDiskInstalls(ropac.ropacRoot);
    catalogLoading = false;
    notifyListeners();

    unawaited(scanLocalModelsBackground(ropac.ropacRoot));
  }

  bool _backgroundScanRunning = false;

  /// Scan Ollama dirs + common folders for .gguf files (non-blocking).
  Future<void> scanLocalModelsBackground(String ropacRoot) async {
    if (_backgroundScanRunning) return;
    _backgroundScanRunning = true;
    backgroundScanning = true;
    notifyListeners();

    try {
      _mergeDiskInstalls(ropacRoot);
      final files = await ModelDiskScan.scanGgufFiles(ropacRoot).timeout(
        const Duration(seconds: 8),
        onTimeout: () => const [],
      );
      _mergeDetectedFiles(files);
    } catch (_) {
      // Best-effort scan — ignore walk errors.
    } finally {
      _backgroundScanRunning = false;
      backgroundScanning = false;
      notifyListeners();
    }
  }

  void _mergeDetectedFiles(List<ScannedModelEntry> files) {
    if (files.isEmpty) return;

    final byRef = <String, InstalledModelEntry>{
      for (final e in installedEntries) e.ref: e,
    };
    final names = {...installedModels};

    for (final e in files) {
      if (modelTypeLabel(e.ref) != 'chat') continue;
      byRef.putIfAbsent(
        e.ref,
        () => InstalledModelEntry(name: e.name, ref: e.ref, path: e.path),
      );
      names.add(e.ref);
    }

    installedEntries = byRef.values.toList()
      ..sort((a, b) => a.name.compareTo(b.name));
    installedModels = names;
  }

  void _mergeOllamaApiNames(List<String> names, String ropacRoot) {
    final nameSet = {...installedModels, ...names};
    installedModels = nameSet;

    final byRef = <String, InstalledModelEntry>{
      for (final e in installedEntries) e.ref: e,
    };
    for (final ref in names) {
      byRef.putIfAbsent(
        ref,
        () => InstalledModelEntry(
          name: ref,
          ref: ref,
          path: _pathForRefFromDisk(ref, ropacRoot),
        ),
      );
    }
    installedEntries = byRef.values.toList()
      ..sort((a, b) => a.name.compareTo(b.name));

    presets = presets
        .map(
          (p) => ModelPreset(
            id: p.id,
            label: p.label,
            tier: p.tier,
            installed: p.installed ||
                nameSet.contains(p.id) ||
                nameSet.any((n) => n.split(':').first == p.id.split(':').first),
          ),
        )
        .toList();
  }

  String _pathForRefFromDisk(String ref, String ropacRoot) {
    for (final dir in ModelDiskScan.candidateDirs(ropacRoot)) {
      for (final e in ModelDiskScan.listInstalled(dir)) {
        if (e.ref == ref) return e.path;
      }
    }
    return '';
  }

  void _mergeDiskInstalls(String ropacRoot) {
    final byRef = <String, InstalledModelEntry>{
      for (final e in installedEntries) e.ref: e,
    };
    final names = {...installedModels};

    for (final dir in ModelDiskScan.candidateDirs(ropacRoot)) {
      if (!Directory(dir).existsSync()) continue;
      for (final e in ModelDiskScan.listInstalled(dir)) {
        byRef.putIfAbsent(
          e.ref,
          () => InstalledModelEntry(name: e.name, ref: e.ref, path: e.path),
        );
        names.add(e.ref);
      }
    }

    if (byRef.isEmpty) return;

    installedEntries = byRef.values.toList()
      ..sort((a, b) => a.name.compareTo(b.name));
    installedModels = names;
    ollamaModelsDir = ModelDiskScan.defaultModelsDir(ropacRoot);

    presets = presets
        .map(
          (p) => ModelPreset(
            id: p.id,
            label: p.label,
            tier: p.tier,
            installed: p.installed ||
                names.contains(p.id) ||
                names.any((n) => n.split(':').first == p.id.split(':').first),
          ),
        )
        .toList();
  }

  void _applyCatalog(Map<String, dynamic> data) {
    modelName = data['custom_model']?.toString() ?? modelName;
    baseModel = data['current_base_model']?.toString() ?? baseModel;
    baseModelPath = data['current_base_path']?.toString() ?? baseModelPath;
    final reportedDir = data['ollama_models_dir']?.toString() ?? '';
    if (reportedDir.isNotEmpty) {
      ollamaModelsDir = reportedDir;
    }
    presets = (data['presets'] as List<dynamic>? ?? [])
        .map((e) => ModelPreset.fromJson(Map<String, dynamic>.from(e as Map)))
        .where((p) => p.id.isNotEmpty)
        .toList();
    installedExtra = (data['installed_extra'] as List<dynamic>? ?? [])
        .map((e) => e.toString())
        .where((e) => e.isNotEmpty)
        .toList();
    installedModels = (data['installed_models'] as List<dynamic>? ?? [])
        .map((e) => e.toString())
        .where((e) => e.isNotEmpty)
        .toSet();
    installedEntries = (data['installed_entries'] as List<dynamic>? ?? [])
        .map(
          (e) => InstalledModelEntry.fromJson(
            Map<String, dynamic>.from(e as Map),
          ),
        )
        .where((e) => e.ref.isNotEmpty)
        .toList();
  }

  String pathForRef(String ref) {
    for (final e in installedEntries) {
      if (e.ref == ref || e.name == ref) return e.path;
    }
    if (ref.isNotEmpty && File(ref).existsSync()) return ref;
    return '';
  }

  String labelForBaseModel(String id) {
    for (final p in presets) {
      if (p.id == id) return p.label;
    }
    if (id.isNotEmpty && File(id).existsSync()) {
      final parts = id.split(Platform.pathSeparator);
      return parts.isNotEmpty ? parts.last : id;
    }
    return id;
  }

  /// Role shown in Downloaded models list: chat, images, embeddings.
  String modelTypeLabel(String id) {
    final probe = id.contains(Platform.pathSeparator)
        ? id.split(Platform.pathSeparator).last
        : id;
    final low = probe.toLowerCase();
    if (low.contains('embed') || low.contains('nomic-embed')) {
      return 'embeddings';
    }
    if (low.contains('moondream') ||
        low.contains('llava') ||
        low.contains('bakllava') ||
        low.contains('minicpm-v') ||
        low.contains('vision')) {
      return 'images';
    }
    return 'chat';
  }

  /// Models user can pick as chat base (excludes vision + embedding helpers).
  List<InstalledModelEntry> get chatInstalledEntries {
    final out = <InstalledModelEntry>[];
    final seen = <String>{};
    for (final e in installedEntries) {
      if (modelTypeLabel(e.ref) != 'chat') continue;
      if (seen.add(e.ref)) out.add(e);
    }
    out.sort((a, b) => a.name.compareTo(b.name));
    return out;
  }

  int get detectedModelCount => chatInstalledEntries.length;

  String tierForBaseModel(String id) {
    for (final p in presets) {
      if (p.id == id) return p.tier;
    }
    return 'Installed';
  }

  Future<void> downloadModel(RopacLocal ropac, String modelId) async {
    if (downloadingId != null) return;

    downloadingId = modelId;
    statusMessage = 'Downloading $modelId…';
    notifyListeners();

    try {
      final data = await ropac.pullModel(modelId);
      statusMessage = data['message']?.toString() ?? 'Download complete';
      final catalog = data['catalog'];
      if (catalog is Map) {
        _applyCatalog(Map<String, dynamic>.from(catalog));
      } else {
        await loadCatalog(ropac);
      }
    } on RopacException catch (e) {
      statusMessage = e.message;
    } catch (e) {
      statusMessage = e.toString();
    } finally {
      downloadingId = null;
      notifyListeners();
    }
  }

  Future<void> switchBaseModel(RopacLocal ropac, String newBase) async {
    final trimmed = newBase.trim();
    if (trimmed.isEmpty || isBusy) return;
    final isLocalPath = File(trimmed).existsSync();
    if (!isLocalPath) {
      final role = modelTypeLabel(trimmed);
      if (role != 'chat') {
        statusMessage =
            '$trimmed is for $role only — select a chat model (e.g. qwen2.5-coder:latest)';
        notifyListeners();
        return;
      }
    }
    if (!isLocalPath && trimmed == baseModel) return;

    if (!isLocalPath && !isInstalled(trimmed)) {
      statusMessage = 'Download $trimmed first, or pick a local model path';
      notifyListeners();
      return;
    }

    switchingModel = true;
    if (state == ModelRunState.ready) {
      statusMessage = 'Stopping current model…';
      notifyListeners();
      try {
        await ropac.stopModel();
      } catch (_) {}
      state = ModelRunState.stopped;
    }

    statusMessage = isLocalPath
        ? 'Using local model…'
        : 'Switching to $trimmed…';
    notifyListeners();

    try {
      final data = await ropac.setBaseModel(trimmed, pullIfMissing: false);
      baseModel = data['base_model']?.toString() ?? trimmed;
      final disk = data['model_path']?.toString();
      if (disk != null && disk.isNotEmpty) {
        baseModelPath = disk;
      } else {
        final p = pathForRef(baseModel);
        if (p.isNotEmpty) baseModelPath = p;
      }
      modelName = data['custom_model']?.toString() ?? modelName;
      statusMessage =
          data['message']?.toString() ?? 'Switched — press Start when ready';
      final catalog = data['catalog'];
      if (catalog is Map) {
        _applyCatalog(Map<String, dynamic>.from(catalog));
      } else {
        await loadCatalog(ropac);
      }
    } on RopacException catch (e) {
      statusMessage = e.message;
    } catch (e) {
      statusMessage = e.toString();
    } finally {
      switchingModel = false;
      if (state != ModelRunState.ready) {
        state = ModelRunState.stopped;
      }
      notifyListeners();
    }
  }

  Future<void> start(RopacLocal ropac) async {
    if (isBusy || state == ModelRunState.ready) return;

    if (!isInstalled(baseModel)) {
      statusMessage = 'Download $baseModel first (model picker)';
      notifyListeners();
      return;
    }

    state = ModelRunState.starting;
    statusMessage = 'Connecting to Ollama…';
    notifyListeners();

    try {
      await _ensureOllamaRunning();

      statusMessage =
          'Loading $modelName — large models can take 1–2 minutes…';
      notifyListeners();

      final data = await ropac.startModel();
      modelName = data['model']?.toString() ?? modelName;

      state = ModelRunState.ready;
      statusMessage =
          data['message']?.toString() ?? '$modelName ready';
    } on RopacException catch (e) {
      state = ModelRunState.stopped;
      statusMessage = e.message;
      await _stopOllamaServeIfNeeded();
    } catch (e) {
      state = ModelRunState.stopped;
      statusMessage = e.toString();
      await _stopOllamaServeIfNeeded();
    }
    notifyListeners();
  }

  Future<void> stop(RopacLocal ropac) async {
    if (isBusy || state == ModelRunState.stopped) return;

    state = ModelRunState.stopping;
    statusMessage = 'Stopping model…';
    notifyListeners();

    try {
      final data = await ropac.stopModel();
      statusMessage = data['message']?.toString() ?? 'Model stopped';
    } on RopacException catch (e) {
      statusMessage = e.message;
    }

    await _stopOllamaServeIfNeeded();
    state = ModelRunState.stopped;
    statusMessage = 'Model stopped — press Start when ready';
    notifyListeners();
  }

  Future<void> refreshStatus(RopacLocal ropac) async {
    if (state != ModelRunState.ready) return;
    try {
      final h = await ropac.health();
      if (h['ollama'] != true || h['model_loaded'] != true) {
        state = ModelRunState.stopped;
        statusMessage = 'Model is no longer loaded';
        notifyListeners();
      }
    } catch (_) {}
  }

  Future<void> _ensureOllamaRunning() async {
    if (await _ollamaReachable()) return;

    final ollama = await _findOllama();
    await Process.start(
      ollama,
      ['serve'],
      mode: ProcessStartMode.detached,
    );
    _weStartedOllama = true;

    for (var i = 0; i < 30; i++) {
      await Future.delayed(const Duration(milliseconds: 500));
      if (await _ollamaReachable()) return;
    }
    throw RopacException(
      'Ollama did not start. Open the Ollama app manually, then try again.',
    );
  }

  Future<bool> _ollamaReachable() async {
    final client = HttpClient();
    try {
      final req = await client
          .getUrl(Uri.parse('http://127.0.0.1:11434/api/tags'))
          .timeout(const Duration(seconds: 2));
      final res = await req.close().timeout(const Duration(seconds: 2));
      return res.statusCode == 200;
    } catch (_) {
      return false;
    } finally {
      client.close(force: true);
    }
  }

  Future<String> _findOllama() async {
    for (final p in [
      '/opt/homebrew/bin/ollama',
      '/usr/local/bin/ollama',
      '/Applications/Ollama.app/Contents/Resources/ollama',
    ]) {
      if (File(p).existsSync()) return p;
    }
    final which = await Process.run('which', ['ollama']);
    if (which.exitCode == 0) {
      final path = (which.stdout as String).trim();
      if (path.isNotEmpty) return path;
    }
    throw RopacException(
      'Ollama not found. Install from https://ollama.com or open the Ollama app.',
    );
  }

  Future<void> _stopOllamaServeIfNeeded() async {
    if (!_weStartedOllama) return;
    _weStartedOllama = false;
    try {
      await Process.run('pkill', ['-f', 'ollama serve']);
    } catch (_) {}
  }

  @override
  void dispose() {
    _stopOllamaServeIfNeeded();
    super.dispose();
  }
}
