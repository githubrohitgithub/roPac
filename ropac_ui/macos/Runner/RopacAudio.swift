import AppKit
import AVFoundation
import FlutterMacOS

/// Native audio for RoPac — main-thread AppKit / AVFoundation.
final class RopacAudio: NSObject, AVAudioPlayerDelegate, NSSpeechSynthesizerDelegate {
  static let shared = RopacAudio()

  private var player: AVAudioPlayer?
  private var engine: AVAudioEngine?
  private var playerNode: AVAudioPlayerNode?
  private var nssound: NSSound?
  private var synth: NSSpeechSynthesizer?
  private var pollTimer: Timer?
  private var pendingResult: FlutterResult?
  private var shellProcess: Process?

  func register(messenger: FlutterBinaryMessenger) {
    let channel = FlutterMethodChannel(name: "ropac/audio", binaryMessenger: messenger)
    channel.setMethodCallHandler { [weak self] call, result in
      guard let self else { return }
      switch call.method {
      case "playWav":
        guard let args = call.arguments as? [String: Any],
              let path = args["path"] as? String
        else {
          result(FlutterError(code: "ARGS", message: "path required", details: nil))
          return
        }
        DispatchQueue.main.async {
          self.playWavOnMain(path: path, result: result)
        }
      case "speak":
        guard let args = call.arguments as? [String: Any],
              let text = args["text"] as? String
        else {
          result(FlutterError(code: "ARGS", message: "text required", details: nil))
          return
        }
        let voiceHint = args["voice"] as? String ?? "Rishi"
        DispatchQueue.main.async {
          self.speakOnMain(text: text, voiceHint: voiceHint, result: result)
        }
      case "shellSay":
        guard let args = call.arguments as? [String: Any],
              let text = args["text"] as? String,
              !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else {
          result(FlutterError(code: "ARGS", message: "text required", details: nil))
          return
        }
        let voice = args["voice"] as? String ?? "Rishi"
        DispatchQueue.global(qos: .userInitiated).async {
          self.runShellSay(text: text, voice: voice, result: result)
        }
      case "stop":
        DispatchQueue.main.async {
          self.stopAllOnMain()
          result(nil)
        }
      default:
        result(FlutterMethodNotImplemented)
      }
    }
  }

  private func runShellSay(text: String, voice: String, result: @escaping FlutterResult) {
    let proc = Process()
    proc.executableURL = URL(fileURLWithPath: "/usr/bin/say")
    let v = voice.trimmingCharacters(in: .whitespacesAndNewlines)
    proc.arguments = v.isEmpty ? [text] : ["-v", v, text]
    shellProcess = proc
    do {
      try proc.run()
      proc.waitUntilExit()
      shellProcess = nil
      let ok = proc.terminationStatus == 0
      DispatchQueue.main.async { result(ok) }
    } catch {
      shellProcess = nil
      DispatchQueue.main.async {
        result(FlutterError(code: "SAY", message: error.localizedDescription, details: nil))
      }
    }
  }

  private func playWavOnMain(path: String, result: @escaping FlutterResult) {
    stopAllOnMain()
    guard FileManager.default.fileExists(atPath: path) else {
      result(FlutterError(code: "NOT_FOUND", message: "WAV not found", details: path))
      return
    }

    pendingResult = result

    if playWavWithEngine(path: path) {
      return
    }

    if let sound = NSSound(contentsOfFile: path, byReference: true) {
      sound.volume = 1.0
      nssound = sound
      if sound.play() {
        scheduleSoundCompletion(sound: sound, path: path)
        return
      }
      nssound = nil
    }

    playWavAVOnMain(path: path)
  }

