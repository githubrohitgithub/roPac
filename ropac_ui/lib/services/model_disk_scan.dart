import 'dart:io';

class ScannedModelEntry {
  const ScannedModelEntry({
    required this.name,
    required this.ref,
    required this.path,
  });

  final String name;
  final String ref;
  final String path;
}

/// Read Ollama manifests and loose GGUF files from common locations.
class ModelDiskScan {
  static const _skipBases = {'roPac'};
  static const _modelExtensions = {'.gguf', '.bin'};
  static const _skipDirNames = {
    '.git',
    '.venv',
    'node_modules',
    'build',
    '.dart_tool',
    'Pods',
    'blobs',
  };

  /// Default model store — Ollama's folder (~/.ollama/models), not inside RoPac.
  static String defaultModelsDir(String ropacRoot) {
    final home = _homeDir();
    if (home.isNotEmpty) {
      final ollama = '$home/.ollama/models';
      if (File(ollama).existsSync() || Directory(ollama).existsSync()) {
        return ollama;
      }
    }
    final portable = '$ropacRoot/ollama_models';
    if (Directory(portable).existsSync() &&
        _dirHasOllamaWeights(portable)) {
      return portable;
    }
    if (home.isNotEmpty) return '$home/.ollama/models';
    return portable;
  }

  static bool _dirHasOllamaWeights(String dir) {
    return Directory('$dir/blobs').existsSync() ||
        Directory('$dir/manifests').existsSync();
  }

  /// Ollama manifest scan — prefer ~/.ollama/models only.
  static List<String> candidateDirs(String ropacRoot) {
    final home = _homeDir();
    if (home.isNotEmpty) {
      final ollama = '$home/.ollama/models';
      if (Directory(ollama).existsSync()) {
        return [ollama];
      }
    }
    final portable = '$ropacRoot/ollama_models';
    if (_dirHasOllamaWeights(portable)) {
      return [portable];
    }
    return [];
  }

  /// Loose .gguf files in download folders (not Ollama store — use listInstalled).
  static List<String> ggufSearchRoots() {
    final out = <String>[];
    final seen = <String>{};

    void add(String path) {
      if (path.isEmpty || seen.contains(path)) return;
      if (!Directory(path).existsSync()) return;
      seen.add(path);
      out.add(path);
    }

    final home = _homeDir();
    if (home.isNotEmpty) {
      for (final sub in [
        'Downloads',
        'Models',
        'AI/models',
        'LLM',
        'llama.cpp/models',
      ]) {
        add(_resolvePath('$home/$sub'));
      }
      add(_resolvePath(
        '$home/Library/Application Support/LM Studio/models',
      ));
    }

    return out;
  }

  static String _homeDir() {
    final home = Platform.environment['HOME'];
    if (home != null && home.isNotEmpty) return home;
    final user = Platform.environment['USER'];
    if (user != null && user.isNotEmpty) return '/Users/$user';
    return '';
  }

  static String _resolvePath(String path) {
    try {
      return File(path).resolveSymbolicLinksSync();
    } catch (_) {
      return path;
    }
  }

  static List<ScannedModelEntry> listInstalled(String modelsDir) {
    final library = Directory(
      '$modelsDir/manifests/registry.ollama.ai/library',
    );
    if (!library.existsSync()) return [];

    final out = <ScannedModelEntry>[];
    for (final base in library.listSync()) {
      if (base is! Directory) continue;
      final baseName = base.uri.pathSegments
          .where((s) => s.isNotEmpty)
          .last;
      final lower = baseName.toLowerCase();
      if (_skipBases.contains(baseName) ||
          lower.contains('embed') ||
          baseName.startsWith('nomic-')) {
        continue;
      }
      for (final tag in base.listSync()) {
        if (tag is! File && tag is! Directory) continue;
        final tagName = tag.uri.pathSegments.where((s) => s.isNotEmpty).last;
        final ref = '$baseName:$tagName';
        out.add(
          ScannedModelEntry(
            name: ref,
            ref: ref,
            path: tag.path,
          ),
        );
      }
    }
    out.sort((a, b) => a.name.compareTo(b.name));
    return out;
  }

  /// Find loose model files under common download folders (background scan).
  static Future<List<ScannedModelEntry>> scanGgufFiles(
    String ropacRoot, {
    int maxDepth = 3,
    int maxFiles = 32,
  }) async {
    final roots = ggufSearchRoots();
    if (roots.isEmpty) return const [];

    final found = <String, ScannedModelEntry>{};
    var steps = 0;

    for (final root in roots) {
      if (found.length >= maxFiles) break;
      await _walkForModels(
        Directory(root),
        depth: 0,
        maxDepth: maxDepth,
        maxFiles: maxFiles,
        found: found,
        steps: () => steps++,
      );
    }

    final out = found.values.toList()
      ..sort((a, b) => a.name.compareTo(b.name));
    return out;
  }

  static Future<void> _walkForModels(
    Directory dir, {
    required int depth,
    required int maxDepth,
    required int maxFiles,
    required Map<String, ScannedModelEntry> found,
    required int Function() steps,
  }) async {
    if (depth > maxDepth || found.length >= maxFiles) return;

    List<FileSystemEntity> entries;
    try {
      entries = await dir.list(followLinks: false).take(500).toList();
    } catch (_) {
      return;
    }

    for (final entry in entries) {
      if (found.length >= maxFiles) return;

      final n = steps();
      if (n % 40 == 0) {
        await Future<void>.delayed(Duration.zero);
      }

      if (entry is File) {
        final path = entry.path;
        final ext = _extension(path);
        if (!_modelExtensions.contains(ext)) continue;
        if (_isHelperModel(path)) continue;
        if (!_looksLikeModelFile(entry)) continue;

        final name = path.split(Platform.pathSeparator).last;
        found.putIfAbsent(
          path,
          () => ScannedModelEntry(name: name, ref: path, path: path),
        );
        continue;
      }

      if (entry is! Directory) continue;
      final base = entry.uri.pathSegments.where((s) => s.isNotEmpty).last;
      if (base.startsWith('.') || _skipDirNames.contains(base)) continue;
      if (base == 'manifests' || base == 'registry.ollama.ai') continue;

      await _walkForModels(
        entry,
        depth: depth + 1,
        maxDepth: maxDepth,
        maxFiles: maxFiles,
        found: found,
        steps: steps,
      );
    }
  }

  static String _extension(String path) {
    final dot = path.lastIndexOf('.');
    if (dot < 0) return '';
    return path.substring(dot).toLowerCase();
  }

  static bool _isHelperModel(String path) {
    final low = path.toLowerCase();
    return low.contains('embed') ||
        low.contains('nomic-embed') ||
        low.contains('moondream') ||
        low.contains('llava') ||
        low.contains('vision');
  }

  /// Skip tiny files that are not full LLM weights.
  static bool _looksLikeModelFile(File file) {
    try {
      return file.lengthSync() >= 50 * 1024 * 1024;
    } catch (_) {
      return false;
    }
  }
}
