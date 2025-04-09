import os
import uuid
from flask import Flask, request, jsonify, send_from_directory, render_template
import ffmpeg
from werkzeug.utils import secure_filename
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import logging
from logging.handlers import RotatingFileHandler
import time
from threading import Thread

app = Flask(__name__)

log_handler = RotatingFileHandler('converter.log', maxBytes=1000000, backupCount=3)
log_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
app.logger.addHandler(log_handler)
app.logger.setLevel(logging.INFO)

UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'converted'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'flv', 'webm', 'mp3', 'wav', 'ogg', 'aac'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

FORMAT_PARAMS = {
    'mp4': {
        'video_codec': 'libx264',
        'audio_codec': 'aac',
        'preset': 'fast',
        'crf': 23,
        'movflags': '+faststart',
    },
    'webm': {
        'video_codec': 'libvpx-vp9',
        'audio_codec': 'libopus',
        'crf': 30,
        'deadline': 'realtime',
        'row-mt': '1',
        'b:v': '0',
    },
    'avi': {
        'video_codec': 'mpeg4',
        'audio_codec': 'mp3',
        'q:v': 3,
    },
    'mov': {
        'video_codec': 'libx264',
        'audio_codec': 'aac',
        'preset': 'fast',
        'crf': 23,
        'movflags': '+faststart',
        'pix_fmt': 'yuv420p',
    },
    'mkv': {
        'video_codec': 'libx264',
        'audio_codec': 'aac',
        'preset': 'fast',
        'crf': 23,
        'strict': 'normal',
    },
    'mp3': {
        'audio_codec': 'libmp3lame',
        'b:a': '192k',
        'ar': 44100,
    },
    'wav': {
        'audio_codec': 'pcm_s16le',
        'ar': 44100,
    },
    'ogg': {
        'audio_codec': 'libvorbis',
        'b:a': '128k',
        'ar': 44100,
        'compression_level': 1,
    },
    'aac': {
        'audio_codec': 'aac',
        'b:a': '192k',
        'ar': 44100,
    }
}
for fmt in FORMAT_PARAMS:
    FORMAT_PARAMS[fmt]['global_options'] = [
        '-loglevel', 'info',
        '-threads', '0',
        '-map', '0',
        '-c:s', 'copy' if fmt == 'mkv' else 'mov_text',
        ]

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["1 per second"]
)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def convert_file(input_path, output_path, output_format):
    try:
        if output_format not in FORMAT_PARAMS:
            app.logger.error(f"Unsupported format: {output_format}")
            return False

        params = FORMAT_PARAMS[output_format]
        app.logger.info(f"Starting conversion: {input_path} -> {output_path}")
        app.logger.info(f"Using params: {params}")

        input_stream = ffmpeg.input(input_path)
        
        output_kwargs = {}
        
        if 'video_codec' in params:
            output_kwargs['c:v'] = params['video_codec']
        
        if 'audio_codec' in params:
            output_kwargs['c:a'] = params['audio_codec']
        
        for key, value in params.items():
            if key not in ['video_codec', 'audio_codec', 'global_options']:
                output_kwargs[key] = value

        output_stream = input_stream.output(output_path, **output_kwargs)
        
        for opt in params.get('global_options', []):
            output_stream = output_stream.global_args(opt)
        
        output_stream.run(overwrite_output=True, capture_stdout=True, capture_stderr=True)
        app.logger.info("Conversion completed successfully")
        return True
        
    except ffmpeg.Error as e:
        app.logger.error(f"FFmpeg error: {e.stderr.decode('utf8')}")
        return False
    except Exception as e:
        app.logger.error(f"Conversion error: {str(e)}")
        return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/convert', methods=['POST'])
@limiter.limit("1 per second")
def convert():
    if 'file' not in request.files:
        app.logger.warning("No file part in request")
        return jsonify({'error': 'Файл не загружен'}), 400
    
    file = request.files['file']
    output_format = request.form.get('format', 'mp4')
    
    if file.filename == '':
        app.logger.warning("No file selected")
        return jsonify({'error': 'Файл не выбран'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        unique_id = str(uuid.uuid4())
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{unique_id}_{filename}")
        output_filename = f"{os.path.splitext(filename)[0]}.{output_format}"
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], f"{unique_id}_{output_filename}")
        
        file.save(input_path)
        app.logger.info(f"File saved to {input_path}")
        
        if convert_file(input_path, output_path, output_format):
            os.remove(input_path)

            download_url = f"/download/{unique_id}_{output_filename}"
            return jsonify({
                'success': True,
                'download_url': download_url,
                'filename': output_filename
            })
        else:
            return jsonify({'error': 'Ошибка конвертации файла'}), 500
    app.logger.warning(f"Invalid file format: {file.filename}")
    return jsonify({'error': 'Недопустимый формат файла'}), 400

@app.route('/download/<filename>')
def download(filename):
    return send_from_directory(app.config['OUTPUT_FOLDER'], filename, as_attachment=True)

def cleanup_old_files(directory, max_age_seconds=3600):
    try:
        current_time = time.time()
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if os.path.isfile(file_path):
                file_age = current_time - os.path.getmtime(file_path)
                if file_age > max_age_seconds:
                    try:
                        os.remove(file_path)
                        app.logger.info(f"Удалён старый файл: {filename}")
                    except Exception as e:
                        app.logger.error(f"Ошибка удаления файла {filename}: {str(e)}")
    except Exception as e:
        app.logger.error(f"Ошибка при очистке директории {directory}: {str(e)}")

def run_cleanup_periodically(interval=360):
    while True:
        cleanup_old_files(app.config['UPLOAD_FOLDER'])
        cleanup_old_files(app.config['OUTPUT_FOLDER'])
        time.sleep(interval)
if __name__ == '__main__':
    cleanup_thread = Thread(target=run_cleanup_periodically, daemon=True)
    cleanup_thread.start()

    app.run(host='0.0.0.0', port=5000, debug=True)