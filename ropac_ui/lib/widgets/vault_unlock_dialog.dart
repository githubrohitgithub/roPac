import 'package:flutter/material.dart';

import '../services/ropac_local.dart';
import '../theme/ropac_theme.dart';

/// Owner password to decrypt personal data for this app session.
class VaultUnlockDialog {
  static Future<bool> show(
    BuildContext context,
    RopacLocal ropac,
  ) async {
    final controller = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        backgroundColor: RoPacColors.surfaceHigh,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: const Text(
          'Owner password required',
          style: TextStyle(color: RoPacColors.textPrimary, fontSize: 18),
        ),
        content: TextField(
          controller: controller,
          obscureText: true,
          autofocus: true,
          style: const TextStyle(color: RoPacColors.textPrimary),
          decoration: const InputDecoration(
            labelText: 'Owner password',
          ),
          onSubmitted: (_) => Navigator.pop(ctx, true),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Unlock'),
          ),
        ],
      ),
    );
    final password = controller.text.trim();
    controller.dispose();
    if (ok != true || password.isEmpty) return false;

    try {
      final setup = await ropac.personalDataSetup(password: password);
      if (setup['needs_enable'] == true || setup['needs_unlock'] == true) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              behavior: SnackBarBehavior.floating,
              content: Text(
                setup['message']?.toString() ?? 'Could not unlock personal data',
              ),
            ),
          );
        }
        return false;
      }
      return setup['unlocked'] != false;
    } on RopacException catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            behavior: SnackBarBehavior.floating,
            content: Text(e.message),
          ),
        );
      }
      return false;
    }
  }
}
