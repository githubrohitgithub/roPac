import 'dart:async';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../services/ropac_local.dart';
import '../theme/ropac_theme.dart';
import '../widgets/glass_panel.dart';

const _maxTrainFiles = 10;

class _PendingTrainFile {
  const _PendingTrainFile({
    required this.path,
    required this.name,
    required this.kind,
  });

  final String path;
  final String name;
  final String kind;
}

class TrainScreen extends StatefulWidget {
  const TrainScreen({super.key, required this.ropac, this.enabled = true});

  final RopacLocal ropac;
  final bool enabled;

  @override
  State<TrainScreen> createState() => _TrainScreenState();
}

class _TrainScreenState extends State<TrainScreen> {
  final _password = TextEditingController();
  final List<_PendingTrainFile> _pending = [];
  bool _busy = false;
  bool _loadingSources = false;
  String _log = '';
  List<Map<String, dynamic>> _sources = [];

  static const _imageExts = {
    'png',
    'jpg',
    'jpeg',
    'gif',
    'webp',
    'bmp',
    'tif',
    'tiff',
  };

  @override
  void initState() {
    super.initState();
    if (widget.enabled) {
      unawaited(_refreshSources());
    }
  }

  @override
  void dispose() {
    _password.dispose();
    super.dispose();
  }

  String _kindForName(String name) {
    final parts = name.split('.');
    if (parts.length < 2) return 'document';
    final ext = parts.last.toLowerCase();
    return _imageExts.contains(ext) ? 'image' : 'document';
  }

  Future<void> _refreshSources() async {
    if (!widget.enabled) return;
    setState(() => _loadingSources = true);
    try {
      final docs = await widget.ropac.getSources();
      if (!mounted) return;
      setState(() => _sources = docs);
    } on RopacException catch (e) {
      if (!mounted) return;
      setState(() => _log = 'Error: ${e.message}');
    } finally {
      if (mounted) setState(() => _loadingSources = false);
    }
  }

