import 'package:flutter/material.dart';

import '../models/chat_message.dart';
import '../theme/ropac_theme.dart';
import 'typing_indicator.dart';

class MessageBubble extends StatelessWidget {
  const MessageBubble({
    super.key,
    required this.message,
    this.onEdit,
  });

  final ChatMessage message;
  final VoidCallback? onEdit;

  static const _textStyle = TextStyle(
    color: RoPacColors.textPrimary,
    fontSize: 14,
    height: 1.5,
  );

  @override
  Widget build(BuildContext context) {
    final isUser = message.isUser;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 20),
      child: Row(
        mainAxisAlignment:
            isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (!isUser) ...[
            Container(
              width: 32,
              height: 32,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(10),
                gradient: const LinearGradient(
                  colors: [RoPacColors.accentDim, RoPacColors.accent],
                ),
              ),
              child: const Icon(
                Icons.smart_toy_outlined,
                color: Colors.white,
                size: 18,
              ),
            ),
            const SizedBox(width: 10),
          ],
          Flexible(
            child: Column(
              crossAxisAlignment:
                  isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 16,
                    vertical: 12,
                  ),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.only(
                      topLeft: const Radius.circular(16),
                      topRight: const Radius.circular(16),
                      bottomLeft: Radius.circular(isUser ? 16 : 4),
                      bottomRight: Radius.circular(isUser ? 4 : 16),
                    ),
                    gradient: isUser
                        ? const LinearGradient(
                            colors: [Color(0xFF4F46E5), Color(0xFF6366F1)],
                          )
                        : null,
                    color: isUser
                        ? null
                        : RoPacColors.surfaceHigh.withValues(alpha: 0.95),
                    border: isUser
                        ? null
                        : Border.all(color: RoPacColors.border),
                  ),
                  child: _BubbleBody(message: message, isUser: isUser),
                ),
                if (onEdit != null) ...[
                  const SizedBox(height: 4),
                  TextButton.icon(
                    onPressed: onEdit,
                    icon: const Icon(Icons.edit_outlined, size: 14),
                    label: const Text('Edit'),
                    style: TextButton.styleFrom(
                      foregroundColor: RoPacColors.textMuted,
                      padding: const EdgeInsets.symmetric(horizontal: 8),
                      minimumSize: const Size(0, 28),
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      textStyle: const TextStyle(fontSize: 12),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _BubbleBody extends StatelessWidget {
  const _BubbleBody({required this.message, required this.isUser});

  final ChatMessage message;
  final bool isUser;

  @override
  Widget build(BuildContext context) {
    if (isUser) {
      return SelectableText(message.content, style: MessageBubble._textStyle);
    }

    if (message.isStreaming && message.content.isEmpty) {
      return const TypingIndicator();
    }

    if (message.isStreaming && message.content.isNotEmpty) {
      return Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Flexible(
            child: SelectableText(
              message.content,
              style: MessageBubble._textStyle,
            ),
          ),
          const _StreamingCursor(),
        ],
      );
    }

    return SelectableText(message.content, style: MessageBubble._textStyle);
  }
}

/// Thin pulsing line while tokens still arrive (not the block ▍).
class _StreamingCursor extends StatefulWidget {
  const _StreamingCursor();

  @override
  State<_StreamingCursor> createState() => _StreamingCursorState();
}

class _StreamingCursorState extends State<_StreamingCursor>
    with SingleTickerProviderStateMixin {
  late final AnimationController _blink;

  @override
  void initState() {
    super.initState();
    _blink = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 700),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _blink.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: Tween(begin: 0.25, end: 1.0).animate(
        CurvedAnimation(parent: _blink, curve: Curves.easeInOut),
      ),
      child: Container(
        width: 2,
        height: 16,
        margin: const EdgeInsets.only(left: 2, bottom: 2),
        decoration: BoxDecoration(
          color: RoPacColors.accent,
          borderRadius: BorderRadius.circular(1),
        ),
      ),
    );
  }
}
