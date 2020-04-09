import main_script

from distutils.dir_util import copy_tree

import functools
import json
import os
import shutil


PROJ_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        '..')
)

GPNL_INPUT_PATH = os.path.join(
        PROJ_PATH,
        'input',
        'scenario_2'
)

GPNL_OUTPUT_PATH = os.path.join(
    PROJ_PATH,
    'output'
)

GPNL_JSON_MODE_FILE = os.path.join(
    GPNL_INPUT_PATH,
    'mode.json'
)


def normal(mode_name, input_dir, output_dir):
    shutil.rmtree(GPNL_INPUT_PATH, ignore_errors=True)
    shutil.rmtree(GPNL_OUTPUT_PATH, ignore_errors=True)
    os.makedirs(GPNL_INPUT_PATH, exist_ok=True)
    os.makedirs(GPNL_OUTPUT_PATH, exist_ok=True)

    copy_tree(input_dir, GPNL_INPUT_PATH)
    with open(GPNL_JSON_MODE_FILE, 'w') as json_file:
        json.dump({"mode": mode_name}, json_file)
    main_script.main()
    copy_tree(GPNL_OUTPUT_PATH, output_dir)


def split(mode_name, input_dir, output_dir):
    gpnl_split_path = os.path.join(GPNL_OUTPUT_PATH, 'split_data')

    shutil.rmtree(GPNL_INPUT_PATH, ignore_errors=True)
    shutil.rmtree(GPNL_OUTPUT_PATH, ignore_errors=True)
    os.makedirs(GPNL_INPUT_PATH, exist_ok=True)
    os.makedirs(gpnl_split_path, exist_ok=True)
    copy_tree(input_dir, GPNL_INPUT_PATH)
    with open(GPNL_JSON_MODE_FILE, 'w') as json_file:
        json.dump({"mode": mode_name}, json_file)
    main_script.main()
    copy_tree(gpnl_split_path, output_dir)


def merge(mode_name, input_dirs, output_dir):
    gpnl_merge_path = os.path.join(GPNL_INPUT_PATH, 'merge')

    shutil.rmtree(GPNL_INPUT_PATH, ignore_errors=True)
    shutil.rmtree(GPNL_OUTPUT_PATH, ignore_errors=True)
    os.makedirs(GPNL_OUTPUT_PATH, exist_ok=True)
    os.makedirs(gpnl_merge_path, exist_ok=True)

    for abs_input_path in input_dirs:
#        fname = os.dirname(abs_input_path)
#        newname = os.path.join(gpnl_merge_path, fname)
#        os.makedirs(newname)
#        copy_tree(abs_input_path, newname)
        copy_tree(abs_input_path, gpnl_merge_path)
    with open(GPNL_JSON_MODE_FILE, 'w') as json_file:
        json.dump({"mode": mode_name}, json_file)

    main_script.main()
    copy_tree(GPNL_OUTPUT_PATH, output_dir)


def copy(input_dirs, output_dir):
    for d in input_dirs:
        copy_tree(d, output_dir)


task_bind = {
    'normal': functools.partial(normal, 'normal'),
    'package': functools.partial(normal, 'package'),
    'detailed': functools.partial(normal, 'detailed'),
    'split': functools.partial(split, 'split'),
    'merge': functools.partial(merge, 'merge'),
    'copy': copy,
}


if __name__ == '__main__':

    import matplotlib
    matplotlib.use('Agg')

    print('in main')
    WORKDIR_FOLDER = os.environ.get(
        'WORKDIR_FOLDER',
        '/tmp/gpnl/'
    )

    normal_input = os.path.join(
        WORKDIR_FOLDER,
        'normal_input'
    )

    split_input = normal_input

    split_output = os.path.join(
        WORKDIR_FOLDER,
        'split_output'
    )

    package_inputs = (
        lambda: [os.path.join(split_output, s_o)
                 for s_o in os.listdir(split_output)]
    )


    package_outputs = os.path.join(
        WORKDIR_FOLDER,
        'package_outputs'
    )

    merge_inputs = (
        lambda: [os.path.join(package_outputs, s_o)
                 for s_o in os.listdir(package_outputs)]
    )

    merge_output = os.path.join(
        WORKDIR_FOLDER,
        'merge_output'
    )

    copy_inputs = [
        merge_output,
        normal_input
    ]

    copy_output = os.path.join(
        WORKDIR_FOLDER,
        'detailed_input'
    )

    detailed_input = copy_output

    detailed_output = os.path.join(
        WORKDIR_FOLDER,
        'detailed_output'
    )
    
    output_dir = os.path.join(
        WORKDIR_FOLDER,
        'split_output'
    )

#    split('split', split_input, split_output)
#    for package in package_inputs():
#        normal(
#            'package',
#            package,
#            os.path.join(package_outputs, os.path.basename(package))
#        )
#    print(merge_inputs())
#    merge('merge', merge_inputs(), merge_output)
#    copy(copy_inputs, copy_output)
    
#    normal('detailed', detailed_input, detailed_output)
