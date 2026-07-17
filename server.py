"""
PixelVerse Video Downloader - Flask Server
Servidor web con yt-dlp para descargar videos.
Funciona en local y en plataformas cloud (Render, Railway, etc.)
"""

from flask import Flask, request, jsonify, send_from_directory, send_file
import subprocess
import sys
import os
import json
import re
import threading
import mimetypes

app = Flask(__name__, static_folder='.', static_url_path='')

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Track active downloads
active_downloads = {}

# Check for cookies in environment variable (Render persistence)
env_cookies = os.environ.get('YOUTUBE_COOKIES')
if env_cookies:
    try:
        with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
            f.write(env_cookies)
        print("Cookies cargadas desde variable de entorno.")
    except Exception as e:
        print("Error guardando cookies de entorno:", e)

# Common yt-dlp args to bypass YouTube bot detection
def get_ytdlp_base_args():
    args = [
        sys.executable, "-m", "yt_dlp",
        "--extractor-args", "youtube:player_client=default",
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "--no-check-certificates",
        "--no-playlist",
    ]
    # Use cookies file if it exists
    if os.path.exists(COOKIES_FILE):
        args += ["--cookies", COOKIES_FILE]
    return args


# ── Static Files ──

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('.', filename)


# ── API: Upload Cookies ──

