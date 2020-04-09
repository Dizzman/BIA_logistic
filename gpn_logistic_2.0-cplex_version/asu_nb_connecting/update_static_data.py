"""Модуль содержит функцию для обновления объекта Static Data перед осуществлением
расчёта перепривязок
"""

from statistics import mean


def update_static_data(data):
    """Функция для обновления объекта Static Data перед осуществлением
    расчёта перепривязок
    """

    # Идентификатор фиктивной НБ

    f_id = 0

    # Выбираем уникальные имена

    unique_asu_depot_names = set()
    unique_uet_names = set()

    # Формируем списки уникальных значений

    for key in data.distances_asu_depot.keys():
        unique_asu_depot_names.add(key[0])
        unique_asu_depot_names.add(key[1])

    for key in data.distances_asu_uet.keys():
        if 'uet' in str(key[0]):
            unique_uet_names.add(key[0])
        if 'uet' in str(key[1]):
            unique_uet_names.add(key[1])

    # Формируем обновленные расстояния между фиктивной НБ и остальными объектами

    for el in unique_asu_depot_names:
        forward_distances = [data.distances_asu_depot[key] for key in data.distances_asu_depot.keys() 
            if int(key[1]) == el and key[0] != f_id and key[0] < 10000]
        backward_distances = [data.distances_asu_depot[key] for key in data.distances_asu_depot.keys() 
            if key[0] == el and key[1] != f_id and key[1] < 10000]

        if len(forward_distances):
            data.distances_asu_depot[(f_id, el)] = mean(forward_distances)
        else:
            data.distances_asu_depot[(f_id, el)] = 10000

        if len(backward_distances):    
            data.distances_asu_depot[(el, f_id)] = mean(backward_distances)
        else:
            data.distances_asu_depot[(el, f_id)] = 10000

    for el in unique_uet_names:
        sum_forward = sum(data.distances_asu_uet[key]
                          for key in data.distances_asu_uet.keys()
                          if str(key[0]) == el and len(str(key[1])) == 1 and str(key[1]) != str(f_id))

        sum_backward = sum(data.distances_asu_uet[key]
                           for key in data.distances_asu_uet.keys()
                           if str(key[1]) == el and len(str(key[0])) == 1 and str(key[0]) != str(f_id))

        num_forward = len([data.distances_asu_uet[key]
                           for key in data.distances_asu_uet.keys()
                           if str(key[0]) == el and len(str(key[1])) == 1 and str(key[1]) != str(f_id)])

        num_backward = len([data.distances_asu_uet[key]
                            for key in data.distances_asu_uet.keys()
                            if str(key[1]) == el and len(str(key[0])) == 1 and str(key[0]) != str(f_id)])

        if num_backward != 0 and sum_backward != 0:
            data.distances_asu_uet[(el, f_id)] = sum_backward / num_backward
            data.distances_asu_uet[(f_id, el)] = sum_backward / num_backward

        if num_forward != 0 and sum_forward != 0:
            data.distances_asu_uet[(el, f_id)] = sum_forward / num_forward
            data.distances_asu_uet[(f_id, el)] = sum_forward / num_forward

    # Модифицируем словарь asu_depot_reallocation

    for key, val in data.asu_depot_reallocation.items():
        data.asu_depot_reallocation[key] = f_id

    for idx in range(len(data.tanks)):
        data.tanks.at[idx, 'depot_id'] = f_id

    for idx in range(len(data.tanks)):
        asu_id = int(data.tanks.at[idx, 'asu_id'])
        n = int(data.tanks.at[idx, 'n'])
        depot_id = int(data.tanks.at[idx, 'depot_id'])
        for t in range(0, 29):
            key = (asu_id, n, t)
            if key not in data.asu_depot_reallocation or not depot_id:
                data.asu_depot_reallocation[key] = f_id

    # Модифицируем словарь depot_work_shift

    data.depot_work_shift[0] = {}
    data.depot_work_shift[0][1] = 1
    data.depot_work_shift[0][2] = 1

    # Обновление ограничений по открытиям (новая версия)

    _new_restrinctions_set = {}

    unique_shifts = set()

    for key in data.restricts.keys():
        unique_shifts.add(key[2])

    for shift in unique_shifts:
        for key, item in data.groups_for_openings_sum.items():
            current_shift = shift
            current_group_id = key
            current_depot_id = 0

            opening_key = (current_depot_id, current_group_id, current_shift)
            opening_volume = 0

            for connection in item['connected_openings']:
                depot = connection[0]
                sku = connection[1]

                if (depot, sku, shift) in data.restricts:
                    opening_volume += data.restricts[(depot, sku, shift)]
                elif (depot, sku) in data.fuel_in_depot:  # TODO хакнул, нужно сделать отсутствие значения (c) Lexa
                    opening_volume += 10 ** 10

            _new_restrinctions_set[opening_key] = opening_volume

    data.restricts = _new_restrinctions_set

    # Обновление data.fuel_in_depot

    print(data.groups_for_openings_sum)

    data.fuel_in_depot = {}

    for key in data.groups_for_openings_sum.keys():
        data.fuel_in_depot[(0, key)] = data.groups_for_openings_sum[(key)]['sku_merged']
    print(data.fuel_in_depot_inverse)

    data.fuel_in_depot_inverse = {}

    for key in data.groups_for_openings_sum.keys():
        for el in data.groups_for_openings_sum[key]['sku_merged']:
            data.fuel_in_depot_inverse[(0, el)] = key