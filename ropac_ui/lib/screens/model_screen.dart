import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../services/model_controller.dart';
import '../services/model_disk_scan.dart';
import '../services/ropac_local.dart';
import '../theme/ropac_theme.dart';
import '../widgets/glass_panel.dart';
import '../widgets/status_chip.dart';

class ModelScreen extends StatefulWidget {
  const ModelScreen({
    super.key,
    required this.ropac,
    required this.model,
    required this.onOpenFolderSettings,
  });

  final RopacLocal ropac;
  final ModelController model;
  final VoidCallback onOpenFolderSettings;

  @override
  State<ModelScreen> createState() => _ModelScreenState();
}

class _ModelScreenState extends State<ModelScreen> {
  static const _modelExtensions = ['gguf', 'bin'];

  @override
  void initState() {
    super.initState();
    // HomeScreen already loads catalog on launch — avoid duplicate background scan.
  }

  Future<void> _pickLocalModelFile() async {
    if (widget.model.isBusy) return;

    final defaultDir = ModelDiskScan.defaultModelsDir(widget.ropac.ropacRoot);

    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: _modelExtensions,
      withData: false,
      dialogTitle: 'Choose a local model file',
      initialDirectory: Directory(defaultDir).existsSync() ? defaultDir : null,
    );
    if (result == null || result.files.isEmpty) return;