@app.route('/api/cookies', methods=['POST'])
def api_upload_cookies():
    """Upload a cookies.txt file for YouTube authentication."""
    if 'file' not in request.files:
        # Try raw text body
        data = request.get_json(silent=True)
        if data and data.get('cookies_text'):
            with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
                f.write(data['cookies_text'])
            return jsonify({"success": True, "message": "Cookies guardadas correctamente"})
        return jsonify({"error": "No se recibio archivo"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Archivo vacio"}), 400

    file.save(COOKIES_FILE)
    return jsonify({"success": True, "message": "Cookies guardadas correctamente"})


@app.route('/api/cookies/status')
def api_cookies_status():
    """Check if cookies file exists."""
    exists = os.path.exists(COOKIES_FILE) and os.path.getsize(COOKIES_FILE) > 0
    return jsonify({"has_cookies": exists})


# ── API: Video Info ──

@app.route('/api/info')
def api_info():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({"error": "URL requerida"}), 400

    try:
        cmd = get_ytdlp_base_args() + [
            "--dump-json", "--no-download", "--no-warnings", url
        ]
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=45,
            encoding="utf-8", errors="replace"
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else "No se pudo obtener info del video"
            return jsonify({"error": error_msg}), 400

        info = json.loads(result.stdout)

        # Extract formats
        formats = []
        seen = set()
        for f in info.get("formats", []):
            ext = f.get("ext", "?")
            height = f.get("height")
            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")
            filesize = f.get("filesize") or f.get("filesize_approx")
            format_id = f.get("format_id", "")

            if vcodec == "none" and acodec == "none":
                continue

            if height and vcodec != "none":
                label = f"{height}p {ext}"
            elif acodec != "none" and vcodec == "none":
                label = f"Audio {ext}"
            else:
                label = f"{ext}"

            if label not in seen:
                seen.add(label)
                formats.append({
                    "format_id": format_id,
                    "label": label,
                    "ext": ext,
                    "height": height,
                    "filesize": filesize,
                    "has_video": vcodec != "none",
                    "has_audio": acodec != "none",
                })

        formats.sort(key=lambda x: x.get("height") or 0, reverse=True)

        return jsonify({
            "title": info.get("title", "Sin titulo"),
            "thumbnail": info.get("thumbnail", ""),
            "duration": info.get("duration", 0),
            "uploader": info.get("uploader", "Desconocido"),
            "view_count": info.get("view_count", 0),
            "description": (info.get("description", "") or "")[:300],
            "webpage_url": info.get("webpage_url", url),
            "formats": formats[:15],
        })

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timeout: el video tardo demasiado en responder"}), 408
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: Start Download ──

@app.route('/api/download')
def api_download():
    url = request.args.get('url', '').strip()
    quality = request.args.get('quality', 'best')

    if not url:
        return jsonify({"error": "URL requerida"}), 400

    download_id = str(abs(hash(url + quality)))[:10]

    if download_id in active_downloads and active_downloads[download_id].get("status") == "downloading":
        return jsonify({"download_id": download_id, "status": "downloading", "message": "Ya se esta descargando"})

    active_downloads[download_id] = {
        "status": "downloading",
        "progress": "0%",
        "filename": None,
        "error": None,
    }

    thread = threading.Thread(target=download_worker, args=(download_id, url, quality))
    thread.daemon = True
    thread.start()

    return jsonify({"download_id": download_id, "status": "downloading"})


def download_worker(download_id, url, quality):
    try:
        if quality == "audio":
            format_sel = "bestaudio/best"
            extra = ["--extract-audio", "--audio-format", "mp3"]
        elif quality == "720":
            format_sel = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
            extra = []
        elif quality == "480":
            format_sel = "bestvideo[height<=480]+bestaudio/best[height<=480]/best"
            extra = []
        elif quality == "360":
            format_sel = "bestvideo[height<=360]+bestaudio/best[height<=360]/best"
            extra = []
        else:
            format_sel = "bestvideo+bestaudio/best"
            extra = []

        output_template = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")

        cmd = get_ytdlp_base_args() + [
            "-f", format_sel,
            "-o", output_template,
            "--no-warnings", "--newline",
            "--merge-output-format", "mp4",
        ] + extra + [url]

        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )

        filename = None
        for line in process.stdout:
            line = line.strip()
            progress_match = re.search(r'(\d+\.?\d*)%', line)
            if progress_match:
                active_downloads[download_id]["progress"] = progress_match.group(0)

            dest_match = re.search(r'\[(?:download|Merger)\].*?(?:Destination|Merging):\s*(.+)', line)
            if dest_match:
                filename = dest_match.group(1).strip()

            already_match = re.search(r'\[download\]\s*(.+?)\s*has already been downloaded', line)
            if already_match:
                filename = already_match.group(1).strip()

        process.wait()

        if process.returncode == 0:
            if not filename or not os.path.exists(filename):
                files = sorted(
                    [os.path.join(DOWNLOAD_DIR, f) for f in os.listdir(DOWNLOAD_DIR)],
                    key=os.path.getmtime, reverse=True
                )
                if files:
                    filename = files[0]

            if filename and os.path.exists(filename):
                active_downloads[download_id]["status"] = "complete"
                active_downloads[download_id]["progress"] = "100%"
                active_downloads[download_id]["filename"] = os.path.basename(filename)
            else:
                active_downloads[download_id]["status"] = "error"
                active_downloads[download_id]["error"] = "Archivo no encontrado tras la descarga"
        else:
            active_downloads[download_id]["status"] = "error"
            active_downloads[download_id]["error"] = "yt-dlp termino con error"

    except Exception as e:
        active_downloads[download_id]["status"] = "error"
        active_downloads[download_id]["error"] = str(e)


# ── API: Download Status ──

@app.route('/api/status')
def api_status():
    download_id = request.args.get('id', '')
    if not download_id or download_id not in active_downloads:
        return jsonify({"error": "Download no encontrado"}), 404
    return jsonify(active_downloads[download_id])


# ── API: Serve File ──

@app.route('/api/file/<path:filename>')
def api_file(filename):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    filepath = os.path.realpath(filepath)

    if not filepath.startswith(os.path.realpath(DOWNLOAD_DIR)):
        return jsonify({"error": "Acceso denegado"}), 403

    if not os.path.exists(filepath):
        return jsonify({"error": "Archivo no encontrado"}), 404

    return send_file(filepath, as_attachment=True, download_name=filename)


# ── API: List Downloads ──

@app.route('/api/list')
def api_list():
    files = []
    if os.path.exists(DOWNLOAD_DIR):
        for f in os.listdir(DOWNLOAD_DIR):
            fpath = os.path.join(DOWNLOAD_DIR, f)
            if os.path.isfile(fpath):
                files.append({
                    "name": f,
                    "size": os.path.getsize(fpath),
                    "modified": os.path.getmtime(fpath),
                })
    files.sort(key=lambda x: x["modified"], reverse=True)
    return jsonify({"files": files})


# ── Run ──

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 9090))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    print(f"\n  Video Downloader corriendo en http://localhost:{port}\n")
    app.run(host='0.0.0.0', port=port, debug=debug)
