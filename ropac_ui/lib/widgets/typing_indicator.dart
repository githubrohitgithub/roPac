import 'package:flutter/material.dart';

import '../theme/ropac_theme.dart';

/// ChatGPT-style thinking dots inside the assistant bubble.
class TypingIndicator extends StatefulWidget {
  const TypingIndicator({super.key});

  @override
  State<TypingIndicator> createState() => _TypingIndicatorState();
}

class _TypingIndicatorState extends State<TypingIndicator>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, _) {
        return Row(
          mainAxisSize: MainAxisSize.min,
          children: List.generate(3, (i) {
            final phase = (_controller.value + i * 0.2) % 1.0;
            final y = -4 * (phase < 0.5 ? phase * 2 : (1 - phase) * 2);
            final opacity = 0.35 + 0.65 * (phase < 0.5 ? phase * 2 : (1 - phase) * 2);
            return Padding(
              padding: EdgeInsets.only(left: i == 0 ? 0 : 5),
              child: Transform.translate(
                offset: Offset(0, y),
                child: Opacity(
                  opacity: opacity,
                  child: Container(
                    width: 7,
                    height: 7,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: RoPacColors.accent.withValues(alpha: 0.9),
                      boxShadow: [
                        BoxShadow(
                          color: RoPacColors.accent.withValues(alpha: 0.35),
                          blurRadius: 4,
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            );
          }),
        );
      },
    );
  }
}
