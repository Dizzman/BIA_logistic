"""Модуль для проверки результатов расчёта на наличие очередей на АЗС
"""

from validation.utils.time_windows_parser import parse_time_period_to_time_segment
from validation.utils.time_windows_parser import convert_minutes_to_time

TIME_LIMIT = 1440


def validate_stations_queues(parameters, stations, timetable, log):
    """Основная функция, осуществляющая проверку превышения допустимого количе-
    ства БВ на НБ в каждый момент времени
    :param parameters: Dict с параметрами расчёта в целом
    :param stations: Список АЗС и их характеристики
    :param timetable: Список операций в графике рейсов
    :return: None
    """
    queue_size = {}

    planning_time_beginning = parameters['planning_start']
    planning_time_end = parameters['planning_start'] + parameters['planning_duration'] - 1

    for checking_shift in range(planning_time_beginning, planning_time_end + 1):
        #print("Смена {}".format(checking_shift))
        for station in stations:
            station_id = station.asu_id
            queue_size[station_id] = {}

            for time in range(0, TIME_LIMIT):
                queue_size[station_id][time] = 0

        #for el in timetable:
         #   print(el.__dict__)

        for operation in timetable:
            if operation.operation == 'слив' and operation.shift == checking_shift:
                tl = parse_time_period_to_time_segment(operation.shift,
                                                       operation.start_time,
                                                       operation.end_time)
                for key, el in tl.items():
                    if el:
                        queue_size[operation.location][key] += 1

        for station in stations:
            for time in range(0, TIME_LIMIT):
                if queue_size[station.asu_id][time] > 1:
                    print(station.asu_id)
                    print(queue_size[station.asu_id][time])
                    log.add_message(module='validate_station_queues',
                                    shift=checking_shift,
                                    time=convert_minutes_to_time(time),
                                    station_id=station.asu_id,
                                    message="Превышение допустимого к-ва БВ на АЗС")

