"""Главный модуль перепривязки резервуаров АЗС к НБ
"""

from copy import deepcopy

from asu_nb_connecting.data_builder import prepare_data_from_sources
from asu_nb_connecting.math_model import gpn_asu_nb_connecting
from data_reader.input_data import get_distance
import pandas as pd


def collect_links(volumes, result, day):
    """Функция для сбора связей из результатов расчёта и формирование выходных
    данных в требуемом формате
    """
    res = dict()
    uniq = set()
    for el in volumes:
        res[(el['id_asu'], el['n'], day)] = result[el['id_asu'], el['n']]
        uniq.add(el['id_asu'])

    return res, list(uniq)


def calculate(conf, data, output_states_collection):
    """Функция для запуска расчёта и возврата результатов перепривязок
    """

    conf['day'] = (conf['current_shift_id'] + 1) // 2

    # result - структура данных для хранения результата расчёта

    result = {'connected': dict(),
              'changed_asu': {conf['day'] * 2 - 1: set(), conf['day'] * 2: set()}}

    # Подготовка данных для осуществления расчёта с помощью prepare_data_from_sources

    _data = prepare_data_from_sources(conf, output_states_collection, data)

    parameters = _data[2]

    # Расчёт перепривязок с использованием мат. модели

    math_connecting_results, volume_results = gpn_asu_nb_connecting(*_data, global_params=data, conf=conf)

    # Сбор результатов в единый словарь с данными

    for shift in parameters['shifts']:
        links, changed_asu = collect_links(_data[0], math_connecting_results, shift)

        result['connected'].update(links)
        result['changed_asu'][shift] = changed_asu
        result['volumes'] = volume_results

    result['period'] = list(parameters['shifts'])

    # (Дополнительно) Формирование в словаре результатов аналога asu_depots

    result['already_reallocated'] = {}
    result['asu_depot'] = {}

    for key, val in result['connected'].items():
        if key[0] not in result['already_reallocated']:
            result['asu_depot'][key[0]] = val
            result['already_reallocated'][key[0]] = True
        else:
            if not result['already_reallocated'][key[0]]:
                result['asu_depot'][key[0]] = val
                result['already_reallocated'][key[0]] = True

    del result['already_reallocated']

    # Заполняем также asu_nb_connecting_result информацией о резервуарах, которые
    # не рассматривались в модели (дополнительное требование)

    reservoirs_number = len(data.tanks)

    for record_id in range(0, reservoirs_number):
        asu_id = data.tanks.at[record_id, 'asu_id']
        n = data.tanks.at[record_id, 'n']

        to_add_this_reservoir = False
        for shift in parameters['shifts']:
            if asu_id in result['changed_asu'][shift]:
                to_add_this_reservoir = True
            if to_add_this_reservoir:
                for time in parameters['shifts']:
                    if (asu_id, n, time) not in result['connected']:
                        idx = (asu_id, n, time)
                        current_depot = result['asu_depot'][asu_id]
                        result['connected'][idx] = current_depot

    # Добавляем в результат также информацию о фиксированных привязках

    if 'used_reallocation' in conf:
        result['used_reallocation'] = conf['used_reallocation']

    # Возвращаем результат

    return result


def depot_correction(depot_id, data, sku, asu_id):
    """
    Функция корректировки привязки Резервуар АЗС - НБ
    Проблема, которую решает настоящая функция - привязка к НБ, где тип НП отсутствует.
    :param depot_id: идентификатор НБ
    :param data: входные данные
    :param sku: Тип НП
    :param asu_id: Номер АЗС
    :return: depot_id
    """
    "Расстояние от НБ до АЗС"
    depots_allowed = {}
    if (depot_id, sku) in data.fuel_in_depot_inverse or not pd.isnull(depot_id):
        return depot_id
    else:
        for depot_new in data.depot_capacity:
            if (depot_new, sku) in data.fuel_in_depot_inverse:
                depots_allowed[depot_new] = get_distance(depot_new, asu_id, data.distances_asu_depot)

        if not depots_allowed:
            print('Нет типа топлива %d на АЗС %d' % (sku, asu_id))
        return min(depots_allowed, key=depots_allowed.get)


