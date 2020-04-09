import contextlib
import datetime
import io
import json
import logging
import multiprocessing
import os
import sys
import shutil
import subprocess
import tarfile
import threading
import time
import traceback
import queue

from functools import wraps

from flask import (
    Flask, request, jsonify, send_from_directory,
    render_template, url_for, abort, send_file
)
from werkzeug.utils import secure_filename

from calculate.dispatcher import task_bind


logger = logging.getLogger('gpn_logistic_rest')
logger.setLevel(logging.DEBUG)
fh = logging.StreamHandler()
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
logger.addHandler(fh)


app = Flask(__name__)

AUTH_TOKEN = os.environ.get(
    'AUTH_TOKEN',
    ''
)

WORKDIR_FOLDER = os.environ.get(
    'WORKDIR_FOLDER',
    '/tmp/parallela/'
)

PORT = os.environ.get(
    'PORT',
    '5000'
)

ARCHIVE_FOLDER = os.environ.get(
    'ARCHIVE_FOLDER',
    '/tmp/archive/'
)

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

class CustomWriter():
    def __init__(self, q):
        self.q = q
        self._inner = []

    def write(self, msg):
        self.q.put(msg)
        self._inner.append(msg)

    def flush(self):
        pass

    def log(self):
        return ''.join(self._inner)


class Sidecar():
    def __init__(self, proc_queue):
        self.proc_queue = proc_queue
        self.log_list = []
        self._sidecar_stop = False

    def _run(self):
        while not self._sidecar_stop:
            try:
                got = self.proc_queue.get(timeout=1)
                self.log_list.append(got)
                print(got, end='')
            except queue.Empty as e:
                continue
        
    def run(self):
        self._thread = threading.Thread(target=self._run, args=())
        self._thread.start()

    def get_log(self):
        return '\n'.join(self.log_list)

    def stop(self):
        self._sidecar_stop = True
        self._thread.join()


def redir_runner(proc_queue, target, args):
    sys.stdout.detach()
    sys.stdout = CustomWriter(proc_queue)
    sys.stderr.detach()
    sys.stderr = sys.stdout
#    sys.stderr = CustomWriter(proc_queue) #sys.stdout
    target(args)


class CalcProcess():
    def __init__(self):
        self._proc = None
        self._sidecar = None
        self._queue = None
        
    def start_proc(self, tasks):
        if self.status() == 'calculating':
            return False
        self.tasks = tasks

        if self._proc:
            self._proc.join()

        if self._sidecar:
            self._sidecar.stop()

        self._queue = multiprocessing.Queue()

        self._sidecar = Sidecar(self._queue)
        self._sidecar.run()

        self._proc = multiprocessing.Process(
            target=redir_runner, args=(self._queue, run_tasks, tasks))

        self._proc.start()

    def status(self):
        if self._proc is None:
            return 'not started'

        if self._proc.is_alive():
            return 'calculating'

        exitcode = self._proc.exitcode
        if exitcode != 0:
            return 'error'
        elif exitcode == 0:
            return 'finished successfully'

    def cancel(self):
        if self.status() == 'calculating':
            self._proc.terminate()
            return True
        return False

    def get_log(self):
        if not self._sidecar:
            return 'No log is available'
        return self._sidecar.get_log()


def run_tasks(tasks_json):
    try:
        calculation_start= datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

        first_task = tasks_json['run'][0]
        folder_in = first_task.get('folder_in')
        if not folder_in:
            raise ValueError('No folder_in path in task')
        if first_task.get('type') == 'merge':
            input_tar = os.path.join(WORKDIR_FOLDER, '{}.tar'.format(folder_in))
            if not os.path.isfile(input_tar):
                raise ValueError('No appropriate tar uploaded')
#TODO check add task name
            shutil.copy(
                input_tar,
                os.path.join(ARCHIVE_FOLDER, '{}.input.{}.{}.tar'.format(calculation_start, first_task.get('type'),first_task.get('name'))))
        else:
            input_tar_gz = os.path.join(WORKDIR_FOLDER, '{}.tar.gz'.format(folder_in))
            if not os.path.isfile(input_tar_gz):
                raise ValueError('No appropriate tar uploaded')
            shutil.copy(
                input_tar_gz,
                os.path.join(ARCHIVE_FOLDER, '{}.input.{}.{}.tar.gz'.format(calculation_start, first_task.get('type'), first_task.get('name'))))


        for task in tasks_json['run']:
            task_name = task.get('name')
            task_type = task.get('type')
            inp = task.get('folder_in')
            inp_arg = os.path.join(WORKDIR_FOLDER, inp)
            if task_type == 'merge':
                inp_arg = [os.path.join(inp_arg, subfolder) for subfolder in task.get('subfolders_in')]
            out = task.get('folder_out')
            out_arg = os.path.join(WORKDIR_FOLDER, out)
            os.makedirs(out_arg, exist_ok=True)
            do_task = task_bind.get(task_name)
            do_task(inp_arg, out_arg)
        last_task = tasks_json['run'][-1]
        folder_out_name = last_task.get('folder_out')
        result_folder = os.path.join(WORKDIR_FOLDER, folder_out_name)

        if last_task.get('type') == 'split':
            tarname = os.path.join(WORKDIR_FOLDER, '{}.tar'.format(folder_out_name))
            with tarfile.open(tarname, 'w') as outer_tar:
                for dirname in os.listdir(result_folder):
                    if os.path.isdir(os.path.join(result_folder, dirname)):
                        innertarname = os.path.join(result_folder, '{}.tar.gz'.format(dirname))
                        with tarfile.open(innertarname, 'w:gz') as inner_tar:
                            inner_tar.add(os.path.join(result_folder, dirname), arcname='')
                        outer_tar.add(innertarname, arcname='{}.tar.gz'.format(dirname))
            shutil.copy(
                tarname,
                os.path.join(ARCHIVE_FOLDER, '{}.output.{}.{}.tar'.format(calculation_start,last_task.get('type'),last_task.get('name'))))
            with open(os.path.join(ARCHIVE_FOLDER, '{}.current_log.{}.{}.txt'.format(calculation_start,last_task.get('type'),last_task.get('name'))), 'w') as f:
                f.write(sys.stdout.log())
            return

        tarname = os.path.join(WORKDIR_FOLDER, '{}.tar.gz'.format(folder_out_name))
        with tarfile.open(tarname, 'w:gz') as tar:
            tar.add(result_folder, arcname='')

        shutil.copy(
            tarname,
            os.path.join(ARCHIVE_FOLDER, '{}.output.{}.{}.tar.gz'.format(calculation_start,last_task.get('type'),last_task.get('name'))))

    except Exception as e:
        traceback.print_exc()
        raise
    finally:
        with open(os.path.join(ARCHIVE_FOLDER, '{}.current_log.{}.{}.txt'.format(calculation_start,last_task.get('type'),last_task.get('name'))), 'w') as f:
            f.write(sys.stdout.log())

