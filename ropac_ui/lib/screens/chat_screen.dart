import 'dart:async';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../config/features.dart';
import '../models/chat_message.dart';
import '../services/ropac_local.dart';
import '../services/voice_service.dart';
import '../theme/ropac_theme.dart';
import '../widgets/glass_panel.dart';
import '../widgets/message_bubble.dart';
import '../widgets/ai_core_background.dart';
import '../widgets/neural_thinking_indicator.dart';
import '../widgets/voice_bar.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({
    super.key,
    required this.ropac,
    this.enabled = true,
  });

  final RopacLocal ropac;
  final bool enabled;

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

final _rememberArrowTrigger = RegExp(
  r'^(?:save|remember)\s+this\s*->\s*(.+)$',
  caseSensitive: false,
  dotAll: true,
);

final _forgetArrowTrigger = RegExp(
  r'^(?:delete|forget)\s+this\s*->\s*(.+)$',
  caseSensitive: false,
  dotAll: true,
);

final _memoryWritePrefix = RegExp(
  r'^(?:save|delete|forget|remember|train)\s+this\s*->',
  caseSensitive: false,
);

/// save-> / delete-> without "this" — not valid (see _remember/_forget triggers).
final _brokenMemoryArrowTrigger = RegExp(
  r'^(?:save|delete|forget|remember|train)\s*->',
  caseSensitive: false,
);

const _memoryArrowFormatHint =
    'Use save this-> <text> or delete this-> <text>. '
    'The word "this" is required (save-> and delete-> are not valid).';

const _maxChatAttachments = 30;

enum ChatProviderOption {
  local('local', 'Local'),
  openai('openai', 'OpenAI (paid)');

  const ChatProviderOption(this.id, this.label);
  final String id;
  final String label;

  static ChatProviderOption fromId(String? id) {
    switch (id) {
      case 'openai':
        return ChatProviderOption.openai;
      default:
        return ChatProviderOption.local;
    }
  }
}

class _PendingAttachment {
  const _PendingAttachment({
    required this.path,
    required this.name,
    required this.kind,
  });

  final String path;
  final String name;
  final String kind;
}

class _ChatScreenState extends State<ChatScreen> {
  final _messages = <ChatMessage>[];
  final _input = TextEditingController();
  final _inputFocus = FocusNode();
  final _scroll = ScrollController();
  VoiceService? _voice;
  VoiceService? _replySpeech;
  bool _speakAloud = false;
  ChatProviderOption _chatProvider = ChatProviderOption.local;
  final _openAiKeyController = TextEditingController();
  bool _loading = false;
  bool _waitingForStream = false;
  bool _freshSession = false;
  final List<_PendingAttachment> _attachments = [];
  final List<String> _sessionAttachmentPaths = [];

  bool get _isGenerating =>
      _loading || _messages.any((message) => message.isStreaming);

  @override
  void initState() {
    super.initState();
    _replySpeech = VoiceService(
      ropac: widget.ropac,
      enableListening: false,
    );
    _loadSpeakAloudPref();
    _loadChatModelPrefs();
    _openAiKeyController.addListener(_onApiKeyFieldChanged);
    if (kVoiceChatEnabled) {
      _voice = VoiceService(ropac: widget.ropac);
    }
    WidgetsBinding.instance.addPostFrameCallback((_) => _focusInputIfAllowed());
    _input.addListener(_onInputChanged);
  }

  void _onApiKeyFieldChanged() {
    if (mounted) setState(() {});
  }

  void _onInputChanged() {
    if (mounted) setState(() {});
  }

