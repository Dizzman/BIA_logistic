def get_timeline(template):

    def convert_string_repr_to_min(_s):
        hours = int(_s.split(":")[0])
        minutes = int(_s.split(":")[1])

        return 60 * hours + minutes

    result = {}

    for time in range(0, 60 * 24):
        result[time] = 0

    since_int = convert_string_repr_to_min(template.split("-")[0])
    till_int = convert_string_repr_to_min(template.split("-")[1])

    return since_int, till_int


def convert_minutes_to_time(minutes):
    hours = str(minutes // 60)
    minutes = str(minutes % 60)

    if len(hours) == 1:
        hours = "0{}".format(hours)

    if len(minutes) == 1:
        minutes = "0{}".format(minutes)

    answer = "{}:{}".format(hours, minutes)

    return answer


def parse_time_windows_to_time_scale(time_windows_repr):
    _temp = time_windows_repr.split(";")

    result = {}
    for time in range(0, 60 * 24):
        result[time] = 0

    for el in _temp:
        since_int, till_int = get_timeline(el)

        if till_int < since_int:
            for time in range(since_int, 60 * 24):
                result[time] = 1
            for time in range(0, till_int):
                result[time] = 1
        else:
            for time in range(since_int, till_int):
                result[time] = 1

    return result


def parse_time_period_to_time_segment(shift, from_t, to_t):
    result_from, result_to = 0, 0

    if shift % 2:
        result_from += 8 * 60
        result_to += 8 * 60
    else:
        result_from += 20 * 60
        result_to += 20 * 60

    from_minutes = int(from_t * 60)
    to_minutes = int(to_t * 60)

    since_int = (result_from + from_minutes) % 1440
    till_int = (result_to + to_minutes) % 1440

    result = {}
    for time in range(0, 60 * 24):
        result[time] = 0

    if till_int < since_int:
        for time in range(since_int, 60 * 24):
            result[time] = 1
        for time in range(0, till_int):
            result[time] = 1
    else:
        for time in range(since_int, till_int):
            result[time] = 1

    return result


def parse_time_point_to_minutes(shift, time_point):
    result = 0

    if shift % 2:
        result += 8 * 60
    else:
        result += 20 * 60

    result += int(60 * time_point)

    if result >= 1440:
        result = result % 1440

    return result