  private func playWavWithEngine(path: String) -> Bool {
    let url = URL(fileURLWithPath: path)
    do {
      let file = try AVAudioFile(forReading: url)
      let eng = AVAudioEngine()
      let node = AVAudioPlayerNode()
      eng.attach(node)
      eng.connect(node, to: eng.mainMixerNode, format: file.processingFormat)
      try eng.start()

      engine = eng
      playerNode = node

      node.scheduleFile(file, at: nil) { [weak self] in
        DispatchQueue.main.async {
          guard let self else { return }
          self.engine?.stop()
          self.engine = nil
          self.playerNode = nil
          let r = self.pendingResult
          self.pendingResult = nil
          r?(true)
        }
      }
      node.play()
      return true
    } catch {
      debugPrint("RopacAudio AVAudioEngine: \(error)")
      engine?.stop()
      engine = nil
      playerNode = nil
      return false
    }
  }

  private func scheduleSoundCompletion(sound: NSSound, path: String) {
    pollTimer?.invalidate()
    var sawPlaying = false
    var ticks = 0
    pollTimer = Timer.scheduledTimer(withTimeInterval: 0.08, repeats: true) { [weak self] timer in
      guard let self else {
        timer.invalidate()
        return
      }
      ticks += 1
      if sound.isPlaying {
        sawPlaying = true
        return
      }
      if !sawPlaying && ticks < 6 {
        return
      }
      timer.invalidate()
      self.pollTimer = nil
      self.nssound = nil
      if !sawPlaying {
        if self.playWavWithEngine(path: path) {
          return
        }
        self.playWavAVOnMain(path: path)
        return
      }
      let r = self.pendingResult
      self.pendingResult = nil
      r?(true)
    }
    RunLoop.main.add(pollTimer!, forMode: .common)
  }

  private func playWavAVOnMain(path: String) {
    let url = URL(fileURLWithPath: path)
    do {
      let p = try AVAudioPlayer(contentsOf: url)
      p.delegate = self
      p.volume = 1.0
      p.prepareToPlay()
      player = p
      if p.play() {
        return
      }
      finishWithError("AVAudioPlayer.play() returned false")
    } catch {
      finishWithError(error.localizedDescription)
    }
  }

  private func speakOnMain(text: String, voiceHint: String, result: @escaping FlutterResult) {
    stopAllOnMain()
    let s = NSSpeechSynthesizer()
    if let match = NSSpeechSynthesizer.availableVoices.first(where: {
      $0.rawValue.localizedCaseInsensitiveContains(voiceHint)
    }) {
      s.setVoice(match)
    }
    s.delegate = self
    synth = s
    pendingResult = result
    if s.startSpeaking(text) {
      return
    }
    synth = nil
    pendingResult = nil
    result(FlutterError(code: "SPEAK_FAILED", message: "NSSpeechSynthesizer failed", details: nil))
  }

  private func finishWithError(_ message: String) {
    player = nil
    engine?.stop()
    engine = nil
    playerNode = nil
    nssound = nil
    synth = nil
    pollTimer?.invalidate()
    pollTimer = nil
    let r = pendingResult
    pendingResult = nil
    r?(FlutterError(code: "PLAY_ERROR", message: message, details: nil))
  }

  private func stopAllOnMain() {
    shellProcess?.terminate()
    shellProcess = nil
    pollTimer?.invalidate()
    pollTimer = nil
    nssound?.stop()
    nssound = nil
    synth?.stopSpeaking()
    synth = nil
    player?.stop()
    player = nil
    playerNode?.stop()
    engine?.stop()
    engine = nil
    playerNode = nil
    pendingResult = nil
  }

  func speechSynthesizer(_ sender: NSSpeechSynthesizer, didFinishSpeaking finishedSpeaking: Bool) {
    guard sender === synth else { return }
    synth = nil
    let r = pendingResult
    pendingResult = nil
    r?(finishedSpeaking)
  }

  func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
    self.player = nil
    let r = pendingResult
    pendingResult = nil
    r?(flag)
  }

  func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
    finishWithError(error?.localizedDescription ?? "decode error")
  }
}
