"""숏폼 합성: 힉스필드 5초 클립(상품 사진 기반) + 무료 텍스트 카드 → 720x1280 30fps mp4.
spec.json 하나로 1편을 만든다. 가격·이유는 v_picks 실측값만 쓰고, 후기·효능은 지어내지 않는다."""
import json, subprocess, sys, os
from PIL import Image, ImageDraw, ImageFont
W, H = 720, 1280
F = "NotoSansKR.otf"
FB = "NotoSansKR-Bold.otf"
def font(sz, bold=False): return ImageFont.truetype(FB if bold else F, sz)
ENC = ["-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", "30"]

def wrap(d, text, f, maxw):  # 띄어쓰기 단위로 줄바꿈(숫자·단어가 쪼개지지 않게)
    lines, cur = [], ""
    for w in text.split(" "):
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) > maxw and cur:
            lines.append(cur); cur = w
        else: cur = t
    if cur: lines.append(cur)
    return lines

def center(d, y, text, f, fill):
    w = d.textlength(text, font=f); d.text(((W - w) / 2, y), text, font=f, fill=fill); return y + f.size * 1.25

def card_hook(s, prod, out):
    im = Image.new("RGB", (W, H), s["bg"]); d = ImageDraw.Draw(im)
    y = center(d, 120, s["series"], font(40, True), s["accent"])
    y = center(d, y + 10, f"#{s['rank']}", font(150), "#111")
    p = prod.copy(); p.thumbnail((520, 520)); im.paste(p, ((W - p.width) // 2, 470))
    d.rounded_rectangle((180, 1030, 540, 1150), 60, fill=s["accent"])
    center(d, 1045, f"{s['discount']}% 할인", font(64), "white")
    im.save(out)

def band(s, out):  # 클립(상단) 아래 고정 패널. 클립은 원본 비율 그대로 위쪽에 놓는다
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, 90), fill=s["bg"])
    center(d, 22, s["series"] + f"  #{s['rank']}", font(36, True), s["accent"])
    top = 90 + s["clip_h"]
    d.rectangle((0, top, W, H), fill="#111111")
    f = font(44); lines = wrap(d, s["name"], f, 650)[:3]
    y = top + 40
    for ln in lines: y = center(d, y, ln, f, "white")
    for r in s["reasons"][:3]:
        y = center(d, y + 8, "✓ " + r, font(34, True), s["accent2"])
    im.save(out)

def card_price(s, out):
    im = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(im)
    y = center(d, 300, s["mall"], font(44, True), "#666")
    if s.get("original"):
        t = f"{s['original']:,}원"; fo = font(56, True); w = d.textlength(t, font=fo); x = (W - w) / 2
        d.text((x, y + 30), t, font=fo, fill="#999"); d.line((x - 6, y + 70, x + w + 6, y + 70), fill="#999", width=5); y += 120
    y = center(d, y + 20, f"{s['price']:,}원", font(120), "#111")
    d.rounded_rectangle((210, y + 30, 510, y + 130), 50, fill=s["accent"])
    center(d, y + 42, f"-{s['discount']}%", font(60), "white")
    if s.get("deadline"): center(d, y + 190, s["deadline"], font(44, True), "#e11d48")
    center(d, 1120, "가격은 수집 시점 기준 · 구매 전 판매처 확인", font(26, True), "#888")
    im.save(out)

def card_cta(s, out):
    im = Image.new("RGB", (W, H), s["accent"]); d = ImageDraw.Draw(im)
    y = center(d, 470, "더 많은 특가는", font(52, True), "white")
    y = center(d, y + 10, s["site"], font(84), "white")
    center(d, y + 20, s["domain"], font(36, True), "white")
    center(d, 1150, "AI로 만든 영상입니다", font(26, True), "white")
    im.save(out)

def still(png, dur, out, fade_in=False):
    vf = f"format=yuv420p,loop=-1:1,trim=duration={dur},setpts=N/30/TB" + (",fade=t=in:st=0:d=0.3" if fade_in else "")
    run(["-framerate", "30", "-i", png, "-vf", vf, *ENC, out])

def run(args):
    tmp = args[-1][:-4] + ".tmp.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args[:-1], tmp], check=True); os.replace(tmp, args[-1])

def main(spec_path):
    s = json.load(open(spec_path)); n = s["slug"]; os.makedirs(n, exist_ok=True)
    prod = Image.open(s["image"]).convert("RGB")
    card_hook(s, prod, f"{n}/1.png"); band(s, f"{n}/band.png"); card_price(s, f"{n}/3.png"); card_cta(s, f"{n}/4.png")
    still(f"{n}/1.png", 2.5, f"{n}/s1.mp4")
    run(["-i", s["clip"], "-i", f"{n}/band.png", "-filter_complex",
         f"color=c={s['bg']}:s={W}x{H}:r=30:d=5[bg];[0:v]scale={W}:{s['clip_h']},fps=30[c];[bg][c]overlay=0:90:shortest=1[v];[v][1:v]overlay=0:0,trim=duration=5,setpts=PTS-STARTPTS,format=yuv420p",
         "-an", *ENC, f"{n}/s2.mp4"])
    still(f"{n}/3.png", 3, f"{n}/s3.mp4", True)
    still(f"{n}/4.png", 2, f"{n}/s4.mp4", True)
    open(f"{n}/list.txt", "w").write("".join(f"file 's{i}.mp4'\n" for i in range(1, 5)))
    run(["-f", "concat", "-safe", "0", "-i", f"{n}/list.txt", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-c:v", "copy", "-c:a", "aac", "-shortest", f"{n}.mp4"])
    print(n + ".mp4")

if __name__ == "__main__": main(sys.argv[1])
