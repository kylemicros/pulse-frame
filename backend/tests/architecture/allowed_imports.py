PACKAGES = ("signal", "vision", "platform", "monitor", "stream", "tools")

ALLOWED_IMPORTS = {
    "signal": (),
    "vision": (),
    "platform": (),
    "monitor": ("signal", "vision"),
    "stream": ("signal", "vision", "platform", "monitor"),
    "tools": ("signal", "vision", "platform", "monitor"),
}

THIRD_PARTY_HOMES = {
    "fastapi": ("stream",),
    "starlette": ("stream",),
    "uvicorn": ("stream",),
    "mediapipe": ("vision",),
}
