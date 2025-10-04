from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import yt_dlp, requests, re
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import Paragraph, SimpleDocTemplate
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
    ydl_opts = {"skip_download": True}
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


# -------- Merge transcript into paragraphs ----------
def merge_paragraphs(transcript, chunk_size=3):
    lines = []
    for t in transcript:
        text = t.get("text", "").strip()
        if not text:
            continue
        if text.lower() in ["[applause]", "(applause)", "[music]", "(music)"]:
            continue
        # Capitalize first letter if missing
        if text and not text[0].isupper():
            text = text[0].upper() + text[1:]
        lines.append(text)

    # Group into paragraphs
    paragraphs, chunk = [], []
    for i, line in enumerate(lines, 1):
        chunk.append(line)
        if i % chunk_size == 0:
            paragraphs.append(" ".join(chunk))
            chunk = []
    if chunk:
        paragraphs.append(" ".join(chunk))

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
        return {"status": "error", "message": str(e)}


# -------- TXT ----------
@app.get("/transcript/{video_id}/download/txt")
async def download_txt(video_id: str, chunk_size: int = Query(3, ge=1, le=20)):
    try:
        info, transcript = extract_transcript(video_id)
        if not transcript:
            return Response("No English captions found", media_type="text/plain")

        paragraphs = merge_paragraphs(transcript, chunk_size)
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
async def download_pdf(video_id: str, chunk_size: int = Query(3, ge=1, le=20)):
    try:
        info, transcript = extract_transcript(video_id)
        if not transcript:
            return Response("No English captions found", media_type="application/pdf")

        paragraphs = merge_paragraphs(transcript, chunk_size)

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        story = []

        story.append(Paragraph(f"<b>{info.get('title', 'Transcript')}</b>", styles["Title"]))
        for p in paragraphs:
            story.append(Paragraph(p, styles["Normal"]))

        doc.build(story)
        pdf_data = buffer.getvalue()
        buffer.close()

        safe_title = "".join(c if c.isalnum() or c in " -_." else "_" for c in info.get("title", video_id))
        filename = f"{safe_title}.pdf"

        return Response(
            pdf_data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        return Response(str(e), media_type="application/pdf")


# -------- DOCX ----------
@app.get("/transcript/{video_id}/download/docx")
async def download_docx(video_id: str, chunk_size: int = Query(3, ge=1, le=20)):
    try:
        info, transcript = extract_transcript(video_id)
        if not transcript:
            return Response("No English captions found", media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

        paragraphs = merge_paragraphs(transcript, chunk_size)

        doc = Document()
        doc.add_heading(info.get("title", "Transcript"), level=1)
        for p in paragraphs:
            doc.add_paragraph(p)

        buffer = BytesIO()
        doc.save(buffer)
        buffer.seek(0)

        safe_title = "".join(c if c.isalnum() or c in " -_." else "_" for c in info.get("title", video_id))
        filename = f"{safe_title}.docx"

        return Response(
            buffer.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        return Response(str(e), media_type="text/plain")