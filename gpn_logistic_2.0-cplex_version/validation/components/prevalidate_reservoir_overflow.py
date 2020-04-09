"""Модуль для исследования данных на предмет переполнения резервуаров при
отложенной поставке"""


def validate_reservoir_overflow(data, parameters, horizon):
    has_warning = False
    has_fatal_error = False
    error_response = list()
    warning_response = list()

    # Образец сообщений об ошибке.
    template = ' переполнение резервуара №{} ({}) на {:.1f} в смену {} \nНачальный остаток: {:.1f} | ' \
               'Потребление до пополнения: {:.1f} | Доставлено в смену: {:.1f} (+{:.1f} - ранее) | Вместимость: {:.1f}'
    warning_template = 'Допустимое' + template
    error_template = 'КРИТИЧЕСКОЕ' + template
    # Образец сообщения об изменении начального остатка.
    change_template = 'Для резервуара №{} ({}) был изменен начальный остаток с {:.1f} на {:.1f}'

    for key, val in data.volumes_to_add.items():
        asu_id, n, time, added_volume = *key, val

        # print("Привоз на АЗС {} (рез. {}) в смену {} - {} л.".format(asu_id, n, time, added_volume, added_volume))

        # Находим начальный остаток для данного бака

        start_volume = data.initial_fuel_state.get((asu_id, n), 0.0)

        # print("Начальный остаток для бака: {}".format(start_volume))

        # Находим суммарное потребление до требуемой смены (не включая)

        total_consumption_before = sum(data.consumption.get((asu_id, n, t), 0.0) for t in range(horizon[0], time))

        # print("Суммарное потребление до требуемой смены: {}".format(total_consumption_before))

        # Находим потребление в требуемую смену

        total_consumption_inside = data.consumption.get((asu_id, n, time), 0.0)

        # print("Потребление в требуемую смену: {}".format(total_consumption_inside))

        # Найти ограничения снизу и сверху бака
        total_capacity_min = data.tank_death_vol.get((asu_id, n), 0.0)
        total_capacity_max = data.tank_max_vol.get((asu_id, n), 0.0)

        # print("Ограничения по баку: {} - {}".format(total_capacity_min, total_capacity_max))

        # Найти момент поставки

        from integral_planning.functions import overload_risk
        time_to_unload = overload_risk(asu_id, 0, parameters, data)

        # print("Момент поставки: {}".format(time_to_unload))

        # Найти потребление в смену до момента поставки

        total_consumption_inside_before_delivery = total_consumption_inside * (1 - time_to_unload)

        # print("Потребление до момента поставки: {}".format(total_consumption_inside_before_delivery))

        # Находим добавленные вручную поставки для данного бака

        total_additional_volumes_before = sum(data.volumes_to_add.get((asu_id, n, i), 0.0) for i in range(1, time))

        # print("Добавленный вручную объём до рассматриваемой смены: {}".format(total_additional_volumes_before))

        # Вычислить состояние бака на момент пополнения

        state_at_the_unload_moment = (start_volume -
                                      total_consumption_before -
                                      total_consumption_inside_before_delivery +
                                      added_volume +
                                      total_additional_volumes_before)

        # print("Состояние бака после пополнения: {}".format(state_at_the_unload_moment))
        # print()

        # Проверка состояния в сравнении с вместимостью

        if state_at_the_unload_moment > total_capacity_max:
            has_warning = True

            response_item = {'asu': asu_id,
                             'reservoir': n,
                             'delivery_volume': added_volume,
                             'delivery_volume_before': total_additional_volumes_before,
                             'capacity': total_capacity_max,
                             'overloading_volume': state_at_the_unload_moment - total_capacity_max,
                             'start_volume': start_volume,
                             'total_consumed_until_delivery': total_consumption_before +
                                                              total_consumption_inside_before_delivery,
                             'time': time}
            # При переполнении смотрим, насколько оно допустимо. Если превышение больше часового потребления,
            # или в результате изменения данных начальный остаток окажется ниже мертвого остатка - переполение критично.
            if state_at_the_unload_moment > (total_capacity_max +
                                             parameters.admissible_reservoir_overflow * total_consumption_inside) or \
                    start_volume - (state_at_the_unload_moment - total_capacity_max) < total_capacity_min:
                has_fatal_error = True
                error_response.append(response_item)
            else:
                warning_response.append(response_item)

    if has_fatal_error:
        print("<FOR_USER>\nНе пройдена проверка данных на переполнение резервуаров. Найдено критическое переполнение."
              " Пожалуйста, проверьте входные данные.")
        # Выводим информацию обо всех найденных ошибках
        for el in error_response:
            print(error_template.format(
                el['reservoir'],
                el['asu'],
                el['overloading_volume'],
                el['time'],
                el['start_volume'],
                el['total_consumed_until_delivery'],
                el['delivery_volume'],
                el['delivery_volume_before'],
                el['capacity']))
        for el in warning_response:
            print(warning_template.format(
                el['reservoir'],
                el['asu'],
                el['overloading_volume'],
                el['time'],
                el['start_volume'],
                el['total_consumed_until_delivery'],
                el['delivery_volume'],
                el['delivery_volume_before'],
                el['capacity']))
        print("</FOR_USER>")
        exit(1)
    elif has_warning:
        print("<FOR_USER>\nНайдены некритичные ошибки при проверке данных на переполнение резервуаров."
              " Стартовые остатки будут уменьшены. Пожалуйста, проверьте входные данные.")
        for el in warning_response:
            # Если переполнения некритичны, изменяем начальный остаток и выводим информацию об ошибках
            asu_id, n = el['asu'], el['reservoir']
            data.initial_fuel_state[asu_id, n] = el['start_volume'] - el['overloading_volume'] - 1e-2
            print(warning_template.format(
                el['reservoir'],
                el['asu'],
                el['overloading_volume'],
                el['time'],
                el['start_volume'],
                el['total_consumed_until_delivery'],
                el['delivery_volume'],
                el['delivery_volume_before'],
                el['capacity']))
            print(change_template.format(
                el['reservoir'],
                el['asu'],
                el['start_volume'],
                data.initial_fuel_state[asu_id, n]))
        print("</FOR_USER>")