  @override
  void didUpdateWidget(covariant ChatScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.enabled && !oldWidget.enabled) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _focusInputIfAllowed());
    }
  }

  void _focusInputIfAllowed() {
    if (!mounted) return;
    if (!widget.enabled || _loading || _micSession) return;
    _inputFocus.requestFocus();
  }

  Future<void> _loadChatModelPrefs() async {
    try {
      final settings = await widget.ropac.getSettings();
      if (!mounted) return;
      setState(() {
        _chatProvider =
            ChatProviderOption.fromId(settings['chat_provider'] as String?);
      });
    } catch (_) {}
  }

  bool get _hasSessionOpenAiKey => _openAiKeyController.text.trim().isNotEmpty;

  bool get _hasActiveCloudKey =>
      _chatProvider == ChatProviderOption.openai && _hasSessionOpenAiKey;

  void _clearSessionApiKeys() {
    _openAiKeyController.clear();
    if (!mounted) return;
    setState(() {});
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        behavior: SnackBarBehavior.floating,
        content: Text('API keys removed from this session'),
      ),
    );
  }

  Future<String?> _promptApiKey({
    required String title,
    required String body,
    required TextEditingController existing,
    String hint = 'sk-...',
  }) async {
    final controller = TextEditingController(text: existing.text);
    final result = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: RoPacColors.surfaceHigh,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: Text(
          title,
          style: const TextStyle(color: RoPacColors.textPrimary),
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              body,
              style: TextStyle(
                color: RoPacColors.textMuted.withValues(alpha: 0.95),
                fontSize: 13,
                height: 1.35,
              ),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: controller,
              obscureText: true,
              autofocus: true,
              autocorrect: false,
              enableSuggestions: false,
              style: const TextStyle(color: RoPacColors.textPrimary),
              decoration: InputDecoration(
                hintText: hint,
                border: const OutlineInputBorder(),
              ),
              onSubmitted: (_) =>
                  Navigator.pop(ctx, controller.text.trim()),
            ),
          ],
        ),
        actions: [
          if (existing.text.trim().isNotEmpty)
            TextButton(
              onPressed: () => Navigator.pop(ctx, ''),
              child: const Text('Remove key'),
            ),
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, controller.text.trim()),
            child: const Text('Use key'),
          ),
        ],
      ),
    );
    controller.dispose();
    return result;
  }

  Future<String?> _promptOpenAiKey({String title = 'OpenAI API key'}) =>
      _promptApiKey(
        title: title,
        body:
            'Paste your OpenAI key for this session only. Not saved to disk or RoPac memory.',
        existing: _openAiKeyController,
      );

  void _setSessionOpenAiKey(String key) {
    _openAiKeyController.text = key.trim();
    if (mounted) setState(() {});
  }

  Future<void> _setChatProvider(ChatProviderOption option) async {
    setState(() => _chatProvider = option);
    try {
      await widget.ropac.setChatModelSettings(chatProvider: option.id);
    } catch (_) {}
  }

  Future<bool> _ensureProviderKeysBeforeSend() async {
    if (_chatProvider == ChatProviderOption.openai) {
      if (_hasSessionOpenAiKey) return true;
      final entered = await _promptOpenAiKey(
        title: 'OpenAI API key — required to send',
      );
      if (!mounted) return false;
      if (entered == null) return false;
      if (entered.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            behavior: SnackBarBehavior.floating,
            content: Text('OpenAI API key is required to send'),
          ),
        );
        return false;
      }
      _setSessionOpenAiKey(entered);
      return true;
    }

    return true;
  }

  String? get _openAiKeyForRequest {
    if (_chatProvider != ChatProviderOption.openai) return null;
    final key = _openAiKeyController.text.trim();
    return key.isEmpty ? null : key;
  }

  Future<void> _loadSpeakAloudPref() async {
    try {
      final on = await widget.ropac.getSpeakAloudEnabled();
      if (!mounted) return;
      setState(() {
        _speakAloud = on;
        _replySpeech?.speakReplies = on;
      });
    } catch (_) {}
  }

  Future<void> _toggleSpeakAloud() async {
    final next = !_speakAloud;
    setState(() {
      _speakAloud = next;
      _replySpeech?.speakReplies = next;
    });
    if (!next) {
      await _replySpeech?.stopAll();
    }
    try {
      await widget.ropac.setSpeakAloudEnabled(next);
    } catch (_) {}
    if (next) {
      unawaited(_testVoiceOnEnable());
    }
  }

  Future<void> _testVoiceOnEnable() async {
    final speech = _replySpeech;
    if (speech == null) return;
    await speech.speakQuickTest('Voice is on. I will read replies aloud.');
  }

  Future<void> _speakReplyAloud(String reply, {bool force = false}) async {
    final speech = _replySpeech;
    if (speech == null) return;

    var shouldSpeak = force || _speakAloud;
    if (!shouldSpeak) {
      try {
        shouldSpeak = await widget.ropac.getSpeakAloudEnabled();
        if (shouldSpeak && mounted) {
          setState(() {
            _speakAloud = true;
            speech.speakReplies = true;
          });
        }
      } catch (_) {}
    }
    if (!shouldSpeak || reply.trim().isEmpty) return;

    speech.speakReplies = true;
    await speech.speak(reply);
  }

  @override
  void dispose() {
    _voice?.dispose();
    _replySpeech?.dispose();
    _input.removeListener(_onInputChanged);
    _openAiKeyController.removeListener(_onApiKeyFieldChanged);
    _openAiKeyController.dispose();
    _input.dispose();
    _inputFocus.dispose();
    _scroll.dispose();
    super.dispose();
  }

  int? get _lastUserIndex {
    for (var i = _messages.length - 1; i >= 0; i--) {
      if (_messages[i].isUser) return i;
    }
    return null;
  }

  Future<bool> _vaultIsUnlocked() async {
    final crypto = await widget.ropac.cryptoStatus();
    return crypto['enabled'] != true || crypto['unlocked'] == true;
  }

  /// One prompt per app session; backend keeps vault unlocked until quit.
  Future<bool> _ensureVaultUnlockedForSession() async {
    if (await _vaultIsUnlocked()) return true;
    final password = await _promptOwnerPassword(
      title: 'Owner password required',
      hint: 'Unlock personal memory for this session',
    );
    if (!mounted) return false;
    if (password == null || password.isEmpty) return false;
    return widget.ropac.ensureVaultUnlocked(password: password);
  }

  Future<String?> _promptOwnerPassword({
    String title = 'Owner password',
    String hint = 'Required to save memory',
  }) async {
    final controller = TextEditingController();
    final result = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: RoPacColors.surfaceHigh,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: Text(
          title,
          style: const TextStyle(color: RoPacColors.textPrimary),
        ),
        content: TextField(
          controller: controller,
          obscureText: true,
          autofocus: true,
          style: const TextStyle(color: RoPacColors.textPrimary),
          decoration: InputDecoration(
            hintText: hint,
          ),
          onSubmitted: (_) => Navigator.pop(ctx, controller.text),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, controller.text),
            child: const Text('Confirm'),
          ),
        ],
      ),
    );
    controller.dispose();
    return result?.trim();
  }

  Future<void> _stopGeneration() async {
    if (!_isGenerating) return;
    await _replySpeech?.stopAll();
    await widget.ropac.interruptGeneration();
    if (!mounted) return;
    setState(() {
      final idx = _messages.lastIndexWhere((m) => m.isStreaming);
      if (idx >= 0) {
        final msg = _messages[idx];
        if (msg.content.isEmpty) {
          _messages.removeAt(idx);
        } else {
          _messages[idx] = ChatMessage(
            role: 'assistant',
            content: msg.content,
            isStreaming: false,
          );
        }
      }
      _loading = false;
      _waitingForStream = false;
    });
    _scrollToEnd();
    _focusInputIfAllowed();
  }

  Future<void> _clearChatSession() async {
    if (_micSession) return;
    if (_loading) {
      await _stopGeneration();
      if (!mounted) return;
    }

    if (_messages.isNotEmpty) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          backgroundColor: RoPacColors.surfaceHigh,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(20),
          ),
          title: const Text(
            'Start fresh?',
            style: TextStyle(color: RoPacColors.textPrimary),
          ),
          content: const Text(
            'Clears this chat so old messages are not sent to the model. '
            'Saved memory and trained files are kept.',
            style: TextStyle(color: RoPacColors.textMuted, height: 1.35),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Clear chat'),
            ),
          ],
        ),
      );
      if (ok != true || !mounted) return;
    }

    try {
      await widget.ropac.clearChatSession();
    } on RopacException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          behavior: SnackBarBehavior.floating,
          content: Text(e.message),
        ),
      );
      return;
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          behavior: SnackBarBehavior.floating,
          content: Text(e.toString()),
        ),
      );
      return;
    }

    await _voice?.stopAll();
    await _replySpeech?.stopAll();
    if (!mounted) return;
    setState(() {
      _messages.clear();
      _attachments.clear();
      _sessionAttachmentPaths.clear();
      _loading = false;
      _waitingForStream = false;
      _freshSession = true;
      _input.clear();
    });
    _focusInputIfAllowed();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        behavior: SnackBarBehavior.floating,
        content: Text('Chat cleared — start fresh'),
      ),
    );
  }

  Future<void> _editLastUserMessage() async {
    final idx = _lastUserIndex;
    if (idx == null) return;

    if (_loading) {
      await _stopGeneration();
      if (!mounted) return;
    }

    final text = _messages[idx].content;
    setState(() {
      _messages.removeAt(idx);
      _input.text = text;
    });
    _scrollToEnd();
    _focusInputIfAllowed();
  }

  bool _isBrokenMemoryArrow(String text) {
    final t = text.trim();
    if (_rememberArrowTrigger.hasMatch(t) || _forgetArrowTrigger.hasMatch(t)) {
      return false;
    }
    return _brokenMemoryArrowTrigger.hasMatch(t);
  }

  bool _isMemoryWriteCommand(String text) {
    final t = text.trim();
    if (t.isEmpty) return false;
    if (_rememberArrowTrigger.hasMatch(t) || _forgetArrowTrigger.hasMatch(t)) {
      return true;
    }
    final firstLine = t.split(RegExp(r'\r?\n')).first.trim();
    return _memoryWritePrefix.hasMatch(firstLine);
  }

  /// Unlock once per app session when personal data is needed (not every message).
  Future<bool> _unlockPersonalVaultIfNeeded(String sendText) async {
    if (await _vaultIsUnlocked()) return true;
    if (_isMemoryWriteCommand(sendText)) {
      return _ensureVaultUnlockedForSession();
    }
    final crypto = await widget.ropac.cryptoStatus();
    if (crypto['enabled'] != true) return true;
    final needed = await widget.ropac.messageNeedsPersonalVault(sendText);
    if (!needed) return true;
    return _ensureVaultUnlockedForSession();
  }

  Future<void> _pickAttachments() async {
    if (_loading || !widget.enabled) return;
    if (_attachments.length >= _maxChatAttachments) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          behavior: SnackBarBehavior.floating,
          content: Text('At most $_maxChatAttachments files per message'),
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

    final added = <_PendingAttachment>[];
    for (final f in result.files) {
      final path = f.path;
      if (path == null || path.isEmpty) continue;
      if (_attachments.any((a) => a.path == path)) continue;
      if (_attachments.length + added.length >= _maxChatAttachments) break;
      final ext = f.extension?.toLowerCase() ?? '';
      final imageExts = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tif', 'tiff'};
      added.add(
        _PendingAttachment(
          path: path,
          name: f.name,
          kind: imageExts.contains(ext) ? 'image' : 'file',
        ),
      );
    }
    if (added.isEmpty || !mounted) return;
    setState(() => _attachments.addAll(added));
    _focusInputIfAllowed();
  }

  void _removeAttachment(int index) {
    setState(() => _attachments.removeAt(index));
  }

  void _clearAttachments() {
    if (_attachments.isEmpty) return;
    setState(() => _attachments.clear());
  }

  String _displayUserMessage(String rawText) {
    if (_attachments.isEmpty) return rawText;
    final names = _attachments.map((a) {
      final icon = a.kind == 'image' ? '🖼' : '📎';
      return '$icon ${a.name}';
    }).join('\n');
    if (rawText.isEmpty) return names;
    return '$names\n\n$rawText';
  }

  Future<void> _send([String? spokenText]) async {
    final rawText = (spokenText ?? _input.text).trim();
    if ((rawText.isEmpty && _attachments.isEmpty) || _loading || !widget.enabled) {
      return;
    }

    if (_isBrokenMemoryArrow(rawText)) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          behavior: SnackBarBehavior.floating,
          content: Text(_memoryArrowFormatHint),
        ),
      );
      return;
    }

    if (!await _ensureProviderKeysBeforeSend()) return;

    final rememberMatch = _rememberArrowTrigger.firstMatch(rawText);
    final forgetMatch = _forgetArrowTrigger.firstMatch(rawText);

    var sendText = rawText;

    if (rememberMatch != null) {
      final fact = rememberMatch.group(1)!.trim();
      sendText = 'save this-> $fact';
    } else if (forgetMatch != null) {
      final query = forgetMatch.group(1)!.trim();
      sendText = 'delete this-> $query';
    }

    if (!await _unlockPersonalVaultIfNeeded(sendText)) return;

    await _voice?.stopAll();
    await _replySpeech?.stopAll();

    final newAttachmentPaths = _attachments.map((a) => a.path).toList();
    for (final path in newAttachmentPaths) {
      if (!_sessionAttachmentPaths.contains(path)) {
        _sessionAttachmentPaths.add(path);
      }
    }
    final attachmentPaths = List<String>.from(_sessionAttachmentPaths);
    final userDisplay = _displayUserMessage(rawText);

    setState(() {
      _loading = true;
      _waitingForStream = true;
      _messages.add(ChatMessage(
        role: 'user',
        content: userDisplay,
        // rawContent is the clean question without emoji attachment prefix lines.
        // toJson() uses this for history so the LLM sees only the actual question.
        rawContent: rawText.isEmpty ? null : rawText,
      ));
      _messages.add(
        const ChatMessage(role: 'assistant', content: '', isStreaming: true),
      );
      if (spokenText == null) _input.clear();
      _attachments.clear();
    });
    _scrollToEnd();

    final assistantIdx = _messages.length - 1;
    final freshSession = _freshSession;

    try {
      final history = freshSession
          ? const <ChatMessage>[]
          : (_messages.length > 2
              ? _messages.sublist(0, _messages.length - 2)
              : <ChatMessage>[]);

      var result = await widget.ropac.chatStreaming(
        sendText,
        history: history,
        freshSession: freshSession,
        chatProvider: _chatProvider.id,
        openaiApiKey: _openAiKeyForRequest,
        attachmentPaths: attachmentPaths,
        onChunk: (chunk) {
          if (!mounted) return;
          setState(() {
            if (_waitingForStream) {
              _waitingForStream = false;
            }
            final prev = _messages[assistantIdx].content;
            _messages[assistantIdx] = ChatMessage(
              role: 'assistant',
              content: prev + chunk,
              isStreaming: true,
            );
          });
          _scrollToEnd();
        },
      );
      if (!mounted) return;

      final reply = result.reply;
      if (reply.toLowerCase().contains('owner password required') &&
          await _ensureVaultUnlockedForSession()) {
        setState(() {
          _messages[assistantIdx] = const ChatMessage(
            role: 'assistant',
            content: '',
            isStreaming: true,
          );
          _loading = true;
          _waitingForStream = true;
        });
        result = await widget.ropac.chatStreaming(
          sendText,
          history: history,
          freshSession: freshSession,
          chatProvider: _chatProvider.id,
          openaiApiKey: _openAiKeyForRequest,
          attachmentPaths: attachmentPaths,
          onChunk: (chunk) {
            if (!mounted) return;
            setState(() {
              if (_waitingForStream) {
                _waitingForStream = false;
              }
              final prev = _messages[assistantIdx].content;
              _messages[assistantIdx] = ChatMessage(
                role: 'assistant',
                content: prev + chunk,
                isStreaming: true,
              );
            });
            _scrollToEnd();
          },
        );
        if (!mounted) return;
      }

      final finalReply = result.reply;
      setState(() {
        _messages[assistantIdx] = ChatMessage(
          role: 'assistant',
          content: finalReply,
          isStreaming: false,
        );
        _loading = false;
        _waitingForStream = false;
        _freshSession = false;
      });
      _scrollToEnd();
      final wantSpeak = _speakAloud ||
          await widget.ropac.getSpeakAloudEnabled().catchError((_) => false);
      if (wantSpeak && _replySpeech != null) {
        if (!_speakAloud && mounted) {
          setState(() {
            _speakAloud = true;
            _replySpeech!.speakReplies = true;
          });
        }
        unawaited(_speakReplyAloud(finalReply, force: true));
      } else if (kVoiceChatEnabled && _voice != null) {
        unawaited(_voice!.speak(reply));
      }
    } on ChatCancelledException {
      if (!mounted) return;
      setState(() {
        if (_messages[assistantIdx].content.isEmpty) {
          _messages.removeAt(assistantIdx);
        } else {
          _messages[assistantIdx] = ChatMessage(
            role: 'assistant',
            content: _messages[assistantIdx].content,
            isStreaming: false,
          );
        }
        _loading = false;
        _waitingForStream = false;
      });
    } on RopacException catch (e) {
      if (!mounted) return;
      if (e.message.startsWith('VAULT_LOCKED:') &&
          await _ensureVaultUnlockedForSession()) {
        try {
          final retryHistory = freshSession
              ? const <ChatMessage>[]
              : (_messages.length > 2
                  ? _messages.sublist(0, _messages.length - 2)
                  : <ChatMessage>[]);
          final result = await widget.ropac.chatStreaming(
            sendText,
            history: retryHistory,
            freshSession: freshSession,
            chatProvider: _chatProvider.id,
            openaiApiKey: _openAiKeyForRequest,
            attachmentPaths: attachmentPaths,
            onChunk: (chunk) {
              if (!mounted) return;
              setState(() {
                if (_waitingForStream) {
                  _waitingForStream = false;
                }
                final prev = _messages[assistantIdx].content;
                _messages[assistantIdx] = ChatMessage(
                  role: 'assistant',
                  content: prev + chunk,
                  isStreaming: true,
                );
              });
              _scrollToEnd();
            },
          );
          if (!mounted) return;
          setState(() {
            _messages[assistantIdx] = ChatMessage(
              role: 'assistant',
              content: result.reply,
              isStreaming: false,
            );
            _loading = false;
            _waitingForStream = false;
            _freshSession = false;
          });
          _scrollToEnd();
        } on RopacException catch (retryErr) {
          if (!mounted) return;
          setState(() {
            _messages[assistantIdx] = ChatMessage(
              role: 'assistant',
              content: 'Error: ${retryErr.message}',
              isStreaming: false,
            );
            _loading = false;
            _waitingForStream = false;
          });
        }
        return;
      }
      setState(() {
        if (_messages[assistantIdx].content.isEmpty) {
          _messages[assistantIdx] = ChatMessage(
            role: 'assistant',
            content: 'Error: ${e.message}',
          );
        } else {
          _messages[assistantIdx] = ChatMessage(
            role: 'assistant',
            content: '${_messages[assistantIdx].content}\n\nError: ${e.message}',
            isStreaming: false,
          );
        }
        _loading = false;
        _waitingForStream = false;
      });
      _scrollToEnd();
    } finally {
      if (mounted && _loading) {
        setState(() {
          _loading = false;
          _waitingForStream = false;
        });
      }
      _focusInputIfAllowed();
    }
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 200),
        curve: Curves.easeOut,
      );
    });
  }

  void _onMicTap() {
    _voice?.toggleListening(onFinalText: (text) => _send(text));
  }

  bool get _micSession => kVoiceChatEnabled && (_voice?.isMicSession ?? false);

  Widget _buildMessageArea() {
    if (_messages.isEmpty && !_micSession) {
      return Stack(
        fit: StackFit.expand,
        children: [AiCoreBackground(modelActive: widget.enabled)],
      );
    }

    final lastUser = _lastUserIndex;

    Widget list = ListView.builder(
      controller: _scroll,
      padding: const EdgeInsets.symmetric(vertical: 16),
      itemCount: _messages.length,
      itemBuilder: (_, i) {
        return MessageBubble(
          message: _messages[i],
          onEdit: i == lastUser && _messages[i].isUser && !_loading
              ? _editLastUserMessage
              : null,
        );
      },
    );

    final content = Stack(
      fit: StackFit.expand,
      children: [
        if (_waitingForStream) const NeuralNetworkBackground(),
        list,
        if (_waitingForStream)
          Positioned(
            left: 0,
            right: 0,
            bottom: 12,
            child: Center(
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                decoration: BoxDecoration(
                  color: RoPacColors.surfaceHigh.withValues(alpha: 0.75),
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(
                    color: RoPacColors.accent.withValues(alpha: 0.2),
                  ),
                ),
                child: const Text(
                  'RoPac is thinking…',
                  style: TextStyle(
                    color: RoPacColors.textMuted,
                    fontSize: 12,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ),
            ),
          ),
      ],
    );

    if (kVoiceChatEnabled && _voice != null) {
      return ListenableBuilder(
        listenable: _voice!,
        builder: (context, _) {
          if (_voice!.isMicSession) {
            return Column(
              children: [
                VoiceListeningBanner(
                  partial: _voice!.partialText,
                  hadNearVoice: _voice!.hadNearVoice,
                ),
                Expanded(child: content),
              ],
            );
          }
          return content;
        },
      );
    }

    return content;
  }

  @override
  Widget build(BuildContext context) {
    final inputEnabled = widget.enabled && !_isGenerating && !_micSession;

    return Container(
      color: RoPacColors.bgMid.withValues(alpha: 0.5),
      child: Column(
        children: [
          Expanded(
            child: GestureDetector(
              behavior: HitTestBehavior.translucent,
              onTap: _focusInputIfAllowed,
              child: _buildMessageArea(),
            ),
          ),
          if (kVoiceChatEnabled && _voice != null)
            VoiceBar(
              voice: _voice!,
              enabled: widget.enabled && !_loading,
              onMicTap: _onMicTap,
            ),
          if (_attachments.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (var i = 0; i < _attachments.length; i++)
                    InputChip(
                      label: Text(
                        _attachments[i].name,
                        style: const TextStyle(fontSize: 12),
                      ),
                      avatar: Icon(
                        _attachments[i].kind == 'image'
                            ? Icons.image_outlined
                            : Icons.attach_file,
                        size: 16,
                        color: RoPacColors.accent,
                      ),
                      deleteIcon: const Icon(Icons.close, size: 16),
                      onDeleted: _loading ? null : () => _removeAttachment(i),
                      backgroundColor: RoPacColors.surfaceHigh,
                      side: BorderSide(
                        color: RoPacColors.accent.withValues(alpha: 0.35),
                      ),
                    ),
                  if (!_loading)
                    ActionChip(
                      label: const Text('Clear all'),
                      onPressed: _clearAttachments,
                    ),
                ],
              ),
            ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 6),
            child: _ChatModelSelector(
              provider: _chatProvider,
              enabled: widget.enabled && !_loading,
              showRemoveKey: _hasActiveCloudKey,
              onProviderChanged: _setChatProvider,
              onRemoveApiKey: _clearSessionApiKeys,
              onClearChat: _clearChatSession,
            ),
          ),
          _ChatInput(
            controller: _input,
            focusNode: _inputFocus,
            enabled: inputEnabled,
            loading: _isGenerating,
            speakAloud: _speakAloud,
            canSend: _input.text.trim().isNotEmpty || _attachments.isNotEmpty,
            onToggleSpeak: _toggleSpeakAloud,
            onAttach: _pickAttachments,
            onSend: () => _send(),
            onStop: _stopGeneration,
          ),
        ],
      ),
    );
  }
}

