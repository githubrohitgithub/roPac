#!/usr/bin/swift
import AVFoundation
import AppKit

guard CommandLine.arguments.count > 1 else {
  fputs("usage: play_wav.swift <path.wav>\n", stderr)
  exit(2)
}
let path = CommandLine.arguments[1]
guard FileManager.default.fileExists(atPath: path) else {
  fputs("not found: \(path)\n", stderr)
  exit(2)
}

final class Delegate: NSObject, AVAudioPlayerDelegate {
  var done = false
  var ok = false
  func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
    ok = flag
    done = true
    CFRunLoopStop(CFRunLoopGetMain())
  }
  func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
    fputs("decode: \(error?.localizedDescription ?? "?")\n", stderr)
    done = true
    CFRunLoopStop(CFRunLoopGetMain())
  }
}

let delegate = Delegate()
let url = URL(fileURLWithPath: path)

if let sound = NSSound(contentsOfFile: path, byReference: true) {
  sound.volume = 1.0
  if sound.play() {
    let deadline = Date().addingTimeInterval(120)
    while sound.isPlaying && Date() < deadline {
      RunLoop.current.run(until: Date().addingTimeInterval(0.05))
    }
    if !sound.isPlaying { exit(0) }
    fputs("NSSound timeout\n", stderr)
  }
}

do {
  let player = try AVAudioPlayer(contentsOf: url)
  player.delegate = delegate
  player.volume = 1.0
  player.prepareToPlay()
  if !player.play() {
    fputs("AVAudioPlayer.play() false\n", stderr)
    exit(1)
  }
  CFRunLoopRun()
  exit(delegate.ok ? 0 : 1)
} catch {
  fputs("\(error)\n", stderr)
  exit(1)
}
