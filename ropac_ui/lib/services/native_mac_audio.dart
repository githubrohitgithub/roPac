import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// macOS native NSSound / NSSpeechSynthesizer (main-thread AppKit playback).
class NativeMacAudio {
  NativeMacAudio._();

  static const _channel = MethodChannel('ropac/audio');
  static String? lastError;

  static Future<bool> playWav(String path) async {
    lastError = null;
    if (!File(path).existsSync()) {
      lastError = 'WAV missing: $path';
      return false;
    }

    try {
      final ok = await _channel.invokeMethod<bool>('playWav', {'path': path});
      if (ok == true) return true;
      lastError = 'Native WAV player returned false';
    } catch (e, st) {
      lastError = e.toString();
      debugPrint('NativeMacAudio.playWav: $e\n$st');
    }
    return false;
  }

  /// Runs `/usr/bin/say` via native Process (same as Terminal).
  static Future<bool> shellSay(String text, {String voice = 'Rishi'}) async {
    lastError = null;
    if (text.trim().isEmpty) return false;
    try {
      final ok = await _channel.invokeMethod<bool>('shellSay', {
        'text': text,
        'voice': voice,
      });
      if (ok == true) return true;
      lastError = 'shellSay returned false';
    } catch (e, st) {
      lastError = e.toString();
      debugPrint('NativeMacAudio.shellSay: $e\n$st');
    }
    return false;
  }

  static Future<bool> speak(String text, {String voice = 'Rishi'}) async {
    lastError = null;
    if (text.trim().isEmpty) return false;
    try {
      final ok = await _channel.invokeMethod<bool>('speak', {
        'text': text,
        'voice': voice,
      });
      if (ok == true) return true;
      lastError = 'Native speech returned false';
    } catch (e, st) {
      lastError = e.toString();
      debugPrint('NativeMacAudio.speak: $e\n$st');
    }
    return false;
  }

  static Future<void> stop() async {
    try {
      await _channel.invokeMethod<void>('stop');
    } catch (_) {}
  }
}
