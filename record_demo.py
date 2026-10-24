"""Records the JALYN product demo from a running server (Playwright) and adds sound (ffmpeg).

Env: JALYN_BASE (default http://127.0.0.1:8011), JALYN_VIDEO_OUT (default ./video), JALYN_AUDIO (dir with
music.wav / click.wav / key0..2.wav made by make_audio.py).
"""
import os, pathlib, random, subprocess, time
import numpy as np
from scipy.io import wavfile
from playwright.sync_api import sync_playwright

BASE = os.getenv("JALYN_BASE", "http://127.0.0.1:8011")
OUT = pathlib.Path(os.getenv("JALYN_VIDEO_OUT", "video")); OUT.mkdir(exist_ok=True, parents=True)
AUDIO = pathlib.Path(os.getenv("JALYN_AUDIO", "audio"))
random.seed(3)

OVERLAY_JS = """
(() => {
  const cur = document.createElement('div'); cur.id='__cur';
  Object.assign(cur.style, {position:'fixed', left:'640px', top:'360px', width:'14px', height:'14px', borderRadius:'50%',
    border:'1.5px solid rgba(0,0,0,0.6)', background:'rgba(255,255,255,0.95)', zIndex: 99999,
    pointerEvents:'none', transform:'translate(-50%,-50%)', transition:'left .4s cubic-bezier(.2,.7,.2,1), top .4s cubic-bezier(.2,.7,.2,1)'});
  document.body.appendChild(cur);
  const cap = document.createElement('div'); cap.id='__cap';
  Object.assign(cap.style, {position:'fixed', left:'20px', bottom:'20px', maxWidth:'560px', padding:'9px 13px', borderRadius:'10px',
    background:'rgba(10,14,21,0.72)', backdropFilter:'blur(10px)', color:'rgba(255,255,255,0.92)', fontSize:'14px', fontWeight:'400',
    fontFamily:'Geist, -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", Arial, sans-serif', letterSpacing:'0.01em',
    zIndex: 99998, pointerEvents:'none', opacity:'0', transition:'opacity .25s ease', lineHeight:'1.35', border:'1px solid rgba(255,255,255,0.08)'});
  document.body.appendChild(cap);
  window.__cur = (x,y)=>{cur.style.left=x+'px'; cur.style.top=y+'px';};
  window.__click = ()=>{cur.animate([{transform:'translate(-50%,-50%) scale(1)'},{transform:'translate(-50%,-50%) scale(.7)'},{transform:'translate(-50%,-50%) scale(1)'}],{duration:180});};
  window.__cap = (t)=>{ if(!t){cap.style.opacity='0';return;} cap.textContent=t; cap.style.opacity='1'; };
})();
"""

events = []  # (t_seconds, kind)
T0 = None
def now(): return time.perf_counter() - T0

def ensure_overlay(page):
    if not page.evaluate("() => !!window.__cur"):
        page.evaluate(OVERLAY_JS)

def caption(page, text, hold=0):
    ensure_overlay(page); page.evaluate("t => window.__cap(t)", text)
    if hold: page.wait_for_timeout(hold)

