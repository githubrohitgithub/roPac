import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme/ropac_theme.dart';

/// Full-chat-area neural network animation while the model is generating.
class NeuralNetworkBackground extends StatefulWidget {
  const NeuralNetworkBackground({super.key});

  @override
  State<NeuralNetworkBackground> createState() => _NeuralNetworkBackgroundState();
}

class _NeuralNetworkBackgroundState extends State<NeuralNetworkBackground>
    with SingleTickerProviderStateMixin {
  late final AnimationController _pulse;

  @override
  void initState() {
    super.initState();
    _pulse = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2800),
    )..repeat();
  }

  @override
  void dispose() {
    _pulse.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: AnimatedBuilder(
        animation: _pulse,
        builder: (context, _) {
          return Stack(
            fit: StackFit.expand,
            children: [
              CustomPaint(
                painter: NeuralNetworkPainter(
                  t: _pulse.value,
                  intensity: 1.0,
                ),
              ),
              DecoratedBox(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [
                      RoPacColors.bgMid.withValues(alpha: 0.55),
                      RoPacColors.bgMid.withValues(alpha: 0.72),
                      RoPacColors.bgMid.withValues(alpha: 0.88),
                    ],
                    stops: const [0.0, 0.45, 1.0],
                  ),
                ),
              ),
              DecoratedBox(
                decoration: BoxDecoration(
                  gradient: RadialGradient(
                    center: const Alignment(0.2, 0.35),
                    radius: 0.95,
                    colors: [
                      RoPacColors.accent.withValues(alpha: 0.06),
                      Colors.transparent,
                    ],
                  ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

class NeuralNetworkPainter extends CustomPainter {
  NeuralNetworkPainter({
    required this.t,
    this.intensity = 1.0,
  });

  final double t;
  final double intensity;

  static const _layers = [4, 6, 6, 4];

  @override
  void paint(Canvas canvas, Size size) {
    if (size.width < 1 || size.height < 1) return;

    final nodes = <Offset>[];
    final layerIndices = <List<int>>[];
    final nodeLayer = <int>[];

    var idx = 0;
    for (var l = 0; l < _layers.length; l++) {
      final count = _layers[l];
      final layer = <int>[];
      final x = size.width * (l + 0.5) / _layers.length;
      for (var n = 0; n < count; n++) {
        final y = size.height * (n + 1) / (count + 1);
        nodes.add(Offset(x, y));
        layer.add(idx);
        nodeLayer.add(l);
        idx++;
      }
      layerIndices.add(layer);
    }

    var edge = 0;
    for (var l = 0; l < layerIndices.length - 1; l++) {
      for (final a in layerIndices[l]) {
        for (final b in layerIndices[l + 1]) {
          final wave = math.sin((t * math.pi * 2) + edge * 0.28);
          final active = (wave + 1) * 0.5;
          final paint = Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = (0.6 + active * 0.9) * intensity
            ..color = Color.lerp(
              RoPacColors.violet.withValues(alpha: 0.08 * intensity),
              RoPacColors.accent.withValues(alpha: 0.42 * intensity),
              active,
            )!;
          canvas.drawLine(nodes[a], nodes[b], paint);
          edge++;
        }
      }
    }

    for (var i = 0; i < nodes.length; i++) {
      final layer = nodeLayer[i];
      final localPhase = t * math.pi * 2 + layer * 0.85 + i * 0.15;
      final activation = 0.3 + 0.7 * ((math.sin(localPhase) + 1) * 0.5);
      final center = nodes[i];
      final radius = (4.0 + activation * 3.5) * intensity;

      final glow = Paint()
        ..color = RoPacColors.accent.withValues(alpha: 0.12 * activation * intensity)
        ..maskFilter = MaskFilter.blur(BlurStyle.normal, 10 * intensity);
      canvas.drawCircle(center, radius + 6, glow);

      final fill = Paint()
        ..color = Color.lerp(
          RoPacColors.violet.withValues(alpha: 0.25 * intensity),
          RoPacColors.accent.withValues(alpha: 0.85 * intensity),
          activation,
        )!;
      canvas.drawCircle(center, radius, fill);
    }
  }

  @override
  bool shouldRepaint(covariant NeuralNetworkPainter oldDelegate) =>
      oldDelegate.t != t || oldDelegate.intensity != intensity;
}
