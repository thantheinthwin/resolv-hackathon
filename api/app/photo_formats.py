"""Image formats accepted for catalog storage and judge review."""

PHOTO_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}

EXTENSION_BY_MIME = {mime: extension for extension, mime in PHOTO_FORMATS.values()}
