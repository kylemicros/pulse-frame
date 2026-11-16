PACKAGES = ("signal", "vision", "platform", "store", "monitor", "stream", "tools")

ALLOWED_IMPORTS = {
    "signal": (),
    "vision": (),
    "platform": (),
    "store": (),
    "monitor": ("signal", "vision"),
    "stream": ("signal", "vision", "platform", "monitor"),
    "tools": ("signal", "vision", "platform", "monitor", "store"),
}

THIRD_PARTY_HOMES = {
    "fastapi": ("stream",),
    "starlette": ("stream",),
    "uvicorn": ("stream",),
    "mediapipe": ("vision",),
    "psycopg": ("store",),
}
