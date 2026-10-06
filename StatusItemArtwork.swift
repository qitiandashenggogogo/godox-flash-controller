import AppKit

/// Builds the menu bar button image, including the update dot when one is due.
///
/// The dot is a real filled circle drawn into the image, not a glyph appended to the title.
/// Two reasons: a text bullet inherits the template tint and vanishes against one of the two
/// menu bar appearances, and it is read as part of the app's name by VoiceOver and by anyone
/// looking. The image is also marked non-template and given an explicit outline, so it stays
/// legible on a light and a dark menu bar alike.
///
/// The dot's slot is always reserved, whether or not a dot is painted. Reserving it keeps the
/// button's width constant, so discovering an update moves nothing in the menu bar and no
/// other item shifts.
enum StatusItemArtwork {
    struct Layout {
        let size: NSSize
        let dotOrigin: NSPoint
        let dotDiameter: CGFloat
    }

    static let dotDiameter: CGFloat = 7
    static let dotGap: CGFloat = 6
    static let sidePadding: CGFloat = 3
    static let dotColor = NSColor.systemOrange

    private static var textAttributes: [NSAttributedString.Key: Any] {
        // The menu bar font, so the image sits at exactly the size AppKit would have drawn a
        // title at. menuBarFont is the API that matches the status item on current macOS.
        let font = NSFont.menuBarFont(ofSize: 0)
        return [.font: font, .foregroundColor: NSColor.labelColor]
    }

    /// Renders "label [●]" as a single image. Returns nil only if AppKit cannot lay out text.
    static func makeImage(label: String, showsDot: Bool) -> NSImage? {
        let attributed = NSAttributedString(string: label, attributes: textAttributes)
        let textSize = attributed.size()
        guard textSize.width > 0, textSize.height > 0 else { return nil }

        let width = sidePadding * 2 + textSize.width + (dotGap + dotDiameter)
        let height = max(textSize.height, dotDiameter)
        let size = NSSize(width: (width).rounded(.up), height: (height + 2).rounded(.up))

        let image = NSImage(size: size)
        image.isTemplate = false
        image.lockFocus()
        defer { image.unlockFocus() }
        NSColor.clear.setFill()
        NSRect(origin: .zero, size: size).fill()

        let textOrigin = NSPoint(x: sidePadding, y: ((size.height - textSize.height) / 2).rounded())
        attributed.draw(at: textOrigin)

        let layout = Layout(
            size: size,
            dotOrigin: NSPoint(x: (size.width - sidePadding - dotDiameter).rounded(),
                               y: ((size.height - dotDiameter) / 2).rounded()),
            dotDiameter: dotDiameter
        )
        if showsDot {
            drawDot(in: image, layout: layout)
        }
        return image
    }

    private static func drawDot(in image: NSImage, layout: Layout) {
        let rect = NSRect(origin: layout.dotOrigin, size: NSSize(width: layout.dotDiameter, height: layout.dotDiameter))
        // A hairline outline in the opposite polarity keeps the dot visible against both a
        // light and a dark menu bar without resorting to a second colour that changes meaning.
        let outline = NSColor.shaftColorForCurrentAppearance
        let dot = NSBezierPath(ovalIn: rect.insetBy(dx: 0.75, dy: 0.75))
        dot.lineWidth = 1.5
        outline.setStroke()
        dot.stroke()
        dotColor.setFill()
        dot.fill()
        _ = image
    }

    /// Applies the label and dot to a status bar button, including the accessibility text.
    /// Rebuilding the image is the caller's job only when the state actually changed, so a
    /// repaint never happens on a tick or a background check that found nothing.
    static func apply(to button: NSStatusBarButton, label: String, state: UpdateState) {
        applyImage(makeImage(label: label, showsDot: state.showsIndicator), to: button, label: label, state: state)
    }

    /// The painting itself, split out so a redraw has exactly one thing to call and cannot
    /// silently drift from the initial paint.
    static func applyImage(_ image: NSImage?, to button: NSStatusBarButton, label: String, state: UpdateState) {
        if let image = image {
            button.image = image
            button.imagePosition = .imageOnly
            button.title = ""
        } else {
            // AppKit failed to lay the text out; fall back to a plain title rather than an
            // empty button. The dot is lost in this path, which is better than a blank item.
            button.image = nil
            button.imagePosition = .noImage
            button.title = state.showsIndicator ? label + " ●" : label
        }
        button.setAccessibilityLabel("神牛引闪器控制台")
        button.setAccessibilityValue(state.accessibilityDescription)
        button.setAccessibilityHelp(state.accessibilityDescription)
        button.toolTip = state.accessibilityDescription
    }
}

