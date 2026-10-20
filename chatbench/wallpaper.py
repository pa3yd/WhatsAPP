"""Original, self-contained line-art wallpaper for simulated chat exports.

The reference is the density and low contrast of a desktop chat wallpaper, not
WhatsApp's proprietary illustration. A fixed seed keeps previews and exports
pixel-for-pixel stable across reruns.
"""

import base64
import random


_MOTIFS = """
<g id="flower"><circle cx="25" cy="25" r="4"/><path d="M25 20C8 2 18-6 25 17c7-23 17-15 0 3M30 25c18-15 25-4 5 0 20 4 13 15-5 0M25 30c8 22-6 25-5 5-12 18-20 5 0-5M20 25C0 38-2 21 15 24 1 10 14 4 20 20"/></g>
<g id="planet"><circle cx="25" cy="25" r="17"/><path d="M10 17c4 12 16 20 29 18M16 13c9 10 17 16 25 16M3 31c-5-7 11-14 27-14 18 0 24 9 8 17-16 8-36 8-35-3Z"/></g>
<g id="camera"><rect x="5" y="13" width="40" height="28" rx="5"/><circle cx="25" cy="27" r="9"/><path d="M12 13l3-6h12l3 6M36 19h3"/></g>
<g id="cup"><path d="M7 15h31v20q-2 8-15 8-14 0-16-8ZM38 19h5q8 1 4 10-2 4-9 4M14 8q-4-4 0-7m9 8q-4-5 0-8m10 7q-4-4 0-7"/></g>
<g id="leaf"><path d="M25 45q-8-17-2-33M24 35C4 33 2 17 6 8q19 0 19 27ZM23 29Q23 9 41 4q7 19-18 25ZM8 11q9 7 16 24M39 8q-11 10-16 21"/></g>
<g id="gift"><rect x="7" y="18" width="36" height="26" rx="2"/><path d="M5 18h40v-8H5Zm20 0v26M25 10Q7 11 11 3c4-7 13 4 14 7Zm0 0Q42 11 39 3c-3-7-13 4-14 7Z"/></g>
<g id="smile"><circle cx="25" cy="25" r="20"/><path d="M17 21h1m14 0h1M15 30q10 12 21 0"/></g>
<g id="heart"><path d="M25 43 6 25C-5 12 10 2 22 14l3 4 3-4C40 2 55 12 44 25Z"/><path d="M13 23q2-5 7-5"/></g>
<g id="icecream"><path d="M9 24h32L25 47ZM12 24q-5-12 5-14 2-9 11-7 7 0 8 8 9 4 5 13Z"/><path d="M18 30l13 13m3-14L20 43"/></g>
<g id="music"><path d="M20 8v30M20 8l23-5v31M20 18l23-5"/><ellipse cx="13" cy="39" rx="7" ry="5"/><ellipse cx="36" cy="35" rx="7" ry="5"/></g>
<g id="paper"><path d="M2 24 47 5 32 46l-9-14-10 8 1-15Z"/><path d="M14 25 47 5M23 32l9 14"/></g>
<g id="balloon"><path d="M25 5c-13 0-19 12-17 23 2 9 8 13 17 14 9-1 15-5 17-14 2-11-4-23-17-23ZM21 42h8l-4 5-4-5ZM25 47v4M12 20h26M16 11q-4 11-1 25m19-25q4 11 1 25"/></g>
<g id="chat"><path d="M5 8h40v29H18L8 45l2-8H5Z"/><path d="M14 18h22m-22 7h17"/></g>
<g id="pencil"><path d="m8 37 27-29 8 8-28 29-11 2Zm26-27 7-7 8 8-7 7M8 37l7 8"/></g>
<g id="fish"><path d="M7 25q15-20 32 0Q22 45 7 25ZM39 25l10-12v24ZM14 23h1M22 13q4 12 0 24"/></g>
<g id="sun"><circle cx="25" cy="25" r="11"/><path d="M25 1v9m0 30v9M1 25h9m30 0h9M8 8l7 7m20 20 7 7M42 8l-7 7M15 35l-7 7"/></g>
<g id="house"><path d="M3 23 25 4l22 19M8 20v26h34V20M20 46V31h10v15M14 25h4m14 0h4"/></g>
<g id="bottle"><path d="M18 3h14v8l5 8v25q-12 6-24 0V19l5-8ZM18 11h14M14 24h22M20 33h10"/></g>
<g id="star"><path d="m25 2 5 16 17 1-14 10 5 17-13-10-13 10 5-17L3 19l17-1Z"/><circle cx="25" cy="26" r="4"/></g>
<g id="cookie"><circle cx="25" cy="25" r="20"/><path d="M9 18q8-2 9-11m-2 26h2m12-16h2m-7 10h2m7 8h2m-17-16h2"/><circle cx="16" cy="33" r="2"/><circle cx="32" cy="17" r="2"/></g>
<g id="umbrella"><path d="M3 26q3-20 22-20t22 20q-5-6-11 0-5-6-11 0-6-6-11 0-5-6-11 0ZM25 6v34q0 8 7 6 4-1 4-5"/></g>
<g id="cloud"><path d="M9 37q-10 0-8-10 1-8 10-8 1-13 13-13 10 0 13 10 11-1 12 9 1 12-11 12Z"/><path d="M14 30h23"/></g>
<g id="cactus"><path d="M18 47V15q0-8 7-8t7 8v32ZM18 30Q6 31 6 17q0-7 5-7t5 7v7m16 4q12 2 12-11 0-7-5-7t-5 7v7M12 47h26"/></g>
<g id="butterfly"><path d="M25 14Q4-4 3 16q0 11 16 11Q2 29 8 44q8 10 17-11 9 21 17 11 6-15-11-17 16 0 16-11Q46-4 25 14ZM25 13v23m-3-24-5-9m11 9 5-9"/></g>
<g id="phone"><rect x="13" y="3" width="24" height="44" rx="5"/><path d="M17 10h16M17 38h16"/><circle cx="25" cy="43" r="1"/></g>
<g id="boat"><path d="M3 29h44l-9 14H12ZM25 28V4M25 7 8 25h17ZM27 8l15 17H27ZM4 47q7-4 14 0 7-4 14 0 7-4 14 0"/></g>
<g id="pizza"><path d="M5 7Q25-1 45 7L25 47ZM5 7q20 12 40 0"/><circle cx="20" cy="20" r="3"/><circle cx="32" cy="20" r="3"/><circle cx="25" cy="32" r="3"/></g>
<g id="football"><circle cx="25" cy="25" r="21"/><path d="m25 14 10 7-4 12H19l-4-12ZM25 14l-2-10m12 17 10-3M31 33l7 9m-19-9-7 9m3-21L5 18"/></g>
"""


