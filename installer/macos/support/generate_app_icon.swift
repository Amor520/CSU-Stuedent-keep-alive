import AppKit
import Foundation

let outputPath = CommandLine.arguments.dropFirst().first ?? "AppIcon.png"
let scriptDirectory = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
let sourceURL = scriptDirectory.appendingPathComponent("assets/csu-app-icon-source.png")

guard let sourceImage = NSImage(contentsOf: sourceURL) else {
    fputs("Failed to load icon source at \(sourceURL.path)\n", stderr)
    exit(1)
}

let canvasSize = NSSize(width: 1024, height: 1024)
let image = NSImage(size: canvasSize)
image.lockFocus()

sourceImage.draw(
    in: NSRect(origin: .zero, size: canvasSize),
    from: .zero,
    operation: .copy,
    fraction: 1.0,
    respectFlipped: false,
    hints: [.interpolation: NSImageInterpolation.high]
)

image.unlockFocus()

guard
    let tiffData = image.tiffRepresentation,
    let bitmap = NSBitmapImageRep(data: tiffData),
    let pngData = bitmap.representation(using: .png, properties: [:])
else {
    fputs("Failed to encode PNG.\n", stderr)
    exit(1)
}

try pngData.write(to: URL(fileURLWithPath: outputPath))
