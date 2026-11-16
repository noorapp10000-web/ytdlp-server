import os, tempfile, shutil, glob, re
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
import yt_dlp, imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], expose_headers=["Content-Disposition"])
BASE = {"quiet": True, "noplaylist": True, "ffmpeg_location": FF}

@app.get("/")
def root(): return {"ok": True}

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
    return {"title": d.get("title"), "thumbnail": d.get("thumbnail"), "duration": d.get("duration"),
            "uploader": d.get("uploader"), "platform": d.get("extractor_key"),
            "video_heights": sorted(heights, reverse=True), "audio_bitrates": sorted(abrs, reverse=True) or [128]}

@app.get("/download")
def download(url: str, kind: str = "video", height: int = 0, abr: int = 128):
    tmp = tempfile.mkdtemp()
    opts = {**BASE, "outtmpl": os.path.join(tmp, "%(title).80s.%(ext)s")}
    if kind == "audio":
        q = str(min(max(abr, 64), 320))
        opts.update(format="bestaudio/best", postprocessors=[{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": q}])
    else:
        h = f"[height<={height}]" if height else ""
        opts.update(format=f"bv*{h}+ba/b{h}/bv*+ba/b", merge_output_format="mp4")
    try:
        with yt_dlp.YoutubeDL(opts) as y: y.download([url])
    except Exception as e:
        shutil.rmtree(tmp, True); raise HTTPException(400, str(e)[:300])
    files = [f for f in glob.glob(os.path.join(tmp, "*")) if not f.endswith(".part")]
    if not files: shutil.rmtree(tmp, True); raise HTTPException(500, "no file")
    f = max(files, key=os.path.getsize)
    return FileResponse(f, filename=os.path.basename(f), background=BackgroundTask(shutil.rmtree, tmp, True))