class _ChatModelSelector extends StatelessWidget {
  const _ChatModelSelector({
    required this.provider,
    required this.enabled,
    required this.showRemoveKey,
    required this.onProviderChanged,
    required this.onRemoveApiKey,
    required this.onClearChat,
  });

  final ChatProviderOption provider;
  final bool enabled;
  final bool showRemoveKey;
  final ValueChanged<ChatProviderOption> onProviderChanged;
  final VoidCallback onRemoveApiKey;
  final VoidCallback onClearChat;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(
            children: [
              for (final opt in ChatProviderOption.values)
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: FilterChip(
                    label: Text(
                      opt.label,
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: provider == opt
                            ? FontWeight.w600
                            : FontWeight.w500,
                      ),
                    ),
                    selected: provider == opt,
                    showCheckmark: false,
                    selectedColor: RoPacColors.accent.withValues(alpha: 0.22),
                    backgroundColor: RoPacColors.surfaceHigh,
                    side: BorderSide(
                      color: provider == opt
                          ? RoPacColors.accent.withValues(alpha: 0.55)
                          : RoPacColors.accent.withValues(alpha: 0.15),
                    ),
                    onSelected: enabled
                        ? (selected) {
                            if (selected) onProviderChanged(opt);
                          }
                        : null,
                  ),
                ),
              if (showRemoveKey)
                TextButton.icon(
                  onPressed: enabled ? onRemoveApiKey : null,
                  icon: const Icon(Icons.key_off_outlined, size: 16),
                  label: const Text('Remove key'),
                  style: TextButton.styleFrom(
                    foregroundColor: RoPacColors.textMuted,
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    minimumSize: const Size(0, 36),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                ),
              TextButton.icon(
                onPressed: enabled ? onClearChat : null,
                icon: const Icon(Icons.refresh_rounded, size: 16),
                label: const Text('New chat'),
                style: TextButton.styleFrom(
                  foregroundColor: RoPacColors.textMuted,
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  minimumSize: const Size(0, 36),
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                ),
              ),
            ],
          ),
        ),
        if (showRemoveKey && provider == ChatProviderOption.openai)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(
              'API key active for this session only — remove when done',
              style: TextStyle(
                color: RoPacColors.textMuted.withValues(alpha: 0.85),
                fontSize: 11,
              ),
            ),
          ),
      ],
    );
  }
}