def _wallpaper_svg() -> str:
    rng = random.Random(20261020)
    names = ("flower", "planet", "camera", "cup", "leaf", "gift", "smile", "heart",
             "icecream", "music", "paper", "balloon", "chat", "pencil", "fish",
             "sun", "house", "bottle", "star", "cookie", "umbrella", "cloud",
             "cactus", "butterfly", "phone", "boat", "pizza", "football")
    doodles = []
    positions = []
    attempts = 0
    while len(positions) < 128 and attempts < 20000:
        attempts += 1
        x, y = rng.randrange(-15, 555), rng.randrange(-15, 555)
        if all((x - px) ** 2 + (y - py) ** 2 >= 34 ** 2 for px, py in positions):
            positions.append((x, y))
    for index, (x, y) in enumerate(positions):
        name = names[(index * 7 + rng.randrange(len(names))) % len(names)]
        angle = rng.randrange(-42, 43)
        scale = rng.choice((0.54, 0.64, 0.74, 0.85, 0.97, 1.12))
        doodles.append(f'<use href="#{name}" transform="translate({x} {y}) rotate({angle} 25 25) scale({scale})"/>')
    accents = []
    for _ in range(92):
        x, y = rng.randrange(560), rng.randrange(560)
        radius = rng.choice((1.5, 2.5, 3.5))
        accents.append(f'<circle cx="{x}" cy="{y}" r="{radius}"/>')
    return ("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"560\" height=\"560\" viewBox=\"0 0 560 560\">"
            f'<defs><g fill="none" stroke="#d4c8ba" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">{_MOTIFS}</g></defs>'
            f'<g fill="none" stroke="#d4c8ba" stroke-width="1.2" opacity=".39">{"".join(doodles)}{"".join(accents)}</g></svg>')


WALLPAPER_DATA_URI = "data:image/svg+xml;base64," + base64.b64encode(_wallpaper_svg().encode("utf-8")).decode("ascii")
