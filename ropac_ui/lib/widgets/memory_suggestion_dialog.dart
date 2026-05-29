import 'package:flutter/material.dart';

import '../theme/ropac_theme.dart';

class MemorySuggestionDialog {
  static Future<List<String>?> show(
    BuildContext context,
    List<String> facts,
  ) async {
    if (facts.isEmpty) return null;

    final selected = <String>{...facts};

    return showDialog<List<String>>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (context, setState) {
          return AlertDialog(
            backgroundColor: RoPacColors.surfaceHigh,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(20),
            ),
            title: const Text(
              'Save to memory?',
              style: TextStyle(color: RoPacColors.textPrimary),
            ),
            content: SizedBox(
              width: 420,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 320),
                child: SingleChildScrollView(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'RoPac found facts worth remembering. Choose what to keep.',
                        style: TextStyle(
                          color: RoPacColors.textMuted,
                          height: 1.4,
                        ),
                      ),
                      const SizedBox(height: 12),
                      ...facts.map((fact) {
                        return CheckboxListTile(
                          value: selected.contains(fact),
                          onChanged: (on) {
                            setState(() {
                              if (on == true) {
                                selected.add(fact);
                              } else {
                                selected.remove(fact);
                              }
                            });
                          },
                          controlAffinity: ListTileControlAffinity.leading,
                          contentPadding: EdgeInsets.zero,
                          dense: true,
                          title: Text(
                            fact,
                            style: const TextStyle(
                              color: RoPacColors.textPrimary,
                              fontSize: 14,
                            ),
                          ),
                        );
                      }),
                    ],
                  ),
                ),
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Not now'),
              ),
              FilledButton(
                onPressed: selected.isEmpty
                    ? null
                    : () => Navigator.pop(ctx, selected.toList()),
                child: const Text('Save selected'),
              ),
            ],
          );
        },
      ),
    );
  }
}
