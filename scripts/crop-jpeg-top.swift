#!/usr/bin/env swift
import Foundation
import ImageIO
import CoreGraphics
import UniformTypeIdentifiers

/// Crop raster in place: remove `dropTop` pixels from the top; width unchanged.
/// CGImage crop rect uses pixel space, origin top-left, y increasing downward.
guard CommandLine.argc == 3,
      let dropTop = Int(CommandLine.arguments[2]), dropTop >= 0
else {
    fputs("usage: crop-jpeg-top.swift <path.jpg> <pixels-to-remove-from-top>\n", stderr)
    exit(1)
}
let path = CommandLine.arguments[1]
let url = URL(fileURLWithPath: path) as CFURL

guard let src = CGImageSourceCreateWithURL(url, nil),
      let cg = CGImageSourceCreateImageAtIndex(src, 0, nil)
else {
    fputs("failed to read image\n", stderr)
    exit(1)
}

let w = cg.width
let h = cg.height
guard dropTop < h else {
    fputs("dropTop >= image height\n", stderr)
    exit(1)
}
let newH = h - dropTop
let rect = CGRect(x: 0, y: CGFloat(dropTop), width: CGFloat(w), height: CGFloat(newH))

guard let cropped = cg.cropping(to: rect) else {
    fputs("crop failed\n", stderr)
    exit(1)
}

guard let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.jpeg.identifier as CFString, 1, nil)
else {
    fputs("failed to open destination\n", stderr)
    exit(1)
}

let props = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [CFString: Any]
CGImageDestinationAddImage(dest, cropped, props as CFDictionary?)
guard CGImageDestinationFinalize(dest) else {
    fputs("write failed\n", stderr)
    exit(1)
}

print("cropped \(w)x\(h) -> \(w)x\(newH) (removed top \(dropTop)px)")