def update_integral_output(flow_data, departures_data, departures_dict, asu_nb_connecting_result, data, update_departures=False):
    """Функция для обновления результатов интегральной модели на основе результата
    работы алгоритма перепривязки резервуаров АЗС к НБ. Обновляются данные
    flow_data, departures_data, departures_dict
    """
    flow_data_copy = deepcopy(flow_data)
    departures_data_copy = deepcopy(departures_data)
    departures_dict_copy = deepcopy(departures_dict)

    # Подготовим список уникальных значений по фиксированным привязкам
    already_reallocated_asu = set()

    if 'used_reallocation' in asu_nb_connecting_result.keys():
        fixed_reallocations = asu_nb_connecting_result['used_reallocation']
        for key in fixed_reallocations.keys():
            already_reallocated_asu.add(int(key[0]))

    # Обновление данных по нефтебазам flow_data

    records_number = len(flow_data_copy)

    for line_id in range(0, records_number):
        id_asu = int(flow_data_copy.iloc[line_id]['id_asu'])
        n = int(flow_data_copy.iloc[line_id]['n'])
        time = int(flow_data_copy.iloc[line_id]['time'])
        sku = int(flow_data_copy.iloc[line_id]['sku'])

        if (id_asu, n, time) in asu_nb_connecting_result['connected']:
            flow_data_copy.at[line_id, 'depot'] = int(asu_nb_connecting_result['connected'][(id_asu, n, time)])

        depot = int(flow_data_copy.iloc[line_id]['depot'])

        idx = (depot, id_asu, n, sku, time)

        if idx in asu_nb_connecting_result['volumes']:
            flow_data_copy.at[line_id, 'volume'] = asu_nb_connecting_result['volumes'][idx]

    for line_id in range(0, records_number):
        sku = int(flow_data_copy.iloc[line_id]['sku'])
        id_asu = int(flow_data_copy.iloc[line_id]['id_asu'])
        depot = int(flow_data_copy.iloc[line_id]['depot'])

        if not depot or pd.isnull(depot):
            depot_id = depot_correction(data.asu_depot[id_asu], data, sku, id_asu)
            flow_data_copy.at[line_id, 'depot'] = depot_id


    # Обновление данных по выездам departures_data
    # TODO Решить вопрос от Алексея по двойным рейсам

    records_number = len(departures_data_copy)
    records_number_at_flow_data = len(flow_data_copy)

    for line_id in range(0, records_number):
        time = departures_data_copy.loc[line_id, 'time']
        asu_id = departures_data_copy.loc[line_id, 'id_asu']
        sku = int(flow_data_copy.iloc[line_id]['sku'])

        set_of_unique_depots = set()

        filtered_df = flow_data_copy.loc[flow_data_copy['id_asu'] == asu_id, ['depot']].loc[flow_data_copy['time'] == time]
        list_of_unique_depots = filtered_df.drop_duplicates().values.tolist()
        flattened_list = [y for x in list_of_unique_depots for y in x]
        set_of_unique_depots = set(flattened_list)

        if len(set_of_unique_depots) > 1 and int(departures_data_copy.at[line_id, 'departures']) == 1:
            if int(asu_id) not in already_reallocated_asu:
                if update_departures:
                    departures_data_copy.at[line_id, 'departures'] = 2
                    departures_dict[(asu_id, time)] = 2

        depot = int(departures_data_copy.iloc[line_id]['depots'])
        if not depot or pd.isnull(depot):
            id_asu = int(departures_data_copy.iloc[line_id]['id_asu'])
            depot_id = depot_correction(data.asu_depot[id_asu], data, sku, id_asu)
            departures_data_copy.at[line_id, 'depots'] = depot_id


    # Обновление данных по выездам в departures_dict

    records_number = len(departures_data_copy)

    for line_id in range(0, records_number):
        id_asu = int(departures_data_copy.iloc[line_id]['id_asu'])
        time = int(departures_data_copy.iloc[line_id]['time'])
        number_of_trips = int(departures_data_copy.iloc[line_id]['departures'])

        if (id_asu, time) in departures_dict_copy:
            departures_dict_copy[(id_asu, time)] = number_of_trips

    return flow_data_copy, departures_data_copy, departures_dict_copy


def update_static_data(data, asu_nb_connecting_result):
    """Функция для обновления Static Data на основе результата работы алгоритма
    перепривязки резервуаров АЗС к НБ
    """

    for key, val in asu_nb_connecting_result['connected'].items():
        for _key in data.asu_depot_reallocation.keys():
            if key[0] == _key[0] and key[2] == _key[2] and key[1] == _key[1]:
                data.asu_depot_reallocation[_key] = val

    for key, val in asu_nb_connecting_result['connected'].items():
        if key not in data.asu_depot_reallocation.keys():
            data.asu_depot_reallocation[key] = val

    data.asu_reallocated.update(asu_nb_connecting_result['changed_asu'])

    # Перепривязка происходит только в случае, если раньше этого не произошло

    for key, val in asu_nb_connecting_result['connected'].items():
            data.asu_depot[key[0]] = val
            data.is_asu_depot_already_reallocated[key[0]] = True
