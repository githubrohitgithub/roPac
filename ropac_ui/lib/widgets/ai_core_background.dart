import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

import '../theme/ropac_theme.dart';

/// AI core visual — continuous motion while the model is ready (no loop reset).
class AiCoreBackground extends StatefulWidget {
  const AiCoreBackground({super.key, required this.modelActive});

  final bool modelActive;

  @override
  State<AiCoreBackground> createState() => _AiCoreBackgroundState();
}

class _AiCoreBackgroundState extends State<AiCoreBackground>
    with SingleTickerProviderStateMixin {
  late final Ticker _ticker;
  double _seconds = 0;
  Duration _timeOffset = Duration.zero;

  @override
  void initState() {
    super.initState();
    _ticker = createTicker(_onTick);
    _syncAnimation();
  }

  @override
  void didUpdateWidget(covariant AiCoreBackground oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.modelActive != widget.modelActive) {
      _syncAnimation();
    }
  }

  void _onTick(Duration elapsed) {
    if (!widget.modelActive || !mounted) return;
    final total = _timeOffset + elapsed;
    setState(() => _seconds = total.inMicroseconds / 1000000.0);
  }

  void _syncAnimation() {
    if (widget.modelActive) {
      if (!_ticker.isActive) {
        _ticker.start();
      }
    } else {
      _timeOffset = Duration(microseconds: (_seconds * 1000000).round());
      _ticker.stop();
      setState(() {});
    }
  }

  @override
  void dispose() {
    _ticker.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final seconds = _seconds;
    return IgnorePointer(
      child: _AiCoreScene(
        seconds: seconds,
        dormant: !widget.modelActive,
      ),
    );
  }
}

class _AiCoreScene extends StatelessWidget {
  const _AiCoreScene({required this.seconds, required this.dormant});

  final double seconds;
  final bool dormant;

  @override
  Widget build(BuildContext context) {
    return Stack(
      fit: StackFit.expand,
      children: [
        CustomPaint(
          painter: AiCorePainter(seconds: seconds, dormant: dormant),
        ),
        DecoratedBox(
          decoration: BoxDecoration(
            gradient: RadialGradient(
              center: Alignment.center,
              radius: 1.1,
              colors: [
                Colors.transparent,
                RoPacColors.bgMid.withValues(alpha: dormant ? 0.5 : 0.35),
                RoPacColors.bgMid.withValues(alpha: 0.82),
              ],
              stops: const [0.35, 0.7, 1.0],
            ),
          ),
        ),
      ],
    );
  }
}

class AiCorePainter extends CustomPainter {
  AiCorePainter({required this.seconds, this.dormant = false});

  /// Elapsed run time in seconds (never wraps to zero while active).
  final double seconds;
  final bool dormant;

  @override
  void paint(Canvas canvas, Size size) {
    if (size.width < 1 || size.height < 1) return;

    final center = Offset(size.width * 0.5, size.height * 0.44);
    final s = dormant ? 0.0 : seconds;

    _drawField(canvas, size, center, s);
    _drawOrbits(canvas, center, s);
    _drawCore(canvas, center, s);
    if (!dormant) {
      _drawSparks(canvas, center, s);
    }
  }

  void _drawField(Canvas canvas, Size size, Offset center, double s) {
    const lines = 12;
    for (var i = 0; i < lines; i++) {
      final angle = (i / lines) * math.pi * 2 + s * 0.12;
      final len = math.min(size.width, size.height) * 0.48;
      final end = center + Offset(math.cos(angle), math.sin(angle)) * len;
      final pulse = dormant ? 0.2 : (math.sin(s * 0.85 + i * 0.5) + 1) * 0.5;
      final paint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 0.6
        ..color = RoPacColors.textMuted.withValues(
          alpha: dormant ? 0.06 : 0.04 + pulse * 0.06,
        );
      canvas.drawLine(center, end, paint);
    }
  }

