import 'package:flutter/material.dart';

import '../services/voice_service.dart';
import '../theme/ropac_theme.dart';
import 'glass_panel.dart';

class VoiceBar extends StatelessWidget {
  const VoiceBar({
    super.key,
    required this.voice,
    required this.enabled,
    required this.onMicTap,
  });

  final VoiceService voice;
  final bool enabled;
  final VoidCallback onMicTap;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: voice,
      builder: (context, _) {
        final starting = voice.isStarting;
        final listening = voice.isListening;
        final session = voice.isMicSession;
        final near = voice.hadNearVoice;
        final level = voice.inputLevel;
        return Padding(
          padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
          child: LayoutBuilder(
            builder: (context, constraints) {
              final stacked = constraints.maxWidth < 420;
              final status = _statusLine(starting, listening, near);
              final mic = _MicButton(
                active: listening,
                starting: starting,
                enabled: enabled && voice.isAvailable,
                onTap: enabled ? onMicTap : null,
              );
              final speakToggle = Switch(
                value: voice.speakReplies,
                onChanged: enabled ? (v) => voice.speakReplies = v : null,
                activeTrackColor: RoPacColors.accent.withValues(alpha: 0.5),
                materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
              );

              Widget statusColumn() => Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        status,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          color: session
                              ? (near
                                  ? RoPacColors.accent
                                  : RoPacColors.textMuted)
                              : RoPacColors.textMuted,
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      if (session) ...[
                        const SizedBox(height: 6),
                        _LevelMeter(level: level, active: near),
                      ],
                      if (session && voice.partialText.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 4),
                          child: Text(
                            voice.partialText,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              color: RoPacColors.textPrimary,
                              fontSize: 13,
                            ),
                          ),
                        ),
                      if (voice.error != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 4),
                          child: Text(
                            voice.error!,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              color: RoPacColors.danger,
                              fontSize: 11,
                            ),
                          ),
                        ),
                    ],
                  );

              return GlassPanel(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                radius: 16,
                child: stacked
                    ? Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Row(
                            children: [
                              mic,
                              const SizedBox(width: 10),
                              Expanded(child: statusColumn()),
                            ],
                          ),
                          const SizedBox(height: 8),
                          Row(
                            mainAxisAlignment: MainAxisAlignment.end,
                            children: [
                              const Icon(
                                Icons.volume_up_rounded,
                                size: 16,
                                color: RoPacColors.textMuted,
                              ),
                              const SizedBox(width: 6),
                              speakToggle,
                            ],
                          ),
                        ],
                      )
                    : Row(
                        children: [
                          mic,
                          const SizedBox(width: 10),
                          Expanded(child: statusColumn()),
                          const SizedBox(width: 6),
                          const Icon(
                            Icons.volume_up_rounded,
                            size: 16,
                            color: RoPacColors.textMuted,
                          ),
                          speakToggle,
                        ],
                      ),
              );
            },
          ),
        );
      },
    );
  }

  String _statusLine(bool starting, bool listening, bool near) {
    if (starting) return 'Starting microphone…';
    if (!listening) {
      if (voice.neuralTtsReady) {
        return 'Tap mic · neural voice (offline Piper)';
      }
      return 'Tap mic · speak near laptop (30–50 cm)';
    }
    if (!near) {
      return 'Waiting for your voice near the mic…';
    }
    return 'Listening — sends ~5s after you go quiet';
  }
}

class _LevelMeter extends StatelessWidget {
  const _LevelMeter({required this.level, required this.active});

  final double level;
  final bool active;

  @override
  Widget build(BuildContext context) {
    const bars = 5;
    return Row(
      children: List.generate(bars, (i) {
        final threshold = (i + 1) / bars;
        final on = level >= threshold * 0.85;
        return Padding(
          padding: EdgeInsets.only(right: i < bars - 1 ? 3 : 0),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 80),
            width: 4,
            height: 6 + (i + 1) * 3.0,
            decoration: BoxDecoration(
              color: on
                  ? (active ? RoPacColors.accent : RoPacColors.textMuted)
                  : RoPacColors.surfaceHigh,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
        );
      }),
    );
  }
}

class _MicButton extends StatefulWidget {
  const _MicButton({
    required this.active,
    required this.starting,
    required this.enabled,
    required this.onTap,
  });

  final bool active;
  final bool starting;
  final bool enabled;
  final VoidCallback? onTap;

  @override
  State<_MicButton> createState() => _MicButtonState();
}

class _MicButtonState extends State<_MicButton>
    with SingleTickerProviderStateMixin {
  late final AnimationController _pulse;

  @override
  void initState() {
    super.initState();
    _pulse = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    );
  }

  @override
  void didUpdateWidget(covariant _MicButton oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.active && !_pulse.isAnimating) {
      _pulse.repeat(reverse: true);
    } else if (!widget.active) {
      _pulse.stop();
      _pulse.reset();
    }
  }

  @override
  void dispose() {
    _pulse.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final session = widget.active || widget.starting;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: widget.onTap,
        borderRadius: BorderRadius.circular(28),
        child: AnimatedBuilder(
          animation: _pulse,
          builder: (context, child) {
            final scale = widget.active ? 1.0 + _pulse.value * 0.08 : 1.0;
            return Transform.scale(scale: scale, child: child);
          },
          child: Container(
            width: 52,
            height: 52,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: widget.active
                  ? const LinearGradient(
                      colors: [RoPacColors.danger, Color(0xFFFF6B6B)],
                    )
                  : widget.starting
                      ? const LinearGradient(
                          colors: [RoPacColors.accentDim, RoPacColors.accent],
                        )
                      : LinearGradient(
                          colors: widget.enabled
                              ? [RoPacColors.accentDim, RoPacColors.accent]
                              : [
                                  RoPacColors.surfaceHigh,
                                  RoPacColors.surfaceHigh,
                                ],
                        ),
              boxShadow: widget.active
                  ? [
                      BoxShadow(
                        color: RoPacColors.danger.withValues(alpha: 0.45),
                        blurRadius: 16,
                        spreadRadius: 2,
                      ),
                    ]
                  : null,
            ),
            child: widget.starting
                ? const Padding(
                    padding: EdgeInsets.all(14),
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Colors.white,
                    ),
                  )
                : Icon(
                    session ? Icons.stop_rounded : Icons.mic_rounded,
                    color:
                        widget.enabled ? Colors.white : RoPacColors.textMuted,
                    size: 26,
                  ),
          ),
        ),
      ),
    );
  }
}

class VoiceListeningBanner extends StatelessWidget {
  const VoiceListeningBanner({
    super.key,
    required this.partial,
    required this.hadNearVoice,
  });

  final String partial;
  final bool hadNearVoice;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: RoPacColors.accent.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: RoPacColors.accent.withValues(alpha: 0.4)),
      ),
      child: Row(
        children: [
          const SizedBox(
            width: 22,
            height: 22,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              color: RoPacColors.accent,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              partial.isEmpty
                  ? (hadNearVoice
                      ? 'Speak — I send when you pause ~5 sec (quiet)'
                      : 'Move closer (30–50 cm) and speak')
                  : partial,
              style: const TextStyle(
                color: RoPacColors.textPrimary,
                fontSize: 14,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
