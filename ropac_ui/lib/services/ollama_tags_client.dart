import 'dart:convert';
import 'dart:io';

/// Same model list as the Ollama desktop app (`GET /api/tags`).
class OllamaTagsClient {
  static const _tagsUrl = 'http://127.0.0.1:11434/api/tags';

  static Future<bool> isReachable() async {
    final names = await listBaseModels();
    return names.isNotEmpty;
  }

  static Future<List<String>> listBaseModels({
    String customModel = 'roPac',
  }) async {
    final client = HttpClient();
    try {
      final request = await client
          .getUrl(Uri.parse(_tagsUrl))
          .timeout(const Duration(seconds: 4));
      final response = await request.close().timeout(
        const Duration(seconds: 4),
      );
      if (response.statusCode != 200) return [];

      final body = await response.transform(utf8.decoder).join();
      final data = jsonDecode(body) as Map<String, dynamic>;
      final models = data['models'] as List<dynamic>? ?? [];

      final out = <String>[];
      for (final raw in models) {
        if (raw is! Map) continue;
        final name = raw['name']?.toString().trim() ?? '';
        if (name.isEmpty) continue;
        final lower = name.toLowerCase();
        if (lower.contains('embed') || name.startsWith('nomic-')) continue;
        if (name.split(':').first == customModel) continue;
        out.add(name);
      }
      out.sort();
      return out;
    } catch (_) {
      return [];
    } finally {
      client.close(force: true);
    }
  }
}
