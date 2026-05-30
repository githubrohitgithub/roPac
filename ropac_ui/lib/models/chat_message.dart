class ChatMessage {
  const ChatMessage({
    required this.role,
    required this.content,
    this.rawContent,
    this.isStreaming = false,
    this.ragMetadata,
  });

  final String role;

  /// Display content shown in the UI (may include emoji file-name prefix lines).
  final String content;

  /// Clean text sent to the model in history. When null, [content] is used.
  /// Set for user messages that have an attachment display prefix (e.g. "📎 file.pdf\n\nHello")
  /// so the LLM only sees the actual question in history, not the UI decoration.
  final String? rawContent;

  /// True while the assistant reply is still being generated.
  final bool isStreaming;

  /// Structured RAG query metadata from the backend
  final Map<String, dynamic>? ragMetadata;

  bool get isUser => role == 'user';

  /// Serialize for history: use rawContent when available so the LLM doesn't
  /// see emoji attachment prefix lines in prior turns.
  Map<String, String> toJson() => {
        'role': role,
        'content': rawContent ?? content,
      };
}
