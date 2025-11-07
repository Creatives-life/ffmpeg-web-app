# app.py
import os
import shlex
import uuid
import subprocess
from flask import Flask, render_template, request, send_from_directory, redirect, url_for, flash

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
ALLOWED_EXT = set(["mp4", "mov", "mkv", "webm", "mp3", "wav", "aac", "m4a", "flac"])

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["OUTPUT_FOLDER"] = OUTPUT_FOLDER
app.secret_key = os.environ.get("FLASK_SECRET", "supersecret")

def allowed_filename(fn):
    return "." in fn and fn.rsplit(".", 1)[1].lower() in ALLOWED_EXT

def has_video_stream(filepath):
    """Return True if file has a video stream (uses ffprobe)."""
    try:
        cmd = ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=codec_type",
               "-of", "csv=p=0", filepath]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().strip()
        return "video" in out.lower()
    except subprocess.CalledProcessError:
        return False

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/process", methods=["POST"])
def process():
    # Get options from form
    overlay_enable = request.form.get("overlay_enable") == "on"
    metadata_enable = request.form.get("metadata_enable") == "on"

    title = request.form.get("title", "")
    artist = request.form.get("artist", "")
    album = request.form.get("album", "")
    genre = request.form.get("genre", "")
    year = request.form.get("year", "")
    comment = request.form.get("comment", "")
    copyright_text = request.form.get("copyright", "")

    uploaded = request.files.get("input_file")
    if not uploaded or uploaded.filename == "":
        flash("Please upload a file.")
        return redirect(url_for("index"))
    if not allowed_filename(uploaded.filename):
        flash("File type not allowed.")
        return redirect(url_for("index"))

    # Save input
    uid = uuid.uuid4().hex[:12]
    in_name = f"{uid}_{uploaded.filename}"
    in_path = os.path.join(app.config["UPLOAD_FOLDER"], in_name)
    uploaded.save(in_path)

    # Decide output filename and ffmpeg command depending on whether it's video or audio
    video_present = has_video_stream(in_path)

    out_filename_safe = in_name.rsplit(".", 1)[0] + "_processed"
    if video_present:
        out_filename = f"{out_filename_safe}.mp4"
    else:
        # preserve original extension for audio-only but use mp3 if unknown
        ext = uploaded.filename.rsplit(".", 1)[1].lower()
        if ext in ["mp3","wav","aac","m4a","flac"]:
            out_filename = f"{out_filename_safe}.{ext}"
        else:
            out_filename = f"{out_filename_safe}.mp3"

    out_path = os.path.join(app.config["OUTPUT_FOLDER"], out_filename)

    # Base ffmpeg args
    ffmpeg_cmd = ["ffmpeg", "-y", "-i", in_path]

    # Add filter_complex only for video
    if video_present and overlay_enable:
        # Build the filter to center crop to 9:16, scale to 720x1280 and add drawtext moving vertically
        drawtext = (
            "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
            "fontsize=20:fontcolor=gray:"
            "x=(w-text_w)/2+20:"
            "y=abs(mod(t*100\\,2*h)-h/2):"
            "text='@TowsifAktar'"
        )
        filter_complex = (
            "[0:v]scale=1.0*iw:-1,"
            "crop=ih*9/16:ih:(iw-ih*9/16)/2:(ih-ih)/2,"
            "scale=720:1280,"
            f"split[txt][orig];[txt]{drawtext}[txt];[txt][orig]overlay"
        )
        ffmpeg_cmd += ["-filter_complex", filter_complex, "-map", "0:v", "-map", "0:a?"]
        ffmpeg_cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-c:a", "copy"]
    else:
        # No video overlay. Copy streams (audio-only or video without overlay).
        # For audio-only, copy audio; for video without overlay, copy both streams.
        if video_present:
            ffmpeg_cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-c:a", "copy"]
        else:
            # audio only
            ffmpeg_cmd += ["-c:a", "copy"]

    # Add metadata if requested
    if metadata_enable:
        meta_map = {
            "TITLE": title,
            "ARTIST": artist,
            "ALBUM": album,
            "GENRE": genre,
            "YEAR": year,
            "COMMENT": comment,
            "COPYRIGHT": copyright_text
        }
        for k, v in meta_map.items():
            if v:
                ffmpeg_cmd += ["-metadata", f"{k}={v}"]

    ffmpeg_cmd.append(out_path)

    try:
        # Run ffmpeg
        subprocess.check_output(ffmpeg_cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        # Return ffmpeg error for debugging (in production, hide this).
        error_output = e.output.decode(errors="ignore")
        flash(f"FFmpeg failed: {error_output[:1000]}")
        return redirect(url_for("index"))

    # Serve file for download
    return redirect(url_for("download_file", filename=os.path.basename(out_path)))

@app.route("/downloads/<path:filename>", methods=["GET"])
def download_file(filename):
    return send_from_directory(app.config["OUTPUT_FOLDER"], filename, as_attachment=True)

if __name__ == "__main__":
    # local dev
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
