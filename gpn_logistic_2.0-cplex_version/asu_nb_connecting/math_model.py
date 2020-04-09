from docplex.mp.model import Model
import os.path

def gpn_asu_nb_connecting(volumes, departures, parameters, distances, global_params, conf):
    """Модель расчёта привязки АЗС к НБ.
    :param volumes: Требуемые объёмы поставок на АЗС.
    :param departures: Требуемые заезды на АЗС.
    :param parameters: Словарь с параметрами модели.
    :param distances: Словарь с расстояниями между НБ и АЗС.
    :return: dict, у которого ключ - номер нефтебазы, значение - set() номеров АЗС,
    которые привязаны к выбранной нефтебазе.
    Пример: {1: {10001, 10002, 10003}, 2: {10004}}.
    """

    ITERATIVE_MODE = False

    def get_required_volume(asu_n_local, sku_local, shift_local):
        """Функция, возвращающая требуемый объём поставок на АЗС asu типа НП sku.
        :param asu_n_local: Идентификатор АЗС.
        :param sku_local: Идентификатор типа НП.
        :param shift_local: Номер смены.
        :return: float - объём поставок.
        """
        for requirement in volumes:
            if requirement['id_asu'] == asu_n_local[0] and requirement['n'] == asu_n_local[1] and requirement['sku'] == sku_local and \
                    requirement['time'] == shift_local:
                return requirement['volume']
        return 0.0

    def get_number_of_trips(asu_local, shift_local):
        """Функция, вовзращающая количество рейсов на АЗС asu_local.
        :param asu_local: Идентификатор АЗС.
        :param shift_local: Номер смены.
        :return: int - количество рейсов.
        """
        for trip in departures:
            if trip['time'] == shift_local and trip['id_asu'] == asu_local:
                return trip['departures']
        return 0

    def get_rest_nb(nb_id, sku_id, current_shift_id=conf['current_shift_id'], is_prioritized_pool=False):
        """Функция для получения объёмов открытия на НБ nb_id по типу топлива sku_id
        доступных на требуемую смену.
        :param nb_id: Идентификатор НБ.
        :param sku_id: Идентификатор типа НП.
        :param current_shift_id: Номер текущей смены.
        :return: Остаток на нефтебазе на начало суток.
        """

        result = 0.0
        first_day_id = (current_shift_id + 1) // 2
        is_record_found = False

        if not current_shift_id % 2 and not is_prioritized_pool:
            second_day_id = first_day_id + 1

            for nb in parameters['nb_set']:
                if nb['id'] == nb_id and nb['sku'] == sku_id and \
                        (nb['day'] == first_day_id or nb['day'] == second_day_id):
                    result += nb['avail']
                    is_record_found = True
        else:
            for nb in parameters['nb_set']:
                if nb['id'] == nb_id and nb['sku'] == sku_id \
                        and nb['day'] == first_day_id:
                    result = nb['avail']
                    is_record_found = True

        if not is_record_found:
            return 999999999.0

        return result

    # Инициализация объекта модели

    m = Model(name='gpn_asu_nb_connecting')
    print("Построение модели привязки АЗС к НБ.")
    if parameters['night_mode']:
        print("Ночная смена. Учтены дополнительные ограничения модели.")
    else:
        print("Дневная смена. Стандартный набор ограничений.")

    # Инициализация контейнеров для переменных модели

    vars = dict()
    vars['dep'] = dict()
    vars['vol'] = dict()
    vars['delta'] = dict()
    vars['connection'] = dict()
    vars['queue'] = dict()
    vars['is_nb_connected'] = dict()
    vars['n_nb_connected'] = dict()


    depots_sku = global_params.fuel_in_depot
    
    petrol_types = global_params.sku_reference
    petrol_groups_new = global_params.fuel_in_depot

    parameters['sku_set'] = []

    for key, val in depots_sku.items():
        parameters['sku_set'].extend(val)

    parameters['sku_set'] = list(set(petrol_types.keys()))

    # Перезапись списка nb_unique

    parameters['nb_unique'] = set()
    
    for depot_sku, skus in petrol_groups_new.items():
        parameters['nb_unique'].add(depot_sku[0])

    # Иницализация переменных задачи

    for depot_sku, skus in petrol_groups_new.items():
        for sku in skus:
            for asu_n in parameters['asu_n_set']:
                for shift in parameters['shifts']:
                    vars['dep'][(depot_sku[0], asu_n[0], asu_n[1], sku, shift)] = \
                        m.binary_var(name='dep_{}_{}_{}_{}_{}'.format(depot_sku[0], asu_n[0], asu_n[1], sku, shift))
                    vars['vol'][(depot_sku[0], asu_n[0], asu_n[1], sku, shift)] = \
                        m.integer_var(name='vol_{}_{}_{}_{}_{}'.format(depot_sku[0], asu_n[0], asu_n[1], sku, shift))
                    vars['delta'][(depot_sku[0], asu_n[0], asu_n[1], sku, shift)] = \
                        m.integer_var(name='delta_{}_{}_{}_{}_{}'.format(depot_sku[0], asu_n[0], asu_n[1], sku, shift), lb=0)

    # Заполнение списка резервуаров для каждой из АЗС

    asu_reservoirs_lists = dict()

    for asu in parameters['asu_n_set']:
        if asu[0] in asu_reservoirs_lists:
            asu_reservoirs_lists[asu[0]].append(asu[1])
        else:
            asu_reservoirs_lists[asu[0]] = [asu[1]]

    for nb in parameters['nb_unique']:
        for asu in parameters['asu_n_set']:
            vars['connection'][(nb, asu[0], asu[1])] = \
                m.binary_var(name='conn_{}_{}_{}'.format(nb, asu[0], asu[1]))

    for nb in parameters['nb_unique']:
        for asu in parameters['asu_set']:
            vars['is_nb_connected'][(nb, asu)] = \
                m.binary_var(name='is_nb_connected_{}_{}'.format(nb, asu))

    for asu in parameters['asu_set']:
        vars['n_nb_connected'][asu] = m.integer_var(name='n_nb_connected_{}'.format(asu), lb=0, ub=2)

    # Подготовка данных по существующим привязкам для ограничений 12

    if 'used_reallocation' in conf:
        ITERATIVE_MODE = True
    
    if ITERATIVE_MODE:
        already_reallocated_reservoirs = conf['used_reallocation']

    # Построение ограничения 1
    # Общий поставленный объём на каждый из резервуаров АЗС должно превышать
    # запрос АЗС на этот резервуар для каждой из смен

    print("Построение ограничений (1)")

    for asu_n in parameters['asu_n_set']:
        for sku in parameters['sku_set']:
            for shift in parameters['shifts']:
                m.add_constraint_(ct=sum(vars['vol'][(depot_sku[0], asu_n[0], asu_n[1], sku, shift)] for depot_sku, skus in petrol_groups_new.items() if sku in skus) +
                                     sum(vars['delta'][(depot_sku[0], asu_n[0], asu_n[1], sku, shift)] for depot_sku, skus in petrol_groups_new.items() if sku in skus) 
                                     >=
                                     get_required_volume(asu_n, sku, shift),
                                     ctname='station_import_constraint_{}_{}_{}_{}'.format(asu_n[0], asu_n[1], sku, shift))

    # Построение ограничения 2
    # Общий поставленный объём по sku на АЗС хотя бы на одну секцию.

    print("Построение ограничений (2)")
    for asu_n in parameters['asu_n_set']:
        for sku in parameters['sku_set']:
            for shift in parameters['shifts']:
                for depot_sku, skus in petrol_groups_new.items():
                    if sku in skus:
                        m.add_constraint_(ct=vars['vol'][(depot_sku[0], asu_n[0], asu_n[1], sku, shift)]
                                            >=
                                            vars['dep'][(depot_sku[0], asu_n[0], asu_n[1], sku, shift)] * global_params.asu_vehicle_avg_section[asu_n[0]],
                                        ctname='station_import_constraint_{}_{}_{}_{}'.format(asu_n[0], asu_n[1], sku, shift))

    # Построение ограничения 3
    # Суммарный привезенный объём должен поместиться в выделенные машины для
    # каждой из смен

    print("Построение ограничений (3)")
    for asu in parameters['asu_set']:
        for shift in parameters['shifts']:
            m.add_constraint_(
                ct=sum(vars['vol'][(depot_sku[0], asu_n[0], asu_n[1], sku, shift)]
                       for asu_n in parameters['asu_n_set']
                       if asu_n[0] == asu
                       for sku in parameters['sku_set']
                       for depot_sku, skus in petrol_groups_new.items() if sku in skus) <= get_number_of_trips(asu, shift) * global_params.asu_vehicle_avg_volume[asu],
                ctname='departure_vol_in_trips_constraint_{}_{}'.format(asu, shift))

    # Построение ограничения 4
    # Связь переменных vol и dep. Если vol > 0 => dep = 1

    print("Построение ограничений (4)")

    for asu_n in parameters['asu_n_set']:
        for sku in parameters['sku_set']:
            for shift in parameters['shifts']:
                for depot_sku, skus in petrol_groups_new.items():
                    if sku in skus:
                        m.add_if_then(if_ct=vars['vol'][(depot_sku[0], asu_n[0], asu_n[1], sku, shift)] >= 1,
                                        then_ct=vars['dep'][(depot_sku[0], asu_n[0], asu_n[1], sku, shift)] == 1)

                        m.add_if_then(if_ct=vars['vol'][(depot_sku[0], asu_n[0], asu_n[1], sku, shift)] == 0,
                                        then_ct=vars['dep'][(depot_sku[0], asu_n[0], asu_n[1], sku, shift)] == 0)

    # Построение ограничения 5
    # Ограничение отправлений привязкой резервуара к НБ. Резервуар, который
    # не привязан к НБ не может принять топливо от этой НБ.

    print("Построение ограничений (5)")
    for asu_n in parameters['asu_n_set']:
        for sku in parameters['sku_set']:
            for shift in parameters['shifts']:
                for depot_sku, skus in petrol_groups_new.items():
                    if sku in skus:
                        m.add_constraint_(
                            ct=vars['dep'][(depot_sku[0], asu_n[0], asu_n[1], sku, shift)] <= vars['connection'][(depot_sku[0], asu_n[0], asu_n[1])],
                            ctname='connection_definition_{}_{}_{}_{}_{}'.format(depot_sku[0], asu_n[0], asu_n[1], sku, shift)
                        )

    # Построение ограничения 6
    # Резервуар может быть привязан только к одной НБ

    print("Построение ограничений (6)")
    for asu in parameters['asu_n_set']:
        m.add_constraint_(
            ct=sum(vars['connection'][(nb, asu[0], asu[1])]
                   for nb in parameters['nb_unique']) == 1,
            ctname='only_one_reservoir_is_connected_to_asu_{}_{}'.format(asu[0], asu[1])
        )

    # Построение ограничения 7
    # Введение коэффициента выравнивания (выровнять заезды на НБ для уменьшения
    # вероятности очередей)

    # TODO Исправить 5.0 на значение из входных данных

    print("Построение ограничений (7)")
    for shift in parameters['shifts']:
        vars['queue'][shift] = m.integer_var(name='max_q_{}'.format(shift))
        for depot_sku, skus in petrol_groups_new.items():
            m.add_constraint_(
                sum(vars['dep'][(depot_sku[0], asu_n[0], asu_n[1], sku, shift)]
                    for asu_n in parameters['asu_n_set']
                    for sku in parameters['sku_set'] if sku in skus) / 5.0
                <=
                vars['queue'][shift]
            )

    if parameters['night_mode']:
        # Построение ограничения 8
        # Объём поставок для приоритетных резервуаров не должен превышать
        # открытия первого дня планирования

        print("Построение ограничений (8)")
        for depot_sku, skus in petrol_groups_new.items():
            m.add_constraint(ct=sum(vars['vol'][(depot_sku[0], asu_n[0], asu_n[1], sku, shift)]
                                    for asu_n in parameters['asu_n_set'] if (asu_n[0], asu_n[1]) in parameters['priority']
                                    for shift in parameters['shifts']
                                    for sku in skus)
                            <=
                            get_rest_nb(depot_sku[0], depot_sku[1], conf['current_shift_id'], True),
                            ctname='depot_export_constraint_prioritized_{}_{}'.format(depot_sku[0], depot_sku[1])
                            )

        # Построение ограничения 8+
        # Потребление каждого типа топлива в сумме за две смены не должно
        # превышать объёмов открытия на НБ

        print("Построение ограничений (8+)")
        for depot_sku, skus in petrol_groups_new.items():
            m.add_constraint(
                ct=sum(vars['vol'][(depot_sku[0], asu_n[0], asu_n[1], sku, shift)]
                    for asu_n in parameters['asu_n_set']
                    for shift in parameters['shifts']
                    for sku in skus if sku in parameters['sku_set'])
                <=
                get_rest_nb(depot_sku[0], depot_sku[1], conf['current_shift_id'], False),
                ctname='depot_export_constraint_total_{}_{}'.format(depot_sku[0], depot_sku[1])
            )

    else:
        # Построение ограничения 8
        # Потребление каждого типа топлива в сумме за две смены не должно превышать объёмов
        # открытия на НБ
        
        print("Построение ограничений (8)")
        
        for depot_sku, skus in petrol_groups_new.items():
            m.add_constraint(
                ct=sum(vars['vol'][(depot_sku[0], asu_n[0], asu_n[1], sku, shift)]
                    for asu_n in parameters['asu_n_set']
                    for shift in parameters['shifts']
                    for sku in skus if sku in parameters['sku_set'])
                <=
                get_rest_nb(depot_sku[0], depot_sku[1], conf['current_shift_id']),
                ctname='depot_export_constraint_total_{}_{}'.format(depot_sku[0], depot_sku[1])
            )

    # Построение ограничения 9
    # Считаем переменные is_nb_connected - индикатор, показывающий, привязана ли
    # нефтебаза к азс (в целом) - не к резервуару

    print("Построение ограничений (9)")
    for nb in parameters['nb_unique']:
        for asu in parameters['asu_set']:
            m.add_constraint_(
                ct=vars['is_nb_connected'][(nb, asu)] 
                ==
                m.max(vars['connection'][(nb, asu, n)] for n in asu_reservoirs_lists[asu]),
                ctname='get_if_asu_connected_to_nb_{}_{}'.format(nb, asu)
            )

    # Построение ограничения 10
    # Связь переменных is_nb_connected и n_nb_connected

    print("Построение ограничений (10)")
    for asu in parameters['asu_set']:
        m.add_constraint_(
            ct=vars['n_nb_connected'][asu]
            ==
            m.sum(vars['is_nb_connected'][nb, asu] for nb in parameters['nb_unique']),
            ctname="sum_of_connected_nb_to_asu_{}".format(asu)
        )

    # Построение ограничения 11
    # Фиксирование привязок, которые ранее были осуществлены (итеративная модель)

    if ITERATIVE_MODE:
        print("Построение ограничений (11)")
        for key, value in already_reallocated_reservoirs.items():
            if (int(value), key[0], key[1]) in vars['connection']:
                m.add_constraint_(ct=vars['connection'][(int(value), key[0], key[1])]
                                  ==
                                  1,
                                  ctname="arleady_connected_reservoirs_{}_{}_{}".format(key[0], key[1], value))

    # Построение целевой функции
    # Добавление части целевой функции, которая отвечает за минимизацию отклонения доставки от плана

    print("Построение целевой функции")
    number_of_objective_elements = 3
    objective = {idx: dict() for idx in range(1, number_of_objective_elements + 1)}

    objective[1]['function'] = sum(vars['delta'][(depot_sku[0], asu_n[0], asu_n[1], sku, shift)]
                                   for asu_n in parameters['asu_n_set']
                                   for shift in parameters['shifts']
                                   for depot_sku, skus in petrol_groups_new.items()
                                   for sku in parameters['sku_set'] if sku in skus)

    # Добавление части целевой функции, которая минимизирует суммарный
    # прогон БВ на АЗС с НБ

    objective[2]['function'] = sum(vars['is_nb_connected'][(nb, asu)] * (distances[(nb, asu)] + distances[(asu, nb)])
                      for nb in parameters['nb_unique']
                      for asu in parameters['asu_set'])

    # Добавление части целевой функции, которая выравнивает количество заездов 
    # на НБ с учётом очередей и вместимости НБ

    objective[3]['function'] = sum(vars['queue'][shift] for shift in parameters['shifts'])

    # Веса целевых функций

    objective[1]['weight'] = 1.0
    objective[2]['weight'] = 1.0
    objective[3]['weight'] = 1.0

    # Сохраняем целевую функцию в модель
    m.minimize(sum(objective[idx]['function'] * objective[idx]['weight']
                   for idx in objective.keys()))

    # Сохраняем модель в файл
    if not os.path.exists('logs/'):
        os.makedirs('logs/')

    m.export_as_lp('logs/asu_nb_connecting_model.lp')

    # Поиск решения
    m.log_output = True

    m.parameters.timelimit = 60

    m.solve()

    result_connecting = dict()
    result_volumes = dict()

    # Сбор результатов
    for key, val in vars['connection'].items():
        if val.solution_value:
            result_connecting[key[1], key[2]] = key[0]

    for key, val in vars['vol'].items():
        if val.solution_value:
            result_volumes[key] = val.solution_value

    return result_connecting, result_volumes
