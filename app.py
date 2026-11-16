import os, tempfile, shutil, glob, re
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
import yt_dlp, imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"]
)

# Optional cookie support if passed via env var or file
COOKIE_FILE = os.path.join(tempfile.gettempdir(), "youtube_cookies.txt")
if os.environ.get("YOUTUBE_COOKIES"):
    try:
        with open(COOKIE_FILE, "w") as f:
            f.write(os.environ["YOUTUBE_COOKIES"])
    except Exception:
        COOKIE_FILE = None
elif os.path.exists("cookies.txt"):
    COOKIE_FILE = "cookies.txt"
else:
    COOKIE_FILE = None

BASE = {
    "quiet": True,
    "noplaylist": True,
    "ffmpeg_location": FF,
    "extractor_args": {
        "youtube": {
            "player_client": ["android"]
        }
    }
}
if COOKIE_FILE:
    BASE["cookiefile"] = COOKIE_FILE

@app.get("/")
def root(): 
    return {"ok": True, "yt_dlp_version": getattr(yt_dlp.version, "__version__", "unknown")}

@app.get("/search")
def search(q: str, n: int = 20):
    n = min(max(n, 1), 100)
    try:
        with yt_dlp.YoutubeDL({**BASE, "skip_download": True, "extract_flat": True}) as y:
            d = y.extract_info(f"ytsearch{n}:{q}", download=False)
    except Exception as e:
        raise HTTPException(400, str(e)[:300])
    out = []
    for e in d.get("entries") or []:
        if not e: continue
        vid = e.get("id") or ""
        url = e.get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else None)
        if not url: continue
        thumbs = e.get("thumbnails") or []
        thumb = e.get("thumbnail") or (thumbs[-1]["url"] if thumbs else None) or (f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg" if vid else None)
        out.append({
            "id": vid, 
            "url": url, 
            "title": e.get("title"), 
            "thumbnail": thumb,
            "duration": e.get("duration"), 
            "uploader": e.get("uploader") or e.get("channel"),
            "views": e.get("view_count")
        })
    return {"query": q, "results": out}

@app.get("/info")
def info(url: str):
    try:
        with yt_dlp.YoutubeDL({**BASE, "skip_download": True}) as y:
            d = y.extract_info(url, download=False)
    except Exception as e:
        raise HTTPException(400, str(e)[:300])
    if d.get("entries"): d = d["entries"][0]
    heights, abrs = set(), set()
    for f in d.get("formats") or []:
        if f.get("vcodec") not in (None, "none") and f.get("height"): heights.add(int(f["height"]))
        if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none") and f.get("abr"): abrs.add(int(f["abr"]))
    if not heights and d.get("height"): heights.add(int(d["height"]))
    return {
        "title": d.get("title"), 
        "thumbnail": d.get("thumbnail"), 
        "duration": d.get("duration"),
        "uploader": d.get("uploader"), 
        "platform": d.get("extractor_key"),
        "video_heights": sorted(heights, reverse=True), 
        "audio_bitrates": sorted(abrs, reverse=True) or [128]
    }

@app.get("/download")
def download(url: str, kind: str = "video", height: int = 0, abr: int = 128):
    tmp = tempfile.mkdtemp()
    opts = {**BASE, "outtmpl": os.path.join(tmp, "%(title).80s.%(ext)s")}
    if kind == "audio":
        q = str(min(max(abr, 64), 320))
        opts.update(format="ba/b", postprocessors=[{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": q}])
    else:
        h = f"[height<={height}]" if height else ""
        opts.update(format=f"b{h}/b/best", merge_output_format="mp4")
    try:
        with yt_dlp.YoutubeDL(opts) as y: y.download([url])
    except Exception as e:
        shutil.rmtree(tmp, True); raise HTTPException(400, str(e)[:300])
    files = [f for f in glob.glob(os.path.join(tmp, "*")) if not f.endswith(".part")]
    if not files: shutil.rmtree(tmp, True); raise HTTPException(500, "no file")
    f = max(files, key=os.path.getsize)
    return FileResponse(f, filename=os.path.basename(f), background=BackgroundTask(shutil.rmtree, tmp, True))