@app.route('/calculate', methods=['POST'])
@login_required
def calculate():
    if calc_process.status() == 'calculating':
        abort(404, 'already started') # FIXME: not atomic

    taskfile = request.files.to_dict().get('tasks.json')
    if not taskfile:
        abort(404, 'No tasks.json file uploaded')
    try:
        tasks = json.loads(taskfile.read())
    except json.decoder.JSONDecodeError:
        abort(404, 'tasks.json does not seem like json file')

    try:
        shutil.rmtree(WORKDIR_FOLDER, ignore_errors=True)
        os.makedirs(WORKDIR_FOLDER)
        in_type = tasks['run'][0].get('type', 'standard')
        folder_in = tasks['run'][0].get('folder_in')
        folder_out = tasks['run'][0].get('folder_out')
        parameters = tasks['run'][0].get('parameters')
        if in_type in 'merge':
            filename = '{}.tar'.format(folder_in)
            f = request.files.to_dict().get(filename)
            filepath = os.path.join(WORKDIR_FOLDER,  filename)
            f.save(filepath)
            with tarfile.open(filepath) as tar:
                path = os.path.join(WORKDIR_FOLDER, folder_in)
                os.makedirs(path, exist_ok=True)
                tar.extractall(path=path)
                for inside_tar in os.listdir(path):
                    dirname=inside_tar[:-len('.tar.gz')]
                    
                    tarname = os.path.join(WORKDIR_FOLDER, folder_in, inside_tar)
                    with tarfile.open(tarname) as inside_tar:
                        inside_tar.extractall(path=os.path.join(WORKDIR_FOLDER, folder_in, dirname))
                    os.remove(tarname)
#            os.remove(filepath)
        else:
            filename = '{}.tar.gz'.format(folder_in)
            filepath = os.path.join(WORKDIR_FOLDER, filename)
            f = request.files.to_dict().get(filename)
            f.save(filepath)
            with tarfile.open(filepath) as tar:
                tar.extractall(path=os.path.join(WORKDIR_FOLDER, folder_in))

        calc_process.start_proc(tasks)
    except Exception as e:
        traceback.print_exc()
        abort(404, e)
        raise

    return jsonify({'ok':'ok'})


@app.route('/status')
@login_required
def status():
    stat = calc_process.status()
    return jsonify({
        'status': stat
    })

@app.route('/archive')
@login_required
def archive():
    content = {}
    for filename in os.listdir(ARCHIVE_FOLDER):
        calc_started, t = filename.split('.')[:2]        
        content.setdefault(calc_started, {})[t] = filename

    calcs = []
    for calc_started, fs in content.items():
        finput = fs.get('input')
        foutput = fs.get('output')
        flog = fs.get('current_log')
#TODO check file names
        calcs.append((
            calc_started,
            (url_for('archive_file', filename=finput) if finput else None, finput.replace(calc_started,'') if finput else 'No input'),
            (url_for('archive_file', filename=foutput) if foutput else None,  'Output' if foutput else 'No output'),
            (url_for('archive_file', filename=flog) if flog else None, 'Log' if flog else 'No log')))

    calcs.sort(reverse=True)
    return render_template('archive.html', calcs=calcs)

@app.route('/archive/<path:filename>')
@login_required
def archive_file(filename):
    directory = ARCHIVE_FOLDER
    logger.info('/archive: get request for {}'.format(filename))
    return send_from_directory(directory, filename)


@app.route('/download')
@login_required
def download():
    if calc_process.status() != 'finished successfully':
        abort(404, 'No proper result')
    
    last_task = calc_process.tasks['run'][-1]
    folder_out = last_task.get('folder_out')
    filename = '{}.tar.gz'.format(folder_out)
    if last_task.get('type') == 'split':
        filename = '{}.tar'.format(folder_out)

    return send_file(
        os.path.join(WORKDIR_FOLDER, filename),
        attachment_filename=filename,
        as_attachment=True
    )

@app.route('/current_log')
@login_required
def current_log():
    if not calc_process:
        return "No log is available"
    return render_template('plaintext.html', text=calc_process.get_log())


@app.route('/ping')
def ping():
    return 'ping success'


@app.route('/ready')
def ready():
    return 'server is ready'

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

def init():
    global calc_process
    os.makedirs(ARCHIVE_FOLDER, exist_ok=True)
    os.makedirs(WORKDIR_FOLDER, exist_ok=True)
    calc_process = CalcProcess()

def run():
    app.run(host='0.0.0.0', port=int(PORT))


if __name__ == '__main__'    :
    init()
    run()
