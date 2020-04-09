"""Модуль для проверки результатов расчёта на нарушение временных окон
доступа к НБ
"""

from validation.utils.time_windows_parser import parse_time_point_to_minutes
from validation.utils.time_windows_parser import convert_minutes_to_time


def validate_stations_time_windows(parameters, stations, timetable, log):
    """Основная функция, осуществляющая проверку наличия нарушений временных
    окон при наливе на НБ
    :return:
    """

    stations_local = {}

    for station in stations:
        stations_local[station.asu_id] = station

    planning_time_beginning = parameters['planning_start']
    planning_time_end = parameters['planning_start'] + parameters['planning_duration'] - 1

    for checking_shift in range(planning_time_beginning, planning_time_end + 1):
        for operation in timetable:
            if operation.operation == 'слив' and operation.shift == checking_shift:
                tl = parse_time_point_to_minutes(operation.shift,
                                                 operation.start_time)

                if not stations_local[operation.location].is_available_at_the_moment(tl):
                    log.add_message(module='validate_stations_time_windows',
                                    shift=checking_shift,
                                    time=convert_minutes_to_time(tl),
                                    station_id=operation.location,
                                    truck_id=operation.truck,
                                    message="Начало слива на АЗС в недопустимое время")