class _SendMessageIntent extends Intent {
  const _SendMessageIntent();
}

class _ChatInput extends StatelessWidget {
  const _ChatInput({
    required this.controller,
    required this.focusNode,
    required this.enabled,
    required this.loading,
    required this.speakAloud,
    required this.canSend,
    required this.onToggleSpeak,
    required this.onAttach,
    required this.onSend,
    required this.onStop,
  });

  final TextEditingController controller;
  final FocusNode focusNode;
  final bool enabled;
  final bool loading;
  final bool speakAloud;
  final bool canSend;
  final VoidCallback onToggleSpeak;
  final VoidCallback onAttach;
  final VoidCallback onSend;
  final VoidCallback onStop;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
      child: GlassPanel(
        padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
        radius: 18,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Expanded(
              child: Shortcuts(
                shortcuts: const {
                  SingleActivator(LogicalKeyboardKey.enter): _SendMessageIntent(),
                },
                child: Actions(
                  actions: {
                    _SendMessageIntent: CallbackAction<_SendMessageIntent>(
                      onInvoke: (_) {
                        if (enabled && canSend) onSend();
                        return null;
                      },
                    ),
                  },
                  child: TextField(
                    controller: controller,
                    focusNode: focusNode,
                    enabled: enabled,
                    maxLines: 1,
                    keyboardType: TextInputType.text,
                    textInputAction: TextInputAction.send,
                    style: const TextStyle(color: RoPacColors.textPrimary),
                    decoration: const InputDecoration(
                      hintText: 'Ask me anything..',
                      border: InputBorder.none,
                      enabledBorder: InputBorder.none,
                      focusedBorder: InputBorder.none,
                      filled: false,
                      contentPadding:
                          EdgeInsets.symmetric(horizontal: 8, vertical: 10),
                    ),
                    onSubmitted: enabled ? (_) => onSend() : null,
                  ),
                ),
              ),
            ),
            IconButton(
              tooltip: 'Attach file or image',
              onPressed: enabled ? onAttach : null,
              visualDensity: VisualDensity.compact,
              style: IconButton.styleFrom(
                backgroundColor: RoPacColors.surfaceHigh,
                foregroundColor: RoPacColors.textMuted,
              ),
              icon: const Icon(Icons.add_rounded, size: 22),
            ),
            const SizedBox(width: 6),
            IconButton(
              tooltip: speakAloud
                  ? 'Spoken replies on'
                  : 'Spoken replies off',
              onPressed: onToggleSpeak,
              visualDensity: VisualDensity.compact,
              style: IconButton.styleFrom(
                backgroundColor: speakAloud
                    ? RoPacColors.accent.withValues(alpha: 0.2)
                    : RoPacColors.surfaceHigh,
                foregroundColor:
                    speakAloud ? RoPacColors.accent : RoPacColors.textMuted,
              ),
              icon: Icon(
                speakAloud ? Icons.volume_up_rounded : Icons.volume_off_rounded,
                size: 22,
              ),
            ),
            const SizedBox(width: 8),
            Material(
              color: Colors.transparent,
              child: InkWell(
                onTap: loading
                    ? onStop
                    : (enabled && canSend ? onSend : null),
                borderRadius: BorderRadius.circular(12),
                child: Tooltip(
                  message: loading ? 'Stop generating' : 'Send message',
                  child: Ink(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(12),
                    gradient: loading
                        ? null
                        : enabled && canSend
                            ? const LinearGradient(
                                colors: [
                                  RoPacColors.accentDim,
                                  RoPacColors.accent,
                                ],
                              )
                            : null,
                    color: loading
                        ? RoPacColors.danger.withValues(alpha: 0.9)
                        : enabled && canSend
                            ? null
                            : RoPacColors.surfaceHigh,
                  ),
                  child: Icon(
                    loading ? Icons.stop_rounded : Icons.arrow_upward_rounded,
                    color: loading || (enabled && canSend)
                        ? Colors.white
                        : RoPacColors.textMuted,
                  ),
                ),
              ),
            ),
          ),
          ],
        ),
      ),
    );
  }
}
