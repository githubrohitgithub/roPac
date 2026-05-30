import 'dart:math' as math;
import 'package:flutter/material.dart';

import '../theme/ropac_theme.dart';

class KnowledgeGraphWidget extends StatefulWidget {
  const KnowledgeGraphWidget({
    super.key,
    required this.ragMetadata,
  });

  final Map<String, dynamic> ragMetadata;

  @override
  State<KnowledgeGraphWidget> createState() => _KnowledgeGraphWidgetState();
}

class _KnowledgeGraphWidgetState extends State<KnowledgeGraphWidget>
    with SingleTickerProviderStateMixin {
  bool _expanded = false;
  late final AnimationController _floatingController;
  Map<String, dynamic>? _selectedNode;

  @override
  void initState() {
    super.initState();
    _floatingController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 4),
    )..repeat();
  }

  @override
  void dispose() {
    _floatingController.dispose();
    super.dispose();
  }

  Color _getNodeColor(String type) {
    switch (type) {
      case 'memory':
        return RoPacColors.violet;
      case 'document':
        return RoPacColors.accentGreen;
      case 'attachment':
        return RoPacColors.warn;
      default:
        return RoPacColors.accent;
    }
  }

  IconData _getNodeIcon(String type) {
    switch (type) {
      case 'memory':
        return Icons.psychology_outlined;
      case 'document':
        return Icons.description_outlined;
      case 'attachment':
        return Icons.attach_file_outlined;
      default:
        return Icons.circle;
    }
  }

  @override
  Widget build(BuildContext context) {
    final nodes = (widget.ragMetadata['nodes'] as List<dynamic>? ?? []);
    final conflicts = (widget.ragMetadata['conflicts'] as List<dynamic>? ?? []);

    if (nodes.isEmpty) return const SizedBox.shrink();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        InkWell(
          onTap: () {
            setState(() {
              _expanded = !_expanded;
              if (!_expanded) _selectedNode = null;
            });
          },
          borderRadius: BorderRadius.circular(10),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 8),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  Icons.hub_outlined,
                  size: 16,
                  color: RoPacColors.accent.withValues(alpha: 0.9),
                ),
                const SizedBox(width: 6),
                Text(
                  'Retrieved Knowledge Graph (${nodes.length} source${nodes.length > 1 ? 's' : ''})',
                  style: const TextStyle(
                    color: RoPacColors.accent,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                if (conflicts.isNotEmpty) ...[
                  const SizedBox(width: 8),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: RoPacColors.danger.withValues(alpha: 0.2),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(
                        color: RoPacColors.danger.withValues(alpha: 0.4),
                      ),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          Icons.warning_amber_rounded,
                          size: 11,
                          color: RoPacColors.danger,
                        ),
                        const SizedBox(width: 3),
                        Text(
                          '${conflicts.length} Conflict${conflicts.length > 1 ? 's' : ''}',
                          style: TextStyle(
                            color: RoPacColors.danger,
                            fontSize: 10,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
                const Spacer(),
                Icon(
                  _expanded ? Icons.keyboard_arrow_up : Icons.keyboard_arrow_down,
                  size: 16,
                  color: RoPacColors.textMuted,
                ),
              ],
            ),
          ),
        ),
        if (_expanded) ...[
          const SizedBox(height: 8),
          LayoutBuilder(
            builder: (context, constraints) {
              final width = constraints.maxWidth;
              const height = 260.0;
              final center = Offset(width / 2, height / 2);
              final radius = math.min(width, height) * 0.38;

              // Calculate positions of each node distributed in a circle
              final nodePositions = <String, Offset>{};
              for (var i = 0; i < nodes.length; i++) {
                final angle = (i * 2 * math.pi / nodes.length) - (math.pi / 2);
                final node = nodes[i] as Map<String, dynamic>;
                final id = node['id'] as String;
                nodePositions[id] = Offset(
                  center.dx + radius * math.cos(angle),
                  center.dy + radius * math.sin(angle),
                );
              }

              return AnimatedBuilder(
                animation: _floatingController,
                builder: (context, child) {
                  // Apply gentle floating offsets to node positions using sine waves
                  final floatedPositions = <String, Offset>{};
                  var index = 0;
                  nodePositions.forEach((id, pos) {
                    final phase = index * (math.pi / 4);
                    final floatY = 6.0 * math.sin(_floatingController.value * 2 * math.pi + phase);
                    final floatX = 3.0 * math.cos(_floatingController.value * 2 * math.pi + phase);
                    floatedPositions[id] = Offset(pos.dx + floatX, pos.dy + floatY);
                    index++;
                  });

                  final queryPulse = 2.0 * math.sin(_floatingController.value * 2 * math.pi);

                  return Container(
                    height: height,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(16),
                      color: RoPacColors.bgDeep.withValues(alpha: 0.6),
                      border: Border.all(color: RoPacColors.border),
                    ),
                    child: Stack(
                      clipBehavior: Clip.antiAlias,
                      children: [
                        // 1. Draw Network Connections (Custom Paint)
                        Positioned.fill(
                          child: CustomPaint(
                            painter: _GraphPainter(
                              center: center,
                              floatedPositions: floatedPositions,
                              conflicts: conflicts,
                              pulseValue: _floatingController.value,
                            ),
                          ),
                        ),

                        // 2. Query Center Node
                        Positioned(
                          left: center.dx - 22,
                          top: center.dy - 22,
                          child: Container(
                            width: 44,
                            height: 44,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              color: RoPacColors.bgMid,
                              border: Border.all(
                                color: RoPacColors.accent,
                                width: 2.0,
                              ),
                              boxShadow: [
                                BoxShadow(
                                  color: RoPacColors.accent.withValues(alpha: 0.4),
                                  blurRadius: 10 + queryPulse,
                                  spreadRadius: 1 + queryPulse / 2,
                                ),
                              ],
                            ),
                            child: const Center(
                              child: Icon(
                                Icons.hub,
                                color: RoPacColors.accent,
                                size: 20,
                              ),
                            ),
                          ),
                        ),

                        // 3. Render Floating Graph Nodes
                        ...nodes.map((n) {
                          final node = n as Map<String, dynamic>;
                          final id = node['id'] as String;
                          final type = node['type'] as String;
                          final color = _getNodeColor(type);
                          final pos = floatedPositions[id] ?? center;
                          final isSelected = _selectedNode?['id'] == id;

                          return Positioned(
                            left: pos.dx - 18,
                            top: pos.dy - 18,
                            child: GestureDetector(
                              onTap: () {
                                setState(() {
                                  _selectedNode = isSelected ? null : node;
                                });
                              },
                              child: Container(
                                width: 36,
                                height: 36,
                                decoration: BoxDecoration(
                                  shape: BoxShape.circle,
                                  color: isSelected ? color : RoPacColors.surfaceHigh,
                                  border: Border.all(
                                    color: color,
                                    width: 1.5,
                                  ),
                                  boxShadow: [
                                    BoxShadow(
                                      color: color.withValues(alpha: isSelected ? 0.5 : 0.25),
                                      blurRadius: isSelected ? 12 : 6,
                                    ),
                                    if (node['conflict_with'] != null &&
                                        (node['conflict_with'] as String).isNotEmpty)
                                      BoxShadow(
                                        color: RoPacColors.danger.withValues(alpha: 0.4),
                                        blurRadius: 8,
                                        spreadRadius: 1,
                                      ),
                                  ],
                                ),
                                child: Center(
                                  child: Icon(
                                    _getNodeIcon(type),
                                    color: isSelected ? Colors.white : color,
                                    size: 16,
                                  ),
                                ),
                              ),
                            ),
                          );
                        }),

                        // 4. Slide-in Glassmorphic Detail Panel
                        if (_selectedNode != null)
                          Positioned(
                            left: 10,
                            right: 10,
                            bottom: 10,
                            child: AnimatedOpacity(
                              opacity: _selectedNode != null ? 1.0 : 0.0,
                              duration: const Duration(milliseconds: 200),
                              child: Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 14,
                                  vertical: 10,
                                ),
                                decoration: BoxDecoration(
                                  borderRadius: BorderRadius.circular(12),
                                  color: RoPacColors.surfaceHigh.withValues(alpha: 0.94),
                                  border: Border.all(
                                    color: _getNodeColor(_selectedNode!['type']).withValues(alpha: 0.4),
                                  ),
                                  boxShadow: [
                                    BoxShadow(
                                      color: Colors.black.withValues(alpha: 0.3),
                                      blurRadius: 12,
                                    ),
                                  ],
                                ),
                                child: Column(
                                  mainAxisSize: MainAxisSize.min,
                                  crossAxisAlignment: CrossAxisAlignment.stretch,
                                  children: [
                                    Row(
                                      children: [
                                        Container(
                                          width: 8,
                                          height: 8,
                                          decoration: BoxDecoration(
                                            shape: BoxShape.circle,
                                            color: _getNodeColor(_selectedNode!['type']),
                                          ),
                                        ),
                                        const SizedBox(width: 6),
                                        Expanded(
                                          child: Text(
                                            '${_selectedNode!['type'].toString().toUpperCase()}: ${_selectedNode!['source']}',
                                            style: const TextStyle(
                                              fontSize: 11,
                                              fontWeight: FontWeight.bold,
                                              color: RoPacColors.textPrimary,
                                            ),
                                            maxLines: 1,
                                            overflow: TextOverflow.ellipsis,
                                          ),
                                        ),
                                        const SizedBox(width: 8),
                                        Text(
                                          'Score: ${_selectedNode!['score']}',
                                          style: TextStyle(
                                            fontSize: 10,
                                            fontWeight: FontWeight.w600,
                                            color: _getNodeColor(_selectedNode!['type']),
                                          ),
                                        ),
                                        const SizedBox(width: 6),
                                        IconButton(
                                          icon: const Icon(Icons.close, size: 14),
                                          padding: EdgeInsets.zero,
                                          constraints: const BoxConstraints(),
                                          onPressed: () {
                                            setState(() => _selectedNode = null);
                                          },
                                        ),
                                      ],
                                    ),
                                    if (_selectedNode!['conflict_with'] != null &&
                                        (_selectedNode!['conflict_with'] as String).isNotEmpty) ...[
                                      const SizedBox(height: 4),
                                      Container(
                                        padding: const EdgeInsets.symmetric(
                                          horizontal: 6,
                                          vertical: 3,
                                        ),
                                        decoration: BoxDecoration(
                                          color: RoPacColors.danger.withValues(alpha: 0.15),
                                          borderRadius: BorderRadius.circular(4),
                                          border: Border.all(
                                            color: RoPacColors.danger.withValues(alpha: 0.3),
                                          ),
                                        ),
                                        child: Row(
                                          children: [
                                            Icon(
                                              Icons.warning_amber_rounded,
                                              size: 11,
                                              color: RoPacColors.danger,
                                            ),
                                            const SizedBox(width: 4),
                                            Expanded(
                                              child: Text(
                                                'CONFLICT DETECTED: Clashes with ${_selectedNode!['conflict_with']}',
                                                style: TextStyle(
                                                  color: RoPacColors.danger,
                                                  fontSize: 9,
                                                  fontWeight: FontWeight.bold,
                                                ),
                                                maxLines: 1,
                                                overflow: TextOverflow.ellipsis,
                                              ),
                                            ),
                                          ],
                                        ),
                                      ),
                                    ],
                                    const SizedBox(height: 6),
                                    Container(
                                      constraints: const BoxConstraints(maxHeight: 70),
                                      padding: const EdgeInsets.all(6),
                                      decoration: BoxDecoration(
                                        color: Colors.black.withValues(alpha: 0.25),
                                        borderRadius: BorderRadius.circular(6),
                                      ),
                                      child: SingleChildScrollView(
                                        child: Text(
                                          _selectedNode!['text'] as String? ?? '',
                                          style: const TextStyle(
                                            color: RoPacColors.textPrimary,
                                            fontSize: 10.5,
                                            height: 1.35,
                                          ),
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ),
                      ],
                    ),
                  );
                },
              );
            },
          ),
        ],
      ],
    );
  }
}

