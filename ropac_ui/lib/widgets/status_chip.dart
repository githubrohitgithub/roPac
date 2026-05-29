import 'package:flutter/material.dart';

import '../services/model_controller.dart';
import '../theme/ropac_theme.dart';

class ModelStatusChip extends StatelessWidget {
  const ModelStatusChip({super.key, required this.state, this.compact = false});

  final ModelRunState state;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final (color, label, icon) = switch (state) {
      ModelRunState.ready => (
          RoPacColors.accentGreen,
          'Ready',
          Icons.bolt_rounded,
        ),
      ModelRunState.starting => (
          RoPacColors.warn,
          'Starting',
          Icons.hourglass_top_rounded,
        ),
      ModelRunState.stopping => (
          RoPacColors.warn,
          'Stopping',
          Icons.hourglass_bottom_rounded,
        ),
      ModelRunState.stopped => (
          RoPacColors.textMuted,
          'Stopped',
          Icons.power_settings_new_rounded,
        ),
    };

    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 7 : 12,
        vertical: compact ? 2 : 6,
      ),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(compact ? 10 : 24),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: compact ? 11 : 14, color: color),
          SizedBox(width: compact ? 4 : 6),
          Text(
            label,
            style: TextStyle(
              color: color,
              fontSize: compact ? 10 : 12,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.2,
            ),
          ),
        ],
      ),
    );
  }
}
