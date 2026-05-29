import AppKit

/// Menu bar status item — kept alive for app lifetime.
final class MenuBarController: NSObject {
  static let shared = MenuBarController()

  private var statusItem: NSStatusItem?
  var onOpen: (() -> Void)?
  var onHide: (() -> Void)?
  var onQuit: (() -> Void)?

  private override init() {
    super.init()
  }

  func install() {
    if statusItem != nil {
      return
    }

    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    statusItem = item

    guard let button = item.button else {
      NSLog("RoPac: NSStatusItem.button is nil")
      return
    }

    button.title = "RoPac"
    button.toolTip = "RoPac — personal assistant"
    if let image = NSImage(systemSymbolName: "sparkle", accessibilityDescription: "RoPac") {
      image.isTemplate = true
      button.image = image
      button.imagePosition = .imageLeading
    }

    let menu = NSMenu()
    menu.addItem(makeItem("Open RoPac", action: #selector(openRoPac)))
    menu.addItem(makeItem("Hide", action: #selector(hideRoPac), key: "h"))
    menu.addItem(.separator())
    menu.addItem(makeItem("Quit RoPac", action: #selector(quitRoPac), key: "q"))
    item.menu = menu

    NSLog("RoPac: menu bar status item installed")
  }

  private func makeItem(
    _ title: String,
    action: Selector,
    key: String = ""
  ) -> NSMenuItem {
    let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
    item.target = self
    return item
  }

  @objc private func openRoPac() {
    onOpen?()
  }

  @objc private func hideRoPac() {
    onHide?()
  }

  @objc private func quitRoPac() {
    onQuit?()
  }
}