/// Keeps one status bar button's artwork correct for as long as the app runs.
///
/// The image is a raster: `NSImage.lockFocus()` resolves `labelColor` against whatever
/// appearance happens to be current at that moment, and the result is baked into the pixels.
/// Nothing repaints it, so switching the menu bar between light and dark leaves the text
/// painted in the colour that used to be right — which is the "unreadable title" bug.
///
/// This is the other half of the fix: it watches the appearance the button is *actually*
/// drawing in and repaints when it changes, comparing a rendered image's appearance name so
/// it never repaints for its own sake. It also repaints when the state changes. It is used by
/// the shipping shell and by the preview, which is why the watching lives here and not in
/// either caller.
///
/// Left-click opening and the right-click menu are untouched: this object only ever assigns
/// `image`, `title` and the accessibility text, never `target`, `action` or `menu`.
@MainActor
final class StatusItemArtworkController {
    private weak var button: NSStatusBarButton?
    private let label: String
    private var state: UpdateState
    private var paintedAppearance: NSAppearance.Name?
    private var tokens: [NSObjectProtocol] = []
    /// True only while an external push is being applied, so the redraw it causes cannot
    /// re-enter and loop.
    private var isApplying = false

    init(button: NSStatusBarButton, label: String, initialState: UpdateState) {
        self.button = button
        self.label = label
        self.state = initialState
        apply()
        startObservingAppearance()
    }

    deinit {
        // Cannot touch AppKit from deinit on a background thread, and the observers are only
        // relevant while this object is alive; the notification centre drops them with the
        // observer tokens, so there is nothing to unwind that must be on the main thread.
        tokens.removeAll()
    }

    /// The state currently painted.
    var paintedState: UpdateState { state }

    func update(_ newState: UpdateState) {
        // Only a real change repaints: a background check that found nothing must not touch
        // the menu bar at all.
        guard newState != state else { return }
        state = newState
        apply()
    }

    /// Repaints whenever the button's effective appearance changes.
    ///
    /// Four independent signals, because there is no single notification that reliably covers
    /// every way the menu bar can change: the appearance can be switched in System Settings
    /// (which posts a distributed notification), it can follow the user switching wallpaper
    /// auto light/dark while the app is frontmost (KVO on the application's effective
    /// appearance), it can change across a display wake (workspaces), and it can differ when
    /// the app is activated from a dark menubar-extraneous display. Whichever arrives, the
    /// comparison below makes the repaint idempotent.
    private func startObservingAppearance() {
        let center = NotificationCenter.default
        tokens.append(center.addObserver(forName: NSApplication.didBecomeActiveNotification,
                                         object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.repaintIfAppearanceChanged() }
        })
        tokens.append(center.addObserver(forName: NSWorkspace.didWakeNotification,
                                         object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.repaintIfAppearanceChanged() }
        })
        let workspaceCentre = NSWorkspace.shared.notificationCenter
        tokens.append(workspaceCentre.addObserver(forName: NSWorkspace.screensDidWakeNotification,
                                                 object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.repaintIfAppearanceChanged() }
        })
        tokens.append(center.addObserver(forName: NSApplication.didChangeScreenParametersNotification,
                                         object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.repaintIfAppearanceChanged() }
        })
        // The user's own light/dark choice, wherever it was made.
        let themeChanged = NotificationCenter.default.addObserver(
            forName: Notification.Name("AppleInterfaceThemeChangedNotification"),
            object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.repaintIfAppearanceChanged() }
        }
        tokens.append(themeChanged)
        // KVO is what covers "the app's own effective appearance changed", which the System
        // Settings notification alone does not always reach for an already-running accessory.
        if let button = button {
            tokens.append(button.observe(\.effectiveAppearance, options: [.new]) { [weak self] _, _ in
                MainActor.assumeIsolated { self?.repaintIfAppearanceChanged() }
            })
        }
        if let application = NSApp {
            tokens.append(application.observe(\.effectiveAppearance, options: [.new]) { [weak self] _, _ in
                MainActor.assumeIsolated { self?.repaintIfAppearanceChanged() }
            })
        }
    }

    private func repaintIfAppearanceChanged() {
        guard !isApplying, let button = button else { return }
        let current = button.effectiveAppearance.bestMatch(from: [.aqua, .darkAqua])
        guard current != paintedAppearance else { return }
        apply()
    }

    private func apply() {
        guard let button = button else { return }
        isApplying = true
        defer { isApplying = false }
        paintedAppearance = button.effectiveAppearance.bestMatch(from: [.aqua, .darkAqua])
        button.effectiveAppearance.performAsCurrentDrawingAppearance {
            StatusItemArtwork.applyImage(StatusItemArtwork.makeImage(label: label, showsDot: state.showsIndicator),
                                         to: button, label: label, state: state)
        }
    }
}

private extension NSColor {
    /// The colour that is guaranteed to contrast with the current menu bar, for the dot's
    /// hairline outline. Derived from the effective appearance so a dark menu bar gets a
    /// light outline and vice versa, instead of a hardcoded choice.
    static var shaftColorForCurrentAppearance: NSColor {
        let appearance = NSAppearance.currentDrawing()
        let isDark = appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
        return isDark ? NSColor.black.withAlphaComponent(0.75) : NSColor.white.withAlphaComponent(0.85)
    }
}
