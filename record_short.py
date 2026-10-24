"""20-second product film: title card → the product, three smooth actions → end card. Sound mixed in."""
import os, pathlib, random, subprocess, time
import numpy as np
from scipy.io import wavfile
from playwright.sync_api import sync_playwright

BASE = os.getenv("JALYN_BASE", "http://127.0.0.1:8012")
OUT = pathlib.Path(os.getenv("JALYN_VIDEO_OUT", "video")); OUT.mkdir(exist_ok=True, parents=True)
AUDIO = pathlib.Path(os.getenv("JALYN_AUDIO", "audio"))
random.seed(5)

FONT = "Geist, -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Helvetica Neue', Helvetica, Arial, sans-serif"
CARD_CSS = f"margin:0;background:#000;height:100vh;display:flex;align-items:center;justify-content:center;color:#f5f5f7;font-family:{FONT};"

OVERLAY_JS = """
(() => {
  const cur = document.createElement('div'); cur.id='__cur';
  Object.assign(cur.style, {position:'fixed', left:'640px', top:'400px', width:'14px', height:'14px', borderRadius:'50%',
    border:'1.5px solid rgba(0,0,0,0.6)', background:'rgba(255,255,255,0.95)', zIndex: 99999,
    pointerEvents:'none', transform:'translate(-50%,-50%)', transition:'left .5s cubic-bezier(.2,.7,.2,1), top .5s cubic-bezier(.2,.7,.2,1)'});
  document.body.appendChild(cur);
  const cap = document.createElement('div'); cap.id='__cap';
  Object.assign(cap.style, {position:'fixed', left:'20px', bottom:'20px', padding:'8px 12px', borderRadius:'9px',
    background:'rgba(10,14,21,0.7)', backdropFilter:'blur(10px)', color:'rgba(255,255,255,0.9)', fontSize:'13px',
    fontFamily:"__FONT__", zIndex: 99998, pointerEvents:'none', opacity:'0', transition:'opacity .35s ease', border:'1px solid rgba(255,255,255,0.08)'});
  document.body.appendChild(cap);
  window.__cur = (x,y)=>{cur.style.left=x+'px'; cur.style.top=y+'px';};
  window.__click = ()=>{cur.animate([{transform:'translate(-50%,-50%) scale(1)'},{transform:'translate(-50%,-50%) scale(.7)'},{transform:'translate(-50%,-50%) scale(1)'}],{duration:180});};
  window.__cap = (t)=>{ if(!t){cap.style.opacity='0';return;} cap.textContent=t; cap.style.opacity='1'; };
})();
""".replace("__FONT__", FONT)

events = []
T0 = None
def now(): return time.perf_counter() - T0
def ensure(page):
    if not page.evaluate("() => !!window.__cur"): page.evaluate(OVERLAY_JS)
def caption(page, text, hold=0):
    ensure(page); page.evaluate("t => window.__cap(t)", text)
    if hold: page.wait_for_timeout(hold)
def move_to(page, x, y, steps=22, dur=700):
    ensure(page)
    cx, cy = page.evaluate("() => { const c=document.getElementById('__cur'); return [parseFloat(c.style.left), parseFloat(c.style.top)]; }")
    for i in range(1, steps + 1):
        t = i / steps; e = t * t * (3 - 2 * t)
        page.evaluate("([x,y]) => window.__cur(x,y)", [cx + (x - cx) * e, cy + (y - cy) * e])
        page.mouse.move(cx + (x - cx) * e, cy + (y - cy) * e)
        page.wait_for_timeout(dur // steps)
def click(page, selector, pause=800):
    el = page.locator(selector).first; el.scroll_into_view_if_needed(); page.wait_for_timeout(150)
    bb = el.bounding_box(); x, y = bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2
    move_to(page, x, y); page.wait_for_timeout(120)
    events.append((now(), "click")); page.evaluate("() => window.__click()")
    el.click(); page.wait_for_timeout(pause)

def card(page, html, hold):
    page.goto("about:blank"); page.set_content(f'<body style="{CARD_CSS}">{html}</body>')
    page.wait_for_timeout(hold)

with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=str(OUT / "raw_short"),
                              record_video_size={"width": 1280, "height": 720}, locale="en-US")
    page = ctx.new_page(); T0 = time.perf_counter()
    # pre-load the font on the first card so the title card uses Geist
    page.goto(BASE + "/", wait_until="networkidle")
    card(page, '<div style="max-width:860px;padding:0 40px;text-align:center"><div style="font-size:40px;font-weight:600;letter-spacing:-0.02em;line-height:1.15">Last year the world burned 167&nbsp;billion&nbsp;m³ of gas for nothing.</div><div style="margin-top:18px;font-size:17px;color:#86868b">We can see every flame from space — and put a price on it.</div></div>', 2800)
    page.goto(BASE + "/", wait_until="networkidle"); page.wait_for_timeout(500)
    ensure(page)
    caption(page, "Flares seen from space · 60 nights · Kazakhstan", 1400)
    click(page, "text=Flare Atyrau 01", pause=1100)
    caption(page, "One site: gas, methanol, tenge, CO₂ per year", 1200)
    click(page, "#techBtn", pause=700)
    caption(page, "Technology matching with payback", 300)
    page.locator("#techList").first.evaluate("el => el.scrollIntoView({behavior: 'smooth', block: 'start'})"); page.wait_for_timeout(1800)
    caption(page, "", 0); page.wait_for_timeout(250)
    card(page, '<div style="text-align:center"><div style="font-size:30px;letter-spacing:.2em;font-weight:500">JALYN</div><div style="margin-top:12px;font-size:15px;color:#86868b">flares from space, priced in tenge · AuaHack 2026</div></div>', 2200)
    T_END = now()
    video_path = page.video.path()
    ctx.close(); browser.close()

def dur_of(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip())

webm = pathlib.Path(video_path); D = dur_of(webm); scale = D / T_END if T_END > 0 else 1.0
SR = 44100
def load(name):
    sr, x = wavfile.read(AUDIO / name); x = x.astype(np.float32) / 32767
    return x if x.ndim == 1 else x.mean(axis=1)
music = load("music.wav"); click_s = load("click.wav")
n = int(D * SR) + SR
mix = np.zeros(n, dtype=np.float32)
m = music[: min(len(music), n)].copy()
fi, fo = int(1.2 * SR), int(2.4 * SR)
m[:fi] *= np.linspace(0, 1, fi)
end = min(len(m), int(D * SR)); m[end - fo:end] *= np.linspace(1, 0, fo); m[end:] = 0
mix[: len(m)] += m * 0.55
for t, kind in events:
    pos = int(t * scale * SR); seg = click_s * 0.9
    e = min(n, pos + len(seg)); mix[pos:e] += seg[: e - pos]
mix = np.clip(mix, -1, 1)
wav_path = OUT / "audio_short.wav"; wavfile.write(wav_path, SR, (mix * 32767).astype(np.int16))
mp4 = OUT / "JALYN-20s.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-i", str(wav_path), "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
                "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(mp4)], check=True)
print("video:", mp4, "duration s:", round(dur_of(mp4), 1), "size KB:", mp4.stat().st_size // 1024, "clicks:", len(events))
