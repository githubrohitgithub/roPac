import Cocoa
import FlutterMacOS

class MainFlutterWindow: NSWindow {
  override func awakeFromNib() {
    let flutterViewController = FlutterViewController()
    let windowFrame = self.frame
    self.contentViewController = flutterViewController

    let minW: CGFloat = 600
    let minH: CGFloat = 420
    self.minSize = NSSize(width: minW, height: minH)

    var frame = windowFrame
    if frame.width < minW { frame.size.width = minW }
    if frame.height < minH { frame.size.height = minH }
    self.setFrame(frame, display: true)

    RegisterGeneratedPlugins(registry: flutterViewController)
    RopacAudio.shared.register(messenger: flutterViewController.engine.binaryMessenger)

    super.awakeFromNib()
  }
}
