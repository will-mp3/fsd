"""Keyboard and mouse input helpers for macOS."""


def utf16_length(text: str) -> int:
  return len(text.encode("utf-16-le")) // 2
