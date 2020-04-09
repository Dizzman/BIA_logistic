import pandas as pd

def check_if_data_is_complete(distances, parameters):
    """Функция для проверки, все ли расстояния между АЗС и НБ имеются
    во входном файле. В случае отсутствия элемента в матрице
    работа программы будет приостановлена.
    :param distances: Матрица расстоний.
    :param parameters: Словарь (dict) с параметрами.
    :return: None
    """
    for depot in parameters['nb_unique']:
        for asu_id in parameters['asu_set']:
            try:
                a = distances[(asu_id, depot)]
                a = distances[(depot, asu_id)]
            except:
                print("Во входном файле недостаточно данных (матрица расстояний). от " + str(asu_id) + " до " + str(depot))
                exit(1)


def prepare_data_from_sources(conf, output_states_collection, data):
    """Функция для подготовки данных к подаче в алгоритм назначения
    :param conf: Словарь (dict) с параметрами.
    :return: volumes, departures, parameters, distances - словари подготовленных
    к работе модели данных.
    """

    # Инициализация

    volumes = list()
    departures = list()
    parameters = dict()
    asu_set = set()
    sku_set = set()
    distances = dict()
    asu_n_set = set()

    # Рассматриваемые смены

    parameters['shifts'] = set()
    current_shift_id = conf['current_shift_id']
    next_shift_id = current_shift_id + 1

    parameters['shifts'].add(current_shift_id)
    parameters['shifts'].add(next_shift_id)

    # Заполнение матрицы расстояний (distances) из данных StaticData

    for key, value in data.distances_asu_depot.items():
        from_point = int(key[0])
        to_point = int(key[1])
        dist = float(value)
        distances[(from_point, to_point)] = dist

    # Заполнение данных о спросе на АЗС из данных flow_data

    prioritized_asu_n = set()

    flow_volumes = conf['flow_data']

    for idx in flow_volumes.index:
        if int(flow_volumes['time'][idx]) in parameters['shifts']:
            volumes.append({'id_asu': int(flow_volumes['id_asu'][idx]),
                            'n': int(flow_volumes['n'][idx]),
                            'sku': int(flow_volumes['sku'][idx]),
                            'time': int(flow_volumes['time'][idx]),
                            'volume': float(flow_volumes['volume'][idx])})

            time_to_death = output_states_collection.get_time_to_death(
                int(flow_volumes['time'][idx]) - 1,
                int(flow_volumes['id_asu'][idx]),
                int(flow_volumes['n'][idx]))

            # Выделение АЗС, на которые поставка осуществляется в рамках текущего открытия
            # (те, что просыхают или закрыты в следующую)

            if time_to_death <= 0.5 and time_to_death != 0:
                prioritized_asu_n.add((int(flow_volumes['id_asu'][idx]),
                                       int(flow_volumes['n'][idx])))

            if time_to_death <= 1.0 and time_to_death != 0 and \
                    data.asu_work_shift[int(flow_volumes['id_asu'][idx])][1 if (int(flow_volumes['time'][idx]) + 1) % 2 == 1 else 2] == 0:
                prioritized_asu_n.add((int(flow_volumes['id_asu'][idx]),
                                       int(flow_volumes['n'][idx])))

            asu_set.add(int(flow_volumes['id_asu'][idx]))
            sku_set.add(int(flow_volumes['sku'][idx]))
            asu_n_set.add((int(flow_volumes['id_asu'][idx]), int(flow_volumes['n'][idx])))

    # Заполнение данных об отправлениях на основе информации о departures_data

    departures_data = conf['departures_data']
    
    for idx in departures_data.index:
        if int(departures_data['time'][idx]) in parameters['shifts']:
            departures.append(
                {
                    'id_asu': int(departures_data['id_asu'][idx]),
                    'time': int(departures_data['time'][idx]),
                    'departures': int(departures_data['departures'][idx])
                }
            )

    # Создание списков уникальных элементов для дальнейшей работы

    parameters['nb_set'] = []
    parameters['nb_unique'] = set()
    parameters['sku_set'] = sku_set

    # Заполнение данных о НБ на основе информации о depots restricts в Static Data

    for key, value in data.restricts.items():
        temp = {
            'id': int(key[0]),
            'avail': int(value),
            'sku': int(key[1]),
            'day': int(key[2])
        }
        parameters['nb_set'].append(temp)
        parameters['nb_unique'].add(temp['id'])


    # Подготовка списка уникальных НБ на основе данных о depots в Static Data

    for key in data.depot_names_dict.keys():
        parameters['nb_unique'].add(key)

    parameters['shift_number'] = conf['day']
    parameters['asu_set'] = asu_set
    parameters['asu_n_set'] = asu_n_set
    parameters['priority'] = prioritized_asu_n

    parameters['night_mode'] = False

    if not current_shift_id % 2:
        parameters['night_mode'] = True

    # Проверка на полноту матрицы расстояний

    check_if_data_is_complete(distances, parameters)

    return volumes, departures, parameters, distances