def move_to(page, x, y, steps=22, dur=750):
    ensure_overlay(page)
    cx, cy = page.evaluate("() => { const c=document.getElementById('__cur'); return [parseFloat(c.style.left), parseFloat(c.style.top)]; }")
    for i in range(1, steps + 1):
        t = i / steps; e = t * t * (3 - 2 * t)
        page.evaluate("([x,y]) => window.__cur(x,y)", [cx + (x - cx) * e, cy + (y - cy) * e])
        page.mouse.move(cx + (x - cx) * e, cy + (y - cy) * e)
        page.wait_for_timeout(dur // steps)

def click(page, selector, pause=900):
    el = page.locator(selector).first; el.scroll_into_view_if_needed(); page.wait_for_timeout(200)
    bb = el.bounding_box(); x, y = bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2
    move_to(page, x, y); page.wait_for_timeout(120)
    events.append((now(), "click")); page.evaluate("() => window.__click()")
    el.click(); page.wait_for_timeout(pause)

def type_into(page, selector, text):
    click(page, selector, pause=350)
    for ch in text:
        events.append((now(), "key")); page.keyboard.type(ch)
        page.wait_for_timeout(random.randint(55, 120))

with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=str(OUT / "raw"),
                              record_video_size={"width": 1280, "height": 720}, locale="en-US")
    page = ctx.new_page(); T0 = time.perf_counter()
    page.goto(BASE + "/", wait_until="networkidle"); page.wait_for_timeout(900)
    ensure_overlay(page)
    caption(page, "Flares detected from NASA FIRMS satellite data · 60 nights · Kazakhstan", 2800)
    move_to(page, 430, 470, dur=1100); page.wait_for_timeout(500)
    caption(page, "Each dot is a flare seen on 35%+ of nights. Size shows radiated power.", 2600)
    click(page, "text=Flare Atyrau 01", pause=1500)
    caption(page, "Site card: gas volume, methanol equivalent, tenge and CO₂ per year", 3200)
    click(page, "#techBtn", pause=1300)
    caption(page, "Technology matching with payback", 1200)
    page.locator("#techList").first.evaluate("el => el.scrollIntoView({behavior: 'smooth', block: 'start'})"); page.wait_for_timeout(2300)
    page.locator(".panel").first.evaluate("el => el.scrollBy({top: 260, behavior: 'smooth'})"); page.wait_for_timeout(1900)
    page.locator("#subBtn").first.evaluate("el => el.scrollIntoView({behavior: 'smooth', block: 'center'})"); page.wait_for_timeout(900)
    click(page, "#subBtn", pause=800)
    caption(page, "Monitoring subscription · ₸250,000 per site per month", 300)
    type_into(page, "#subForm input[name=company]", "Demo Oil LLP")
    type_into(page, "#subForm input[name=email]", "ops@demo-oil.kz")
    click(page, "#subForm button[type=submit]", pause=700)
    caption(page, "Saved to the server database", 2600)
    caption(page, "", 0)
    page.goto(BASE + "/api/sites/D-04/report", wait_until="networkidle"); page.wait_for_timeout(500)
    ensure_overlay(page); caption(page, "Utilization program report, generated per site", 1800)
    page.evaluate("() => window.scrollTo({top: 520, behavior: 'smooth'})"); page.wait_for_timeout(1900)
    page.evaluate("() => window.scrollTo({top: 1000, behavior: 'smooth'})"); page.wait_for_timeout(1700)
    caption(page, "", 0)
    page.goto(BASE + "/", wait_until="networkidle"); page.wait_for_timeout(700)
    ensure_overlay(page); click(page, "#methodBtn", pause=700)
    caption(page, "Method and assumptions — every coefficient is open", 2800)
    page.locator(".modal-card").first.evaluate("el => el.scrollTo({top: 420, behavior: 'smooth'})"); page.wait_for_timeout(1500)
    caption(page, "", 0)
    page.goto("about:blank"); page.wait_for_timeout(100)
    page.set_content('<body style="margin:0;background:#0b0f17;display:flex;align-items:center;justify-content:center;height:100vh;color:#f3f6fb;font-family:Geist,-apple-system,BlinkMacSystemFont,Helvetica,Arial,sans-serif"><div style="text-align:center"><div style="font-size:34px;letter-spacing:.18em;font-weight:500">JALYN</div><div style="font-size:14px;opacity:.65;margin-top:10px">AuaHack 2026 · flares from space, priced in tenge</div></div></body>')
    page.wait_for_timeout(2600)
    T_END = now()
    video_path = page.video.path()
    ctx.close(); browser.close()

# ---------------- audio ----------------
def dur_of(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip())

webm = pathlib.Path(video_path)
D = dur_of(webm)
scale = D / T_END if T_END > 0 else 1.0
SR = 44100
def load(name):
    sr, x = wavfile.read(AUDIO / name); x = x.astype(np.float32) / 32767
    return x if x.ndim == 1 else x.mean(axis=1)
music = load("music.wav"); click_s = load("click.wav"); keys = [load(f"key{i}.wav") for i in range(3)]
n = int(D * SR) + SR
mix = np.zeros(n, dtype=np.float32)
m = music[:n]; mix[: len(m)] += m * 0.55
fade = int(2.5 * SR)
if len(m) > fade: mix[len(m) - fade: len(m)] *= np.linspace(1, 0, fade)
for t, kind in events:
    s = click_s if kind == "click" else random.choice(keys)
    pos = int(t * scale * SR)
    seg = s * (0.9 if kind == "click" else 0.5)
    end = min(n, pos + len(seg)); mix[pos:end] += seg[: end - pos]
mix = np.clip(mix, -1, 1)
wav_path = OUT / "audio_mix.wav"
wavfile.write(wav_path, SR, (mix * 32767).astype(np.int16))

mp4 = OUT / "JALYN-demo.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-i", str(wav_path), "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p", "-r", "30",
                "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(mp4)], check=True)
print("video:", mp4, "duration s:", round(dur_of(mp4), 1), "size KB:", mp4.stat().st_size // 1024, "events:", len(events))