  void _drawOrbits(Canvas canvas, Offset center, double s) {
    const configs = [
      (rx: 72.0, ry: 28.0, speed: 1.0, tilt: 0.35, alpha: 0.35),
      (rx: 110.0, ry: 42.0, speed: -0.65, tilt: -0.2, alpha: 0.22),
      (rx: 148.0, ry: 56.0, speed: 0.4, tilt: 0.55, alpha: 0.14),
    ];

    for (final c in configs) {
      canvas.save();
      canvas.translate(center.dx, center.dy);
      canvas.rotate(c.tilt + (dormant ? 0 : s * 0.045 * c.speed));

      final orbitAlpha = dormant ? c.alpha * 0.35 : c.alpha;
      final orbitPaint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.2
        ..color = RoPacColors.violet.withValues(alpha: orbitAlpha);

      canvas.drawOval(
        Rect.fromCenter(center: Offset.zero, width: c.rx * 2, height: c.ry * 2),
        orbitPaint,
      );

      if (!dormant) {
        final dotAngle = s * 0.52 * c.speed;
        final dot = Offset(math.cos(dotAngle) * c.rx, math.sin(dotAngle) * c.ry);
        final dotPaint = Paint()
          ..color = RoPacColors.accent.withValues(alpha: 0.75)
          ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 4);
        canvas.drawCircle(dot, 5, dotPaint);
        canvas.drawCircle(
          dot,
          2.5,
          Paint()..color = Colors.white.withValues(alpha: 0.9),
        );
      }

      canvas.restore();
    }
  }

  void _drawCore(Canvas canvas, Offset center, double s) {
    final pulse = dormant ? 1.0 : 0.88 + 0.12 * math.sin(s * 1.05);
    final r = 28.0 * (dormant ? 0.82 : pulse);

    if (!dormant) {
      final glowPulse = 0.9 + 0.1 * math.sin(s * 0.8);
      final outerGlow = Paint()
        ..shader = RadialGradient(
          colors: [
            RoPacColors.accent.withValues(alpha: 0.32 * glowPulse),
            RoPacColors.violet.withValues(alpha: 0.1),
            Colors.transparent,
          ],
          stops: const [0.0, 0.45, 1.0],
        ).createShader(Rect.fromCircle(center: center, radius: r * 2.8))
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 18);
      canvas.drawCircle(center, r * 2.8, outerGlow);
    }

    final coreShader = RadialGradient(
      colors: dormant
          ? [
              RoPacColors.textMuted.withValues(alpha: 0.5),
              RoPacColors.surfaceHigh,
              RoPacColors.bgMid,
            ]
          : [
              Colors.white.withValues(alpha: 0.95),
              RoPacColors.accent,
              RoPacColors.accentDim,
              RoPacColors.violet.withValues(alpha: 0.5),
            ],
      stops: dormant ? const [0.0, 0.5, 1.0] : const [0.0, 0.25, 0.6, 1.0],
    ).createShader(Rect.fromCircle(center: center, radius: r));

    canvas.drawCircle(center, r, Paint()..shader = coreShader);

    final ringR = r * 1.55;
    final ringPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = dormant ? 1.0 : 2
      ..color = dormant
          ? RoPacColors.textMuted.withValues(alpha: 0.25)
          : RoPacColors.accent.withValues(
              alpha: 0.45 + 0.22 * math.sin(s * 0.92),
            );
    canvas.drawCircle(center, ringR, ringPaint);

    final innerRing = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1
      ..color = Colors.white.withValues(alpha: dormant ? 0.08 : 0.2);
    canvas.drawCircle(center, r * 0.55, innerRing);
  }

  void _drawSparks(Canvas canvas, Offset center, double s) {
    const count = 8;
    for (var i = 0; i < count; i++) {
      final a = (i / count) * math.pi * 2 + s * 0.38;
      final dist = 52 + 18 * math.sin(s * 0.65 + i * 0.9);
      final p = center + Offset(math.cos(a), math.sin(a)) * dist;
      final flicker = (math.sin(s * 1.15 + i * 1.7) + 1) * 0.5;
      final alpha = 0.12 + flicker * 0.48;
      final radius = 1.0 + flicker * 1.6;
      canvas.drawCircle(
        p,
        radius,
        Paint()..color = RoPacColors.accent.withValues(alpha: alpha),
      );
    }
  }

  @override
  bool shouldRepaint(covariant AiCorePainter oldDelegate) =>
      oldDelegate.dormant != dormant ||
      (seconds - oldDelegate.seconds).abs() > 0.008;
}
