import yt_dlp

url = "https://www.youtube.com/watch?v=DTnBEpbIkEc"
ydl_opts = {"skip_download": True, "writesubtitles": True, "subtitleslangs": ["en"]}

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info(url, download=False)
    print("Title:", info["title"])
    print("Available subs:", info.get("subtitles"))
    print("Auto subs:", info.get("automatic_captions"))
