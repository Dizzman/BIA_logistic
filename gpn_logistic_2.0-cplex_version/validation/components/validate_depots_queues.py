"""Модуль для проверки результатов расчёта на наличие очередей на НБ
"""

from validation.utils.time_windows_parser import parse_time_period_to_time_segment
from validation.utils.time_windows_parser import convert_minutes_to_time

TIME_LIMIT = 1440


def validate_depots_queues(parameters, depots, timetable, log):
    """Основная функция, осуществляющая проверку превышения допустимого количе-
    ства БВ на НБ в каждый момент времени
    :param parameters: Dict с параметрами расчёта в целом
    :param depots: Список нефтебаз и их характеристики
    :param timetable: Список операций в графике рейсов
    :return: None
    """
    queue_size = {}
    queue_allowed = {}

    planning_time_beginning = parameters['planning_start']
    planning_time_end = parameters['planning_start'] + parameters['planning_duration'] - 1

    for checking_shift in range(planning_time_beginning, planning_time_end + 1):
        for depot in depots:
            depot_id = depot.depot_id
            queue_size[depot_id] = {}
            queue_allowed[depot_id] = depot.depot_traffic_capacity

            for time in range(0, TIME_LIMIT):
                queue_size[depot_id][time] = 0

        for operation in timetable:
            if operation.operation == 'налив' and operation.shift == checking_shift:
                tl = parse_time_period_to_time_segment(operation.shift,
                                                       operation.start_time,
                                                       operation.end_time)
                for key, el in tl.items():
                    if el:
                        queue_size[operation.location][key] += 1

        for depot in depots:
            for time in range(0, TIME_LIMIT):
                if queue_size[depot.depot_id][time] > queue_allowed[depot.depot_id]:
                    log.add_message(module='validate_depots_queues',
                                    shift=checking_shift,
                                    time=convert_minutes_to_time(time),
                                    depot_id=depot.depot_id,
                                    message="Превышение допустимого к-ва БВ на НБ")


def is_allowable_to_load_at_nb(shift, time_moment, depot_id, depots, timetable):
    queue_size = {}
    queue_allowed = {}

    for depot in depots:
        queue_size[depot.depot_id] = {}
        queue_allowed[depot.depot_id] = depot.depot_traffic_capacity

    for time in range(0, TIME_LIMIT):
        queue_size[depot_id][time] = 0

    for operation in timetable:
        if operation.operation == 'налив' and operation.shift == shift and operation.location == depot_id:
            tl = parse_time_period_to_time_segment(operation.shift,
                                                   operation.start_time,
                                                   operation.end_time)

            for key, el in tl.items():
                if el:
                    queue_size[operation.location][key] += 1

    if queue_size[depot_id][time_moment] >= queue_allowed[depot_id]:
        return False

    return True


def queue_at_depot(shift, time_moment, depot_id, depots, timetable):
    queue_size = {}
    queue_allowed = {}

    for depot in depots:
        queue_size[depot.depot_id] = {}
        queue_allowed[depot.depot_id] = depot.depot_traffic_capacity

    for time in range(0, TIME_LIMIT):
        queue_size[depot_id][time] = 0

    for operation in timetable:
        if operation.operation == 'налив' and operation.shift == shift and operation.location == depot_id:
            tl = parse_time_period_to_time_segment(operation.shift,
                                                   operation.start_time,
                                                   operation.end_time)

            for key, el in tl.items():
                if el:
                   queue_size[operation.location][key] += 1

    return queue_size[depot_id][time_moment]