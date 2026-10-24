"""Check the running server can see an image and point in Qwen3-VL's 0-1000 format.

Draws a red SAVE button at a known spot, asks the model where it is, and
checks the returned [POINT:x,y] lands on it. Run through test_vision.sh,
which supplies PORT, MODEL and API_KEY.
"""

import base64
import io
import json
import os
import re
import sys
import time
import urllib.request

from PIL import Image, ImageDraw

W, H = 1280, 800
BOX = (860, 560, 1060, 640)  # button centre (960, 600) px = (750, 750) on 0-1000

img = Image.new("RGB", (W, H), "white")
draw = ImageDraw.Draw(img)
draw.rectangle(BOX, fill="red")
draw.text((935, 592), "SAVE", fill="white")
png = io.BytesIO()
img.save(png, "PNG")

body = {
    "model": os.environ["MODEL"],
    "max_tokens": 50,
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64," + base64.b64encode(png.getvalue()).decode()
                    },
                },
                {
                    "type": "text",
                    "text": "Where is the SAVE button? Reply only with [POINT:x,y:save] using "
                    "relative coordinates on a 0 to 1000 scale, where (0,0) is top-left "
                    "and (1000,1000) is bottom-right.",
                },
            ],
        }
    ],
}
request = urllib.request.Request(
    f"http://127.0.0.1:{os.environ['PORT']}/v1/chat/completions",
    data=json.dumps(body).encode(),
    headers={
        "content-type": "application/json",
        "authorization": "Bearer " + os.environ["API_KEY"],
    },
)

start = time.time()
with urllib.request.urlopen(request, timeout=120) as response:
    reply = json.load(response)["choices"][0]["message"]["content"]
print(f"reply ({time.time() - start:.1f}s): {reply!r}")
print("expected about [POINT:750,750:save]")

match = re.search(r"\[POINT:(\d+),(\d+)", reply)
if not match:
    sys.exit("FAIL: no POINT tag in the reply")
x = int(match[1]) * W / 1000
y = int(match[2]) * H / 1000
ok = BOX[0] <= x <= BOX[2] and BOX[1] <= y <= BOX[3]
print(("PASS" if ok else "FAIL") + f": lands at pixel ({x:.0f}, {y:.0f})")
sys.exit(0 if ok else 1)