    final path = result.files.single.path;
    if (path == null || path.isEmpty) return;
    if (!File(path).existsSync()) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('File not found')),
      );
      return;
    }

    await widget.model.switchBaseModel(widget.ropac, path);
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.model,
      builder: (context, _) {
        final model = widget.model;
        final busy = model.isBusy;
        final entries = model.chatInstalledEntries;

        return SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 480),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text(
                    'Model & setup',
                    style: TextStyle(
                      color: RoPacColors.textPrimary,
                      fontSize: 22,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 6),
                  const Text(
                    'Chat models only. Images (moondream) and embeddings (nomic-embed-text) run automatically from config.',
                    style: TextStyle(color: RoPacColors.textMuted, height: 1.4),
                  ),
                  const SizedBox(height: 20),
                  GlassPanel(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Row(
                          children: [
                            ModelStatusChip(state: model.state),
                            const Spacer(),
                            IconButton(
                              tooltip: 'Refresh list',
                              onPressed: busy
                                  ? null
                                  : () => model.loadCatalog(widget.ropac),
                              icon: model.catalogLoading
                                  ? const SizedBox(
                                      width: 20,
                                      height: 20,
                                      child: CircularProgressIndicator(
                                        strokeWidth: 2,
                                      ),
                                    )
                                  : const Icon(Icons.refresh_rounded),
                              color: RoPacColors.textMuted,
                            ),
                            IconButton(
                              tooltip: 'RoPac folder',
                              onPressed: widget.onOpenFolderSettings,
                              icon: const Icon(Icons.folder_open_rounded),
                              color: RoPacColors.textMuted,
                            ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        Text(
                          model.statusMessage,
                          style: const TextStyle(
                            color: RoPacColors.textMuted,
                            fontSize: 13,
                            height: 1.35,
                          ),
                        ),
                        if (model.ollamaModelsDir.isNotEmpty) ...[
                          const SizedBox(height: 12),
                          Text(
                            'Default folder: ${model.ollamaModelsDir}',
                            style: const TextStyle(
                              color: RoPacColors.textMuted,
                              fontSize: 10,
                              height: 1.3,
                            ),
                          ),
                        ],
                        const SizedBox(height: 16),
                        Row(
                          children: [
                            const Expanded(
                              child: Text(
                                'Detected models',
                                style: TextStyle(
                                  color: RoPacColors.textMuted,
                                  fontSize: 11,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                            if (model.backgroundScanning)
                              const SizedBox(
                                width: 14,
                                height: 14,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              )
                            else if (model.detectedModelCount > 0)
                              Text(
                                '${model.detectedModelCount} found',
                                style: const TextStyle(
                                  color: RoPacColors.textMuted,
                                  fontSize: 10,
                                ),
                              ),
                          ],
                        ),
                        const SizedBox(height: 6),
                        const Text(
                          'Ollama models load from ~/.ollama/models (outside RoPac). Optional scan checks Downloads for .gguf files.',
                          style: TextStyle(
                            color: RoPacColors.textMuted,
                            fontSize: 11,
                            height: 1.35,
                          ),
                        ),
                        const SizedBox(height: 8),
                        if (model.catalogLoading && entries.isEmpty)
                          const Padding(
                            padding: EdgeInsets.symmetric(vertical: 24),
                            child: Center(
                              child: CircularProgressIndicator(strokeWidth: 2),
                            ),
                          )
                        else if (entries.isEmpty && !model.backgroundScanning)
                          Padding(
                            padding: const EdgeInsets.symmetric(vertical: 12),
                            child: Text(
                              model.ollamaModelsDir.isNotEmpty
                                  ? 'No models yet under:\n${model.ollamaModelsDir}\n\nUse Choose model file below, or pull via Ollama.'
                                  : 'No models found yet.\nOpen Ollama, or choose a local .gguf file below.',
                              style: const TextStyle(
                                color: RoPacColors.textMuted,
                                fontSize: 12,
                                height: 1.4,
                              ),
                            ),
                          )
                        else if (entries.isEmpty && model.backgroundScanning)
                          const Padding(
                            padding: EdgeInsets.symmetric(vertical: 16),
                            child: Text(
                              'Scanning for models…',
                              style: TextStyle(
                                color: RoPacColors.textMuted,
                                fontSize: 12,
                              ),
                            ),
                          )
                        else
                          ...entries.map(
                            (e) => Padding(
                              padding: const EdgeInsets.only(bottom: 6),
                              child: _DownloadedModelTile(
                                name: model.labelForBaseModel(e.name),
                                subtitle: _subtitleForEntry(e),
                                isActive: e.ref == model.baseModel ||
                                    e.name == model.baseModel,
                                busy: busy,
                                isLocalFile: e.ref.contains(Platform.pathSeparator),
                                onTap: () =>
                                    model.switchBaseModel(widget.ropac, e.ref),
                              ),
                            ),
                          ),
                        const SizedBox(height: 16),
                        const Text(
                          'Local model file',
                          style: TextStyle(
                            color: RoPacColors.textMuted,
                            fontSize: 11,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        const SizedBox(height: 6),
                        const Text(
                          'Or pick any .gguf / .bin file manually if auto-scan did not find it.',
                          style: TextStyle(
                            color: RoPacColors.textMuted,
                            fontSize: 11,
                            height: 1.35,
                          ),
                        ),
                        const SizedBox(height: 8),
                        OutlinedButton.icon(
                          onPressed: busy ? null : _pickLocalModelFile,
                          icon: const Icon(Icons.upload_file_rounded, size: 18),
                          label: const Text('Choose model file…'),
                          style: OutlinedButton.styleFrom(
                            foregroundColor: RoPacColors.textPrimary,
                            side: const BorderSide(color: RoPacColors.border),
                            padding: const EdgeInsets.symmetric(
                              horizontal: 14,
                              vertical: 12,
                            ),
                          ),
                        ),
                        if (model.hasLocalFileBase &&
                            !entries.any((e) => e.ref == model.baseModel)) ...[
                          const SizedBox(height: 8),
                          _DownloadedModelTile(
                            name: model.labelForBaseModel(model.baseModel),
                            subtitle: model.baseModel,
                            isActive: true,
                            busy: busy,
                            isLocalFile: true,
                            onTap: null,
                          ),
                        ],
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }

  String _subtitleForEntry(InstalledModelEntry e) {
    if (e.ref.contains(Platform.pathSeparator)) return e.path;
    if (e.path.contains(Platform.pathSeparator) && e.path != e.name) {
      return e.path;
    }
    return '';
  }
}

class _DownloadedModelTile extends StatelessWidget {
  const _DownloadedModelTile({
    required this.name,
    required this.subtitle,
    required this.isActive,
    required this.busy,
    required this.onTap,
    this.isLocalFile = false,
  });

  final String name;
  final String subtitle;
  final bool isActive;
  final bool busy;
  final VoidCallback? onTap;
  final bool isLocalFile;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: isActive
          ? RoPacColors.accent.withValues(alpha: 0.12)
          : RoPacColors.surfaceHigh,
      borderRadius: BorderRadius.circular(10),
      child: InkWell(
        onTap: busy || isActive ? null : onTap,
        borderRadius: BorderRadius.circular(10),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(10),
            border: Border.all(
              color: isActive
                  ? RoPacColors.accent.withValues(alpha: 0.35)
                  : RoPacColors.border,
            ),
          ),
          child: Row(
            children: [
              Icon(
                isActive
                    ? Icons.radio_button_checked_rounded
                    : Icons.radio_button_off_rounded,
                size: 20,
                color: isActive ? RoPacColors.accent : RoPacColors.textMuted,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      name,
                      style: const TextStyle(
                        color: RoPacColors.textPrimary,
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    if (subtitle.isNotEmpty && subtitle != name)
                      Text(
                        subtitle,
                        style: const TextStyle(
                          color: RoPacColors.textMuted,
                          fontSize: 11,
                        ),
                      ),
                  ],
                ),
              ),
              if (isActive)
                const Text(
                  'Base',
                  style: TextStyle(
                    color: RoPacColors.accent,
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                  ),
                )
              else if (isLocalFile)
                const Text(
                  'File',
                  style: TextStyle(
                    color: RoPacColors.textMuted,
                    fontSize: 10,
                    fontWeight: FontWeight.w600,
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
