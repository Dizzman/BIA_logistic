#!/usr/bin/env python

from flask import Flask, request, jsonify, send_from_directory, render_template, url_for, abort
from werkzeug.utils import secure_filename
from functools import wraps

import datetime
import io
import logging
import os
import time
import select
import shutil
import subprocess
import threading
import traceback
import zipdir

logger = logging.getLogger('gpn_logistic_rest')
logger.setLevel(logging.DEBUG)
fh = logging.StreamHandler()
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
logger.addHandler(fh)

AUTH_TOKEN = os.environ.get(
    'AUTH_TOKEN',
    ''
)

UPLOAD_FOLDER = os.environ.get(
    'UPLOAD_FOLDER',
    '/tmp/gpn_logistic_2.0/input/scenario_2/'
)

OUTPUT_FOLDER = os.environ.get(
    'OUTPUT_FOLDER',
    '/tmp/gpn_logistic_2.0/output/',
)

UPLOAD_ARCHIVE_FOLDER = os.environ.get(
    'UPLOAD_ARCHIVE_FOLDER',
    '/tmp/gpn_logistic_2.0/upload_archive'
)

RESULT_ARCHIVE_FOLDER = os.environ.get(
    'RESULT_ARCHIVE_FOLDER',
    '/tmp/gpn_logistic_2.0/result_archive'
)

RESULT_LOG_FOLDER = os.environ.get(
    'RESULT_LOG_FOLDER',
    '/tmp/gpn_logistic_2.0/result_log'
)


ALLOWED_EXTENSIONS = set(('xlsx',))

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not check_auth(request.headers.get('Authorization')):
            abort(401)
        return f(*args, **kwargs)
    return decorated_function

def check_auth(token):
    if AUTH_TOKEN=='':
        return True
    else: 
        return ('Basic ' + AUTH_TOKEN)==token

def allowed_file(filename):
    return True
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_state():
    if exec_process is None:
        return 'not started'
    elif exec_process.poll() is None:
        return 'calculating'
    elif exec_process.poll() == 0:
        return 'finished successfully'
    else:
        return 'error'


app = Flask(__name__)

@app.route('/')
@app.route('/doc')
@login_required
def help():
    return render_template('plaintext.html',
                           text="""
API

/archive: html страница с архивными данными: входные/выходные параметры расчёта, лог

/clean?until_date={date}: очистка хранилища архивных данных до "date" формата "%Y-%m-%d", где %Y - год, %m - месяц, %d - день

/calculate: начинает расчёт (в отдельном процессе), если расчёт в данный момент не шёл.

/current_log: возвращает текущий stdout/stderr расчётного процесса

/doc: возвращает данную страницу

/kill: завершает текущий процесс

/output/filename: возвращает файл запроса

/output_list: возрващает список файлов в каталоге OUTPUT_FOLDER {
    { 'files': { 'file1.xlsx': { 'size':12356 }, 'file2.xlsx': { 'size': 111 } } }

/status: возвращает статус рачёта: {'status': STATUS}, где STATUS - один из 'not started', 'calculating', 'finished successfully', 'error'

/upload_input: принимает mulipart post запрос с набором файлов, кладёт их в UPLOAD_FOLDER (/tmp/gpn_logistic_2.0/input/scenario_2/)

/upload_list: возвращает список файлов в каталоге INPUT_FOLDER
""")


@app.route('/upload_input', methods=['POST'])
@login_required
def upload_input():
    logger.info('/upload_input: got upload input request, removing old input directory content')
    shutil.rmtree(UPLOAD_FOLDER)
    logger.info('/upload_input: directory deleted, uploading files into directory')
    os.makedirs(UPLOAD_FOLDER)
    upload_files = {
        'uploaded': {},
        'ignored':  {},
    }
    for filename, f in request.files.to_dict().items():
        if f and allowed_file(filename):
            filename = secure_filename(filename)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            f.save(filepath)
            filesize = os.path.getsize(filepath)
            logger.info('/upload_input: uploaded {filename}, {filesize} bytes'.format(
                filename=filename,
                filesize=filesize,
            ))
            upload_files['uploaded'][filename] = {
                'size': filesize,
            }
        else:
            logger.info('/upload_input: ignored {filename}'.format(
                filename=filename
            ))
            upload_files['ignored'][filename] = {
                'reason': 'is not allowed',
            }
    return jsonify(upload_files)


