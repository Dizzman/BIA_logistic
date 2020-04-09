from mode_switcher.modes import Mode
import json
import os.path


def main():    
    mode = Mode()
    mode_path = './input/scenario_2/mode.json'
    mode_type = None

    if os.path.isfile(mode_path):
        with open(mode_path) as f:
            mode_type = json.load(f)

    if mode_type:
        mode.run(mode_type['mode'])
    else:
        mode.run('normal')


if __name__ == '__main__':
    main()
