"""Модуль для проверки резервуаров на переполнение в ходе осуществления поставок
"""


def validate_reservoir_overflow_advanced(parameters, stations, timetable, deliveries, log):
    """Функция для проверки резервуаров на переполнение в ходе осуществления поставок.
    :param parameters: Dict с параметрами расчёта в целом
    :param stations: Список АЗС и их характеристики
    :param timetable: Список операций в графике рейсов
    :param deliveries: Список секций БВ с объёмами поставок
    :param log: Объект класса Response для сбора информации о валидации
    :return: None
    """

    planning_time_beginning = parameters['planning_start']
    planning_time_end = parameters['planning_start'] + parameters['planning_duration'] - 1

    for checking_shift in range(planning_time_beginning, planning_time_end + 1):
        for station in stations:
            for reservoir in station.reservoirs:
                current_start_state = None
                current_consumption = None
                for state in reservoir.states:
                    if state.shift == checking_shift - 1:
                        current_start_state = state.asu_state
                    if state.shift == checking_shift:
                        current_consumption = state.consumption

                # Вычисляем суммарные поставки на текущий резервуар и отмечаем время

                deliveries_to_reservoir = []

                for delivery in deliveries:
                    if delivery.shift == checking_shift and delivery.asu == station.asu_id \
                            and delivery.n == reservoir.n:
                        volume_added = False
                        for el in deliveries_to_reservoir:
                            if el['start_time'] == delivery.time:
                                el['volume'] += delivery.section_volume
                                volume_added = True
                        if not volume_added:
                            deliveries_to_reservoir.append(
                                {'volume': delivery.section_volume,
                                 'start_time': delivery.time}
                            )
                import math
                for delivery in deliveries_to_reservoir:
                    for operation in timetable:
                        if operation.operation == 'слив' and operation.location == station.asu_id \
                                and math.floor(delivery['start_time'] * 100) == math.floor(operation.start_time * 100):
                            delivery['end_time'] = operation.end_time

                # Проверяем условие переполнения в случаях одной или двух поставок в смену

                if len(deliveries_to_reservoir) == 1:
                    local_delivery = deliveries_to_reservoir[0]
                    consumption_before_loading = (local_delivery['end_time'] / 12.0) * current_consumption
                    loaded_volume = local_delivery['volume']

                    if current_start_state - consumption_before_loading + \
                            loaded_volume > reservoir.capacity:
                        diff = reservoir.capacity - (current_start_state - consumption_before_loading + \
                            loaded_volume)
                        log.add_message(module='validate_reservoir_overflow',
                                        shift=checking_shift,
                                        station_id=station.asu_id,
                                        reservoir_id=reservoir.n,
                                        message='Переполнение резервуара '
                                                '({:.1f} - {:.1f} + {:.1f} > {:.1f}, Δ = {:.1f})'.
                                        format(current_start_state, consumption_before_loading,
                                               loaded_volume, reservoir.capacity, abs(diff)))

                elif len(deliveries_to_reservoir) == 2:
                    if deliveries_to_reservoir[0]['start_time'] < deliveries_to_reservoir[1]['start_time']:
                        first_delivery = deliveries_to_reservoir[0]
                        second_delivery = deliveries_to_reservoir[1]
                    else:
                        first_delivery = deliveries_to_reservoir[1]
                        second_delivery = deliveries_to_reservoir[0]

                    consumption_before_first_loading = (first_delivery['end_time'] / 12.0) * current_consumption
                    consumption_before_second_loading = (second_delivery['end_time'] / 12.0) * current_consumption

                    if current_start_state - consumption_before_first_loading + \
                            first_delivery['volume'] > reservoir.capacity:
                        diff = reservoir.capacity - (current_start_state - consumption_before_first_loading +
                                                     first_delivery['volume'])
                        log.add_message(module='validate_reservoir_overflow',
                                        shift=checking_shift,
                                        station_id=station.asu_id,
                                        reservoir_id=reservoir.n,
                                        message='Переполнение резервуара '
                                                '({:.1f} - {:.1f} + {:.1f} > {:.1f}, Δ = {:.1f})'.
                                        format(current_start_state, consumption_before_first_loading,
                                               first_delivery['volume'], reservoir.capacity, abs(diff)))

                    if current_start_state - consumption_before_second_loading + \
                            first_delivery['volume'] + second_delivery['volume'] > reservoir.capacity:
                        diff = reservoir.capacity - (current_start_state - consumption_before_second_loading +
                                                     first_delivery['volume'] + second_delivery['volume'])
                        log.add_message(module='validate_reservoir_overflow',
                                        shift=checking_shift,
                                        station_id=station.asu_id,
                                        reservoir_id=reservoir.n,
                                        message='Переполнение резервуара '
                                                '({:.1f} + {:.1f} + {:.1f} - {:.1f} > {:.1f}, Δ = {:.1f})'.
                                        format(current_start_state, first_delivery['volume'], second_delivery['volume'],
                                               consumption_before_second_loading, reservoir.capacity, abs(diff)))
