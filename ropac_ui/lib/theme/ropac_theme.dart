import 'package:flutter/material.dart';

abstract final class RoPacColors {
  static const bgDeep = Color(0xFF070B14);
  static const bgMid = Color(0xFF0E1424);
  static const surface = Color(0xFF151C2E);
  static const surfaceHigh = Color(0xFF1E2738);
  static const border = Color(0x33FFFFFF);
  static const accent = Color(0xFF22D3EE);
  static const accentDim = Color(0xFF0891B2);
  static const accentGreen = Color(0xFF34D399);
  static const violet = Color(0xFF818CF8);
  static const textPrimary = Color(0xFFF1F5F9);
  static const textMuted = Color(0xFF94A3B8);
  static const danger = Color(0xFFF87171);
  static const warn = Color(0xFFFBBF24);
}

class RoPacTheme {
  static ThemeData dark() {
    const scheme = ColorScheme.dark(
      primary: RoPacColors.accent,
      secondary: RoPacColors.violet,
      surface: RoPacColors.surface,
      onSurface: RoPacColors.textPrimary,
    );
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: scheme,
      scaffoldBackgroundColor: RoPacColors.bgDeep,
      fontFamily: '.AppleSystemUIFont',
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: RoPacColors.surface.withValues(alpha: 0.85),
        indicatorColor: RoPacColors.accent.withValues(alpha: 0.18),
        labelTextStyle: WidgetStateProperty.resolveWith((states) {
          final selected = states.contains(WidgetState.selected);
          return TextStyle(
            fontSize: 12,
            fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
            color: selected ? RoPacColors.accent : RoPacColors.textMuted,
          );
        }),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: RoPacColors.surfaceHigh.withValues(alpha: 0.9),
        labelStyle: const TextStyle(color: RoPacColors.textMuted),
        hintStyle: TextStyle(color: RoPacColors.textMuted.withValues(alpha: 0.7)),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: RoPacColors.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: RoPacColors.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: RoPacColors.accent, width: 1.5),
        ),
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: RoPacColors.accentDim,
          foregroundColor: Colors.white,
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
          elevation: 0,
        ),
      ),
    );
  }

  static BoxDecoration pageBackground() => const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            RoPacColors.bgDeep,
            Color(0xFF0C1220),
            Color(0xFF10182B),
          ],
        ),
      );

  static BoxDecoration glassPanel({Color? tint, double radius = 20}) {
    return BoxDecoration(
      borderRadius: BorderRadius.circular(radius),
      color: (tint ?? RoPacColors.surface).withValues(alpha: 0.72),
      border: Border.all(color: RoPacColors.border),
      boxShadow: [
        BoxShadow(
          color: Colors.black.withValues(alpha: 0.35),
          blurRadius: 24,
          offset: const Offset(0, 8),
        ),
      ],
    );
  }

  static BoxDecoration accentGlow({required bool active}) {
    if (!active) return const BoxDecoration();
    return BoxDecoration(
      boxShadow: [
        BoxShadow(
          color: RoPacColors.accentGreen.withValues(alpha: 0.35),
          blurRadius: 20,
          spreadRadius: -4,
        ),
      ],
    );
  }
}