@app.route('/upload_list')
@login_required
def upload_list():
    logger.info('/input_list get request')
    return jsonify({
        'files': {
            filename: {
                'size': os.path.getsize(os.path.join(UPLOAD_FOLDER, filename))
            }
            for filename in os.listdir(UPLOAD_FOLDER) if os.path.isfile(os.path.join(UPLOAD_FOLDER, filename))
        }
    })


@app.route('/calculate')
@login_required
def calculate():
    global exec_process
    global log_buffer
    global calculation_start
    global calc_id
    global last_state
    logger.info('/calculate: get request for start calculating')

    if get_state() == 'calculating':
        logger.warning('/calculate: already started, do nothing')
        return jsonify({
            'status': 'cannot start, already calculating'
        })

    calculation_start= datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

    logger.info('/calculate: archiving input, cleaning')
    zipdir.dir_to_zip(UPLOAD_ARCHIVE_FOLDER, "input_" + calculation_start + ".zip", UPLOAD_FOLDER)

    shutil.rmtree(OUTPUT_FOLDER)
    os.makedirs(OUTPUT_FOLDER)
    logger.info('/calculate: output directory recreated')

    log_buffer = io.StringIO()

    os.chdir('/tmp/gpn_logistic_2.0');

    exec_process = subprocess.Popen(
        [
            'python3',
            '-u',
            '/tmp/gpn_logistic_2.0/main_script.py'
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )

    logger.info('/calculate: calculating process started')

    last_state = get_state()
    return jsonify({
            'status': 'calculation started'
    })


@app.route('/current_log')
@login_required
def current_log(log_start=True):
    state = last_state

    if state == 'not started':
        logger.info('/current_log: no calc for log')
        return 'No calc started yet'

    return render_template('plaintext.html', text=log_buffer.getvalue())


def fill_log_buffer():
    if get_state() == 'not started':
        return

    select_poll_stdout = select.poll()
    select_poll_stdout.register(exec_process.stdout, select.POLLIN)

    before = datetime.datetime.now()
    while datetime.datetime.now() < before + datetime.timedelta(seconds=0.5):
        if select_poll_stdout.poll(1.5):
            line = exec_process.stdout.readline().decode('utf-8')
            log_buffer.write(line)
            if line:
                logger.info("/computational_log: {}".format(line.strip()))
        else:
            time.sleep(0.1)
    select_poll_stdout.unregister(exec_process.stdout)


@app.route('/status')
@login_required
def status():
    logger.info('/status get status request')
    return jsonify({
        'status': last_state
    })


@app.route('/kill')
@login_required
def kill():
    if get_state() == 'calculating':
        exec_process.kill()
        logger.info('/kill process killed')
        return jsonify({
            'status': 'nothing to kill'
        })
    return jsonify({
        'status': 'killed',
    })


@app.route('/output_list')
@login_required
def output_list():
    logger.info('/output_list get request')
    return jsonify({
        'files': {
            filename: {
                'size': os.path.getsize(os.path.join(OUTPUT_FOLDER, filename))
            }
            for filename in os.listdir(OUTPUT_FOLDER) if os.path.isfile(os.path.join(OUTPUT_FOLDER, filename))
        }
    })


@app.route('/output/<path:filename>')
@login_required
def output(filename):
    logger.info('/output: get request for {}'.format(filename))
    return send_from_directory(OUTPUT_FOLDER, filename)


@app.route('/ping')
def ping():
    return 'ping success'


@app.route('/ready')
def ready():
    return 'server is ready'


@app.route('/clean')
def clean():
    try:
        until_date = datetime.datetime.strptime(request.args.get('until_date'), "%Y-%m-%d")
    except (ValueError, TypeError) as err:
        return "Wrong format: {}".format(err), 404

    inputs = get_directory(UPLOAD_ARCHIVE_FOLDER)
    outputs = dict(get_directory(RESULT_ARCHIVE_FOLDER))
    logs = dict(get_directory(RESULT_LOG_FOLDER))
    to_delete = []
    to_delete_fnames = []

    for f, _ in inputs:
        calc_started = os.path.splitext(f)[0][len('input_'):]
        date_started = datetime.datetime.strptime(calc_started, "%Y-%m-%d_%H-%M-%S")
        if date_started < until_date:
            to_delete.append(calc_started)
            outname = f.replace('input', 'output')
            logname = f.replace('.zip', '.log')[len('input_'):]
            to_delete_fnames.append(os.path.join(UPLOAD_ARCHIVE_FOLDER, f))
            to_delete_fnames.append(os.path.join(RESULT_ARCHIVE_FOLDER, outname))
            to_delete_fnames.append(os.path.join(RESULT_LOG_FOLDER, logname))
    logger.info('/clean: removing files {}'.format(" ".join(to_delete_fnames)))
    for f in to_delete_fnames:
        os.remove(f)
    return "{} archived calculations removed: {}".format(len(to_delete), " ".join(to_delete))


def archive_output():
    logger.info('/sidecar: archiving result')
    zipdir.dir_to_zip(RESULT_ARCHIVE_FOLDER, "output_" + calculation_start + ".zip", OUTPUT_FOLDER)
    with open(os.path.join(RESULT_LOG_FOLDER, calculation_start + ".log"), 'w') as f:
        f.write(log_buffer.getvalue())



def sidecar_work():
    global last_state
    while True:
        try:
            fill_log_buffer()
            if get_state() != last_state and last_state == 'calculating':
                fill_log_buffer()
                archive_output()
            last_state = get_state()
            time.sleep(5)
        except Exception as e:
            logger.error('sidecar_work: got exception')
            traceback.print_exc()


def get_directory(directory):
    archives = []
    for f in os.listdir(directory):
        size = get_size(directory, f)
        archives.append((f, size))
    return archives


def get_size(directory, filename):
    return os.path.getsize(os.path.join(directory, filename))


mapping = {
    'input': UPLOAD_ARCHIVE_FOLDER,
    'output': RESULT_ARCHIVE_FOLDER,
    'log': RESULT_LOG_FOLDER
}

@app.route('/archive/<filetype>/<path:filename>')
def archive_file(filename, filetype):
    directory = mapping[filetype]
    logger.info('/archive: get request for {} {}'.format(filetype, filename))
    return send_from_directory(directory, filename)


def prepare_data():
    inputs = get_directory(UPLOAD_ARCHIVE_FOLDER)
    outputs = dict(get_directory(RESULT_ARCHIVE_FOLDER))
    logs = dict(get_directory(RESULT_LOG_FOLDER))
    calcs = []
    for f, isize in inputs:
        if not f.startswith('input_'):
            calc_started = os.path.splitext(f)[0]
            inp = (
                url_for('archive_file', filetype='input', filename=f),
                "Input. {} bytes".format(isize)
            )

            outsize = outputs.get(f)
            out = (
                url_for('archive_file', filetype='output', filename=f) if outsize else None,
                "Output. {} bytes".format(outsize) if outsize else "No file"
            )

            logfile = f.replace('.zip', '.log')
            logsize = logs.get(logfile)
            log = (
                url_for('archive_file', filetype='log', filename=logfile) if logsize else None,
                "Log. {} bytes".format(logsize) if logsize else "No File"
            )
        else:
            calc_started = os.path.splitext(f)[0][len('input_'):]
            inp = (
                url_for('archive_file', filetype='input', filename=f),
                "Input. {} bytes".format(isize)
            )

            outname = f.replace('input', 'output')
            outsize = outputs.get(outname)
            out = (
                url_for('archive_file', filetype='output', filename=outname) if outsize else None,
                "Output. {} bytes".format(outsize) if outsize else "No file"
            )

            logfile = f.replace('.zip', '.log')[len('input_'):]
            logsize = logs.get(logfile)
            log = (
                url_for('archive_file', filetype='log', filename=logfile) if logsize else None,
                "Log. {} bytes".format(logsize) if logsize else "No File"
            )

        calcs.append((calc_started, inp, out, log))

    print("\n".join(map(str, calcs)))
    return sorted(calcs, reverse=True)


@app.route('/archive')
@login_required
def archive():
    return render_template('archives.html', calcs=prepare_data())

def init():
    global exec_process
    global calculation_start
    global last_state

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    os.makedirs(UPLOAD_ARCHIVE_FOLDER, exist_ok=True)
    os.makedirs(RESULT_ARCHIVE_FOLDER, exist_ok=True)
    os.makedirs(RESULT_LOG_FOLDER, exist_ok=True)

    exec_process = None
    calculation_start = None
    last_state = 'not started'


def start_sidecar():
    p = threading.Thread(target=sidecar_work, args=())
    p.start()
    return p


def run():
    sidecar = start_sidecar()
    app.run(host='0.0.0.0')

if __name__ == '__main__':
    init()
    run()
