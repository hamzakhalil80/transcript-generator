from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
import yt_dlp, requests, os   # 👈 added os
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from docx import Document

app = FastAPI()

# ✅ Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # adjust if you want to restrict to frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------- Helper Function ----------
def extract_transcript(video_id: str):
    """
    Fetch YouTube transcript (English if available).
    Returns video info and transcript list [{start, text}, ...]
    """
    url = f"https://www.youtube.com/watch?v={video_id}"

    # ✅ Create cookies.txt dynamically from environment variable if present
    if "YOUTUBE_COOKIES" in os.environ:
        cookie_file = "cookies.txt"
        with open(cookie_file, "w", encoding="utf-8") as f:
            f.write(os.environ["YOUTUBE_COOKIES"])

    ydl_opts = {
        "skip_download": True,
        "cookiefile": cookie_file,   # ✅ ensure yt-dlp uses it
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

        subs = {}
        if info.get("subtitles"):
            subs.update(info["subtitles"])
        if info.get("automatic_captions"):
            subs.update(info["automatic_captions"])

        if not subs:
            return info, None

        en_key = next((k for k in subs.keys() if k.startswith("en")), None)
        if not en_key:
            return info, None

        transcript_url = subs[en_key][0]["url"]
        res = requests.get(transcript_url)
        res.raise_for_status()
        transcript_json = res.json()
        events = transcript_json.get("events", [])

        transcript = [
            {"start": e["tStartMs"] / 1000, "text": seg["utf8"]}
            for e in events if "segs" in e
            for seg in e["segs"]
            if seg.get("utf8", "").strip()
        ]
        return info, transcript


# -------- Merge transcript into natural paragraphs ----------
def merge_paragraphs(transcript, max_chars=300, max_gap=8):
    """
    Merge transcript lines into paragraphs.
    - max_chars: approx max characters per paragraph
    - max_gap: seconds of silence that trigger a new paragraph
    """
    paragraphs = []
    current = ""
    count = 0

    for i, line in enumerate(transcript):
        text = (line.get("text") or "").strip()
        if not text:
            continue
        if text.lower() in ["[applause]", "(applause)", "[music]", "(music)"]:
            continue

        current += (" " if current else "") + text
        count += len(text)

        next_line = transcript[i+1] if i+1 < len(transcript) else None
        long_pause = next_line and (next_line["start"] - line["start"] > max_gap)

        if count > max_chars or long_pause or not next_line:
            paragraphs.append(current.strip())
            current = ""
            count = 0

    return paragraphs


# -------- API: Get Transcript as JSON ----------
@app.get("/transcript/{video_id}")
async def get_transcript(video_id: str):
    try:
        info, transcript = extract_transcript(video_id)
        if not transcript:
            return {"status": "error", "message": "No English captions found"}

        paragraphs = merge_paragraphs(transcript)

        return {
            "status": "success",
            "video_title": info.get("title") or "Transcript",
            "language": "en",
            "transcript": [{"text": p} for p in paragraphs]
        }
    except Exception as e:
        # 👇 Helpful error if cookies expired
        if "sign in" in str(e).lower() or "private" in str(e).lower():
            return {"status": "error", "message": "YouTube cookies may be expired. Please update YOUTUBE_COOKIES in Render."}
        return {"status": "error", "message": str(e)}


# -------- TXT ----------
@app.get("/transcript/{video_id}/download/txt")
async def download_txt(video_id: str):
    try:
        info, transcript = extract_transcript(video_id)
        if not transcript:
            return Response("No English captions found", media_type="text/plain")

        paragraphs = merge_paragraphs(transcript)
        content = "\n\n".join(paragraphs)

        safe_title = "".join(c if c.isalnum() or c in " -_." else "_" for c in info.get("title", video_id))
        filename = f"{safe_title}.txt"

        return Response(
            content,
            media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        return Response(str(e), media_type="text/plain")


# -------- PDF ----------
@app.get("/transcript/{video_id}/download/pdf")
async def download_pdf(video_id: str):
    try:
        info, transcript = extract_transcript(video_id)
        if not transcript:
            return Response("No English captions found", media_type="application/pdf")

        paragraphs = merge_paragraphs(transcript)

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        story = []

        story.append(Paragraph(f"<b>{info.get('title', 'Transcript')}</b>", styles["Title"]))
        story.append(Spacer(1, 12))

        for p in paragraphs:
            story.append(Paragraph(p, styles["Normal"]))
            story.append(Spacer(1, 12))

        doc.build(story)
        buffer.seek(0)

        safe_title = "".join(c if c.isalnum() or c in " -_." else "_" for c in info.get("title", video_id))
        filename = f"{safe_title}.pdf"

        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        return Response(str(e), media_type="application/pdf")


# -------- DOCX ----------
@app.get("/transcript/{video_id}/download/docx")
async def download_docx(video_id: str):
    try:
        info, transcript = extract_transcript(video_id)
        if not transcript:
            return Response("No English captions found", media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

        paragraphs = merge_paragraphs(transcript)

        doc = Document()
        doc.add_heading(info.get("title", "Transcript"), level=1)
        for p in paragraphs:
            doc.add_paragraph(p)

        buffer = BytesIO()
        doc.save(buffer)
        buffer.seek(0)

        safe_title = "".join(c if c.isalnum() or c in " -_." else "_" for c in info.get("title", video_id))
        filename = f"{safe_title}.docx"

        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        return Response(str(e), media_type="text/plain")