  Future<void> _pickFiles() async {
    if (_busy || !widget.enabled) return;
    if (_pending.length >= _maxTrainFiles) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          behavior: SnackBarBehavior.floating,
          content: Text('At most $_maxTrainFiles files per batch'),
        ),
      );
      return;
    }
    final result = await FilePicker.platform.pickFiles(
      allowMultiple: true,
      withData: false,
      type: FileType.any,
    );
    if (result == null || result.files.isEmpty) return;

    final added = <_PendingTrainFile>[];
    for (final f in result.files) {
      final path = f.path;
      if (path == null || path.isEmpty) continue;
      if (_pending.any((p) => p.path == path)) continue;
      if (_pending.length + added.length >= _maxTrainFiles) break;
      added.add(
        _PendingTrainFile(
          path: path,
          name: f.name,
          kind: _kindForName(f.name),
        ),
      );
    }
    if (added.isEmpty || !mounted) return;
    setState(() => _pending.addAll(added));
  }

  void _removePending(int index) {
    setState(() => _pending.removeAt(index));
  }

  void _clearPending() {
    if (_pending.isEmpty) return;
    setState(() => _pending.clear());
  }

  Future<void> _previewFile(_PendingTrainFile file) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _log = 'Checking ${file.name}…';
    });
    try {
      final meta = await widget.ropac.parseAttachment(file.path);
      if (!mounted) return;
      if (meta['ok'] == true) {
        final kind = meta['kind']?.toString() ?? file.kind;
        final len = (meta['text'] as String? ?? '').length;
        setState(() {
          _log =
              'OK: $kind · ~$len chars readable\n'
              'Images use vision model (ollama pull moondream).';
        });
      } else {
        setState(() {
          _log = 'Cannot read ${file.name}:\n${meta['error'] ?? 'unknown'}';
        });
      }
    } on RopacException catch (e) {
      if (!mounted) return;
      setState(() => _log = 'Error: ${e.message}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _forgetAllTrained() async {
    if (!widget.enabled || _busy) return;
    if (_sources.isEmpty) {
      setState(() => _log = 'No trained files to forget.');
      return;
    }
    if (_password.text.isEmpty) {
      setState(() => _log = 'Error: Owner password required');
      return;
    }

    final count = _sources.length;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Forget all trained files?'),
        content: Text(
          'Remove all $count trained file(s) from RAG?\n\n'
          'Chunks, embeddings, and memory facts from those files will be deleted. '
          'This cannot be undone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: FilledButton.styleFrom(
              backgroundColor: RoPacColors.warn,
            ),
            child: const Text('Forget all'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() {
      _busy = true;
      _log = 'Removing trained files…';
    });
    try {
      final msg = await widget.ropac.forgetAllTrained(_password.text);
      if (!mounted) return;
      setState(() => _log = msg);
      await _refreshSources();
    } on RopacException catch (e) {
      if (!mounted) return;
      setState(() => _log = 'Error: ${e.message}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _hardResetLocalData() async {
    if (!widget.enabled || _busy) return;
    if (_password.text.isEmpty) {
      setState(() => _log = 'Error: Owner password required');
      return;
    }

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Hard reset all local data?'),
        content: const Text(
          'This permanently deletes:\n'
          '• All memory facts\n'
          '• All trained files (RAG)\n'
          '• Document + memory embeddings\n'
          '• Chat attachment sessions\n'
          '• Chat history log\n\n'
          'Owner password, encryption, and app settings are kept.\n'
          'This cannot be undone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: FilledButton.styleFrom(
              backgroundColor: RoPacColors.warn,
            ),
            child: const Text('Hard reset'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() {
      _busy = true;
      _log = 'Hard reset in progress…';
    });
    try {
      final msg = await widget.ropac.hardResetLocalData(_password.text);
      if (!mounted) return;
      setState(() {
        _log = msg;
        _pending.clear();
      });
      await _refreshSources();
    } on RopacException catch (e) {
      if (!mounted) return;
      setState(() => _log = 'Error: ${e.message}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _reindex({bool force = false}) async {
    if (!widget.enabled) return;
    if (_password.text.isEmpty) {
      setState(() => _log = 'Error: Owner password required for reindex');
      return;
    }
    setState(() {
      _busy = true;
      _log = '';
    });
    try {
      final msg = await widget.ropac.reindexEmbeddings(
        _password.text,
        force: force,
      );
      if (!mounted) return;
      setState(() => _log = msg);
      await _refreshSources();
    } on RopacException catch (e) {
      if (!mounted) return;
      setState(() => _log = 'Error: ${e.message}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _run() async {
    if (!widget.enabled) return;
    if (_pending.isEmpty) {
      setState(() => _log = 'Error: Add at least one file or image');
      return;
    }
    if (_password.text.isEmpty) {
      setState(() => _log = 'Error: Owner password required');
      return;
    }

    final batch = List<_PendingTrainFile>.from(_pending);
    setState(() {
      _busy = true;
      _log = '';
      _pending.clear();
    });

    final logs = <String>[];
    var ok = 0;
    for (var i = 0; i < batch.length; i++) {
      final file = batch[i];
      if (!mounted) return;
      setState(() {
        _log = 'Training ${i + 1}/${batch.length}: ${file.name}…';
      });
      try {
        final msg = await widget.ropac.trainFile(file.path, _password.text);
        logs.add('=== ${file.name} ===\n$msg');
        ok += 1;
      } on RopacException catch (e) {
        logs.add('=== ${file.name} ===\nError: ${e.message}');
      }
    }

    if (!mounted) return;
    setState(() {
      _log = 'Done: $ok/${batch.length} trained.\n\n${logs.join('\n\n')}';
      _busy = false;
    });
    await _refreshSources();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      color: RoPacColors.bgMid.withValues(alpha: 0.5),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(20),
            child: GlassPanel(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const SectionLabel(
                    title: 'Train me with files & images',
                    subtitle:
                        'PDF, Office, code, or images → chunks + embeddings for RAG · offline · password required',
                    trailing: OfflineBadge(),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Images are described with the local vision model (moondream), then stored like documents. Chat retrieves them via RAG.',
                    style: TextStyle(
                      color: RoPacColors.textMuted,
                      fontSize: 12,
                      height: 1.4,
                    ),
                  ),
                  const SizedBox(height: 16),
                  _FilePickerTile(
                    count: _pending.length,
                    onTap: _busy ? null : _pickFiles,
                  ),
                  if (_pending.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    ...List.generate(_pending.length, (i) {
                      final f = _pending[i];
                      return Padding(
                        padding: const EdgeInsets.only(bottom: 6),
                        child: Row(
                          children: [
                            Icon(
                              f.kind == 'image'
                                  ? Icons.image_outlined
                                  : Icons.description_outlined,
                              size: 18,
                              color: RoPacColors.accent,
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                f.name,
                                style: const TextStyle(
                                  color: RoPacColors.textPrimary,
                                  fontSize: 13,
                                ),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            IconButton(
                              tooltip: 'Preview read',
                              visualDensity: VisualDensity.compact,
                              onPressed: _busy ? null : () => _previewFile(f),
                              icon: const Icon(Icons.visibility_outlined, size: 18),
                              color: RoPacColors.textMuted,
                            ),
                            IconButton(
                              tooltip: 'Remove',
                              visualDensity: VisualDensity.compact,
                              onPressed: _busy ? null : () => _removePending(i),
                              icon: const Icon(Icons.close, size: 18),
                              color: RoPacColors.textMuted,
                            ),
                          ],
                        ),
                      );
                    }),
                    if (!_busy)
                      Align(
                        alignment: Alignment.centerLeft,
                        child: TextButton(
                          onPressed: _clearPending,
                          child: const Text('Clear queue'),
                        ),
                      ),
                  ],
                  const SizedBox(height: 12),
                  TextField(
                    controller: _password,
                    enabled: !_busy,
                    obscureText: true,
                    style: const TextStyle(color: RoPacColors.textPrimary),
                    decoration: const InputDecoration(
                      labelText: 'Owner password (required)',
                    ),
                  ),
                  const SizedBox(height: 20),
                  FilledButton.icon(
                    onPressed: _busy || _pending.isEmpty ? null : _run,
                    icon: _busy
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Icon(Icons.bolt_rounded),
                    label: Text(
                      _busy
                          ? 'Training…'
                          : _pending.length > 1
                              ? 'Train ${_pending.length} files'
                              : 'Train',
                    ),
                  ),
                  const SizedBox(height: 12),
                  OutlinedButton.icon(
                    onPressed: _busy ? null : () => _reindex(force: false),
                    icon: const Icon(Icons.refresh_rounded, size: 18),
                    label: const Text('Reindex embeddings'),
                  ),
                  const SizedBox(height: 20),
                  Row(
                    children: [
                      const Text(
                        'Trained for RAG',
                        style: TextStyle(
                          color: RoPacColors.textPrimary,
                          fontWeight: FontWeight.w600,
                          fontSize: 14,
                        ),
                      ),
                      const Spacer(),
                      if (_sources.isNotEmpty && !_busy)
                        TextButton.icon(
                          onPressed: _forgetAllTrained,
                          icon: const Icon(Icons.delete_outline, size: 16),
                          label: const Text('Forget all'),
                          style: TextButton.styleFrom(
                            foregroundColor: RoPacColors.warn,
                            padding: const EdgeInsets.symmetric(horizontal: 8),
                            minimumSize: const Size(0, 32),
                            tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                          ),
                        ),
                      if (_loadingSources)
                        const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      else
                        IconButton(
                          tooltip: 'Refresh list',
                          onPressed: _busy ? null : _refreshSources,
                          icon: const Icon(Icons.sync, size: 20),
                          color: RoPacColors.textMuted,
                        ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  if (_sources.isEmpty && !_loadingSources)
                    const Text(
                      'No files yet. Train PDFs, documents, or images — chat will retrieve relevant chunks automatically.',
                      style: TextStyle(
                        color: RoPacColors.textMuted,
                        fontSize: 12,
                        height: 1.4,
                      ),
                    )
                  else
                    ..._sources.map((d) {
                      final name =
                          d['source_name']?.toString() ?? 'document';
                      final chunks = d['chunk_count'] ?? 0;
                      final emb = d['embeddings'] == true;
                      return Padding(
                        padding: const EdgeInsets.only(bottom: 6),
                        child: Row(
                          children: [
                            Icon(
                              emb
                                  ? Icons.hub_outlined
                                  : Icons.warning_amber_rounded,
                              size: 16,
                              color: emb
                                  ? RoPacColors.accent
                                  : RoPacColors.warn,
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                '$name · $chunks chunks',
                                style: const TextStyle(
                                  color: RoPacColors.textMuted,
                                  fontSize: 12,
                                ),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                          ],
                        ),
                      );
                    }),
                  const SizedBox(height: 20),
                  const Divider(color: RoPacColors.border),
                  const SizedBox(height: 12),
                  const Text(
                    'Danger zone',
                    style: TextStyle(
                      color: RoPacColors.warn,
                      fontWeight: FontWeight.w600,
                      fontSize: 14,
                    ),
                  ),
                  const SizedBox(height: 6),
                  const Text(
                    'Hard reset wipes all memory, RAG training, embeddings, and chat history. '
                    'Use when you want a clean slate.',
                    style: TextStyle(
                      color: RoPacColors.textMuted,
                      fontSize: 12,
                      height: 1.4,
                    ),
                  ),
                  const SizedBox(height: 10),
                  OutlinedButton.icon(
                    onPressed: _busy ? null : _hardResetLocalData,
                    icon: const Icon(Icons.delete_forever_rounded, size: 18),
                    label: const Text('Hard reset local data'),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: RoPacColors.warn,
                      side: const BorderSide(color: RoPacColors.warn),
                      padding: const EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 12,
                      ),
                    ),
                  ),
                  if (_log.isNotEmpty) ...[
                    const SizedBox(height: 16),
                    Container(
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: RoPacColors.bgDeep.withValues(alpha: 0.5),
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: RoPacColors.border),
                      ),
                      child: SelectableText(
                        _log,
                        style: const TextStyle(
                          color: RoPacColors.textPrimary,
                          fontSize: 13,
                          height: 1.45,
                          fontFamily: 'Menlo',
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _FilePickerTile extends StatelessWidget {
  const _FilePickerTile({required this.count, required this.onTap});

  final int count;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final label = count == 0
        ? 'Add files or images (PDF, Word, PNG, …)'
        : '$count file(s) queued — tap to add more';

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(14),
        child: Ink(
          padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(14),
            border: Border.all(
              color: count > 0
                  ? RoPacColors.accent.withValues(alpha: 0.5)
                  : RoPacColors.border,
            ),
            color: RoPacColors.bgDeep.withValues(alpha: 0.4),
          ),
          child: Row(
            children: [
              Icon(
                Icons.cloud_upload_outlined,
                color: count > 0 ? RoPacColors.accent : RoPacColors.textMuted,
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Text(
                  label,
                  style: TextStyle(
                    color: count > 0
                        ? RoPacColors.textPrimary
                        : RoPacColors.textMuted,
                    fontWeight: count > 0 ? FontWeight.w500 : FontWeight.normal,
                  ),
                ),
              ),
              const Icon(Icons.chevron_right, color: RoPacColors.textMuted),
            ],
          ),
        ),
      ),
    );
  }
}
