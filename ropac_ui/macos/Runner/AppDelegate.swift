import Cocoa
import FlutterMacOS
import Carbon

@main
class AppDelegate: FlutterAppDelegate {
  private var hotKeyRef: EventHotKeyRef?

  override func applicationWillFinishLaunching(_ notification: Notification) {
    NSApp.setActivationPolicy(.regular)
    super.applicationWillFinishLaunching(notification)
  }

  override func applicationDidFinishLaunching(_ notification: Notification) {
    super.applicationDidFinishLaunching(notification)

    let menuBar = MenuBarController.shared
    menuBar.onOpen = { [weak self] in self?.showQuickWindow() }
    menuBar.onHide = { NSApp.hide(nil) }
    menuBar.onQuit = { NSApp.terminate(nil) }

    menuBar.install()

    DispatchQueue.main.async {
      MenuBarController.shared.install()
      self.setupGlobalHotKey()
    }
  }

  override func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
    false
  }

  override func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool {
    true
  }

  private func setupGlobalHotKey() {
    var hotKeyID = EventHotKeyID()
    hotKeyID.signature = fourCharCode("RpAC")
    hotKeyID.id = 1

    var eventType = EventTypeSpec(
      eventClass: OSType(kEventClassKeyboard),
      eventKind: UInt32(kEventHotKeyPressed)
    )

    let selfPtr = Unmanaged.passUnretained(self).toOpaque()
    InstallEventHandler(
      GetApplicationEventTarget(),
      { _, _, userData -> OSStatus in
        guard let userData else { return OSStatus(eventNotHandledErr) }
        let delegate = Unmanaged<AppDelegate>.fromOpaque(userData).takeUnretainedValue()
        DispatchQueue.main.async {
          delegate.showQuickWindow()
        }
        return noErr
      },
      1,
      &eventType,
      selfPtr,
      nil
    )

    var ref: EventHotKeyRef?
    let status = RegisterEventHotKey(
      UInt32(kVK_Space),
      UInt32(cmdKey | optionKey),
      hotKeyID,
      GetApplicationEventTarget(),
      0,
      &ref
    )
    if status == noErr {
      hotKeyRef = ref
    } else {
      NSLog("RoPac: global hotkey registration failed (%d)", status)
    }
  }

  private func showQuickWindow() {
    NSApp.setActivationPolicy(.regular)
    NSApp.activate(ignoringOtherApps: true)
    NSApp.unhide(nil)

    if let w = NSApp.windows.first(where: { $0 is MainFlutterWindow }) {
      let targetSize = NSSize(width: 620, height: 460)
      var frame = w.frame
      if frame.size != targetSize {
        frame.size = targetSize
        w.setFrame(frame, display: true)
      }
      w.makeKeyAndOrderFront(nil)
      return
    }

    NSApp.windows.first?.makeKeyAndOrderFront(nil)
  }
}

private func fourCharCode(_ string: String) -> OSType {
  var result: UInt32 = 0
  for byte in string.utf8.prefix(4) {
    result = (result << 8) + UInt32(byte)
  }
  return OSType(result)
}
