class ChatMessage {
  const ChatMessage({
    required this.role,
    required this.content,
    this.isStreaming = false,
  });

  final String role;
  final String content;

  /// True while the assistant reply is still being generated.
  final bool isStreaming;

  bool get isUser => role == 'user';

  Map<String, String> toJson() => {'role': role, 'content': content};
}
