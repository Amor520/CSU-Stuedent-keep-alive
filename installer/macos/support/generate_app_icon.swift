import AppKit
import Foundation

func point(center: NSPoint, radius: CGFloat, angle: CGFloat) -> NSPoint {
    let radians = angle * .pi / 180
    return NSPoint(
        x: center.x + radius * cos(radians),
        y: center.y + radius * sin(radians)
    )
}

func strokeArc(center: NSPoint, radius: CGFloat, startAngle: CGFloat, endAngle: CGFloat, lineWidth: CGFloat, color: NSColor) {
    let path = NSBezierPath()
    path.lineWidth = lineWidth
    path.lineCapStyle = .round
    color.setStroke()
    path.appendArc(withCenter: center, radius: radius, startAngle: startAngle, endAngle: endAngle)
    path.stroke()
}

let outputPath = CommandLine.arguments.dropFirst().first ?? "AppIcon.png"
let size = NSSize(width: 1024, height: 1024)
let canvas = NSRect(origin: .zero, size: size)

let ink = NSColor(calibratedRed: 0.13, green: 0.17, blue: 0.25, alpha: 1)
let blueA = NSColor(calibratedRed: 0.98, green: 0.99, blue: 1.0, alpha: 1)
let blueB = NSColor(calibratedRed: 0.82, green: 0.89, blue: 1.0, alpha: 1)
let gold = NSColor(calibratedRed: 0.98, green: 0.89, blue: 0.77, alpha: 1)
let accent = NSColor(calibratedRed: 0.95, green: 0.65, blue: 0.25, alpha: 1)

let image = NSImage(size: size)
image.lockFocus()

NSColor.clear.setFill()
canvas.fill()

let outerRect = canvas.insetBy(dx: 68, dy: 68)
let outerPath = NSBezierPath(roundedRect: outerRect, xRadius: 228, yRadius: 228)
let shadow = NSShadow()
shadow.shadowColor = NSColor.black.withAlphaComponent(0.12)
shadow.shadowOffset = NSSize(width: 0, height: -18)
shadow.shadowBlurRadius = 40

NSGraphicsContext.saveGraphicsState()
shadow.set()
let bgGradient = NSGradient(colors: [blueA, blueB, gold])!
bgGradient.draw(in: outerPath, angle: -38)
NSGraphicsContext.restoreGraphicsState()

NSColor.white.withAlphaComponent(0.36).setFill()
NSBezierPath(ovalIn: NSRect(x: 180, y: 560, width: 470, height: 270)).fill()

let plateRect = outerRect.insetBy(dx: 134, dy: 134)
let platePath = NSBezierPath(roundedRect: plateRect, xRadius: 168, yRadius: 168)
NSColor.white.withAlphaComponent(0.9).setFill()
platePath.fill()

NSColor(calibratedRed: 0.72, green: 0.8, blue: 0.94, alpha: 0.3).setStroke()
platePath.lineWidth = 2
platePath.stroke()

let wifiCenter = NSPoint(x: canvas.midX - 44, y: canvas.midY + 34)
strokeArc(center: wifiCenter, radius: 82, startAngle: 40, endAngle: 140, lineWidth: 18, color: ink)
strokeArc(center: wifiCenter, radius: 128, startAngle: 48, endAngle: 132, lineWidth: 18, color: ink)
strokeArc(center: wifiCenter, radius: 174, startAngle: 56, endAngle: 124, lineWidth: 18, color: ink)

let dotPath = NSBezierPath(ovalIn: NSRect(x: wifiCenter.x - 20, y: wifiCenter.y - 20, width: 40, height: 40))
ink.setFill()
dotPath.fill()

let refreshCenter = NSPoint(x: canvas.midX + 170, y: canvas.midY - 120)
strokeArc(center: refreshCenter, radius: 88, startAngle: 215, endAngle: 18, lineWidth: 19, color: accent)

let arrowTip = point(center: refreshCenter, radius: 88, angle: 18)
let arrowLeft = point(center: arrowTip, radius: 26, angle: 162)
let arrowRight = point(center: arrowTip, radius: 26, angle: 264)
let arrowPath = NSBezierPath()
arrowPath.move(to: arrowTip)
arrowPath.line(to: arrowLeft)
arrowPath.line(to: arrowRight)
arrowPath.close()
accent.setFill()
arrowPath.fill()

let accentGlow = NSBezierPath(ovalIn: NSRect(x: refreshCenter.x - 62, y: refreshCenter.y - 62, width: 124, height: 124))
accent.withAlphaComponent(0.12).setFill()
accentGlow.fill()

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
