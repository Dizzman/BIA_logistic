"""Модуль содержит функцию для преобразования входной строки с входными данными
с окнами для НБ и АЗС в данные, подходящие для работы модели.
"""

MINUTES_IN_DAY = 60*24
HOUR = 60


def convert_time_windows(input_data):
    """Функция для преобразования входной строки с временными окнами в формиат,
    соответствующий параметрам модели.
    
    Arguments:
        input_data {str} -- Входная строка, например: "00:00-06:00;08:30-23:59"
    
    Returns:
        dict -- Результат работы алгоритма для дневной и ночной смен, например: 
        ({'window': (0.5, 12.0), 'blocks': []}, {'window': (0.0, 10.0), 'blocks': []})
    """

    timeline = {}

    for time in range(0, MINUTES_IN_DAY):
        timeline[time] = 0

    def convert_string_repr_to_min(_s):
        hours = int(_s.split(":")[0])
        minutes = int(_s.split(":")[1])

        return 60 * hours + minutes

    def get_period_borders(_s):
        since_int = convert_string_repr_to_min(_s.split("-")[0])
        till_int = convert_string_repr_to_min(_s.split("-")[1])
        return since_int, till_int

    splitted_periods_input = input_data.split(';')

    for element in splitted_periods_input:
        since, till = get_period_borders(element)
        if since > till:
            for time in range(since, MINUTES_IN_DAY):
                timeline[time] = 1
            
            for time in range(0, till+1):
                timeline[time] = 1
        else:
            for time in range(since, till+1):
                timeline[time] = 1

    day_timeline = {}
    night_timeline = {}

    for time in range(8 * HOUR, 20 * HOUR):
        day_timeline[time - 8 * HOUR] = timeline[time]
    day_timeline[720] = day_timeline[719]

    current_minute = 0

    for time in range(20 * HOUR, MINUTES_IN_DAY):
        night_timeline[current_minute] = timeline[time]
        current_minute += 1

    for time in range(0, 8 * HOUR):
        night_timeline[current_minute] = timeline[time]
        current_minute += 1

    night_timeline[0] = night_timeline[1]
    day_timeline[0] = day_timeline[1]
    
    night_timeline[current_minute] = night_timeline[current_minute-1]

    def get_text_repr(_timeline):
        window_border_left = 720
        window_border_right = 0
        number_of_working_hours = 0
        result_blocks = []
        result_window = (0.0, 0.0)

        for key, val in _timeline.items():
            if val == 1:
                window_border_left = min(window_border_left, key)
                window_border_right = max(window_border_right, key)
                number_of_working_hours += 1

        if number_of_working_hours > 1:
            block_is_closed = True
            block_border_left = block_border_right = 0
            for time in range(window_border_left, window_border_right + 1):
                if _timeline[time] == 0 and block_is_closed:
                    block_is_closed = False
                    block_border_left = time - 1
                elif _timeline[time] == 1 and not block_is_closed:
                    block_border_right = time
                    result_block = (block_border_left / HOUR, block_border_right / HOUR)
                    result_blocks.append(result_block)
                    block_border_left = block_border_right = 0
                    block_is_closed = True

            result_window = (window_border_left / HOUR, window_border_right / HOUR)

        return {'window': result_window, 'blocks': result_blocks}

    return get_text_repr(day_timeline), get_text_repr(night_timeline)


if __name__ == '__main__':
    print(convert_time_windows("20:00-08:00;15:00-23:00"))
