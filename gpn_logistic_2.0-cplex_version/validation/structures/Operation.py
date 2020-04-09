def convert_to_rel_hours(str, shift):
    if type(str) == float:
        print(str)
        exit()

    str = str.split(":")
    str[0] = int(str[0])
    str[1] = int(str[1])
    del str[2]

    if shift % 2:
        str[0] -= 8
        if str[0] < 0:
            str[0] += 24
    else:
        str[0] -= 20
        if str[0] < 0:
            str[0] += 24

    result = int(str[0]) + str[1] / 60.0
    return result


class Operation:
    def __init__(self, pandas_line, volumes_add=False):
        if not volumes_add:
            self.shift = int(pandas_line['shift'])
            self.truck = int(pandas_line['truck'])
            self.location = pandas_line['location']
            self.operation = pandas_line['operation']
            self.start_time = float(pandas_line['start_time'])
            self.duration = float(pandas_line['duration'])
            self.end_time = float(pandas_line['end_time'])
        else:
            self.shift = int(pandas_line['time'])
            self.location = pandas_line['asu_id']
            self.start_time = convert_to_rel_hours(pandas_line['left_bound'], self.shift)
            self.end_time = convert_to_rel_hours(pandas_line['right_bound'], self.shift)
            self.duration = self.end_time - self.start_time
            self.operation = 'слив'
            self.truck = None