class _GraphPainter extends CustomPainter {
  _GraphPainter({
    required this.center,
    required this.floatedPositions,
    required this.conflicts,
    required this.pulseValue,
  });

  final Offset center;
  final Map<String, Offset> floatedPositions;
  final List<dynamic> conflicts;
  final double pulseValue;

  @override
  void paint(Canvas canvas, Size size) {
    // 1. Draw connecting lines from query node (center) to retrieved nodes
    final linePaint = Paint()
      ..color = RoPacColors.accent.withValues(alpha: 0.18)
      ..strokeWidth = 1.0
      ..style = PaintingStyle.stroke;

    floatedPositions.forEach((id, pos) {
      canvas.drawLine(center, pos, linePaint);
      
      // Draw subtle particles traveling along query lines
      final progress = (pulseValue + (id.hashCode % 10) / 10.0) % 1.0;
      final particlePos = Offset.lerp(center, pos, progress)!;
      final particlePaint = Paint()
        ..color = RoPacColors.accent.withValues(alpha: 0.5)
        ..style = PaintingStyle.fill;
      canvas.drawCircle(particlePos, 2.0, particlePaint);
    });

    // 2. Draw red connection lines for conflicts
    final conflictLaserPaint = Paint()
      ..color = RoPacColors.danger.withValues(alpha: 0.8)
      ..strokeWidth = 2.0
      ..style = PaintingStyle.stroke;

    final conflictGlowPaint = Paint()
      ..color = RoPacColors.danger.withValues(alpha: 0.25)
      ..strokeWidth = 5.0
      ..strokeCap = StrokeCap.round
      ..style = PaintingStyle.stroke;

    for (final c in conflicts) {
      final conflict = c as Map<String, dynamic>;
      final id1 = conflict['node_id_1'] as String?;
      final id2 = conflict['node_id_2'] as String?;

      if (id1 != null && id2 != null) {
        final pos1 = floatedPositions[id1];
        final pos2 = floatedPositions[id2];

        if (pos1 != null && pos2 != null) {
          // Draw laser line + glow backing
          canvas.drawLine(pos1, pos2, conflictGlowPaint);
          canvas.drawLine(pos1, pos2, conflictLaserPaint);

          // Draw active glowing pulsing dots along conflict line
          final progress = (pulseValue * 1.5) % 1.0;
          final pulsePos = Offset.lerp(pos1, pos2, progress)!;
          final pulsePaint = Paint()
            ..color = Colors.white
            ..style = PaintingStyle.fill;
          canvas.drawCircle(pulsePos, 3.0, pulsePaint);
        }
      }
    }
  }

  @override
  bool shouldRepaint(covariant _GraphPainter oldDelegate) {
    return oldDelegate.pulseValue != pulseValue ||
        oldDelegate.floatedPositions != floatedPositions;
  }
}
