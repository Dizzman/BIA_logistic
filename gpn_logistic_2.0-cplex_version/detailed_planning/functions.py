from data_reader.input_data import StaticData
from detailed_planning.dp_parameters import DParameters
from integral_planning.functions import day_calculation_by_shift
import asu_nb_connecting.asu_nb_connection as asu_nb_connection
import pandas as pd
from collections import namedtuple


"""Get allocated depot for set of tanks"""


def get_depot_allocation(set_asu, data: StaticData, dp_parameters: DParameters):
    """Get current depot for first asu_id. Assumed, that all asu in set_asu has same depot allocation"""

    depot_current = data.asu_depot[dp_parameters.asu_decoder(set_asu[0])]
    day = day_calculation_by_shift(dp_parameters.time)

    for asu_id in set_asu:
        if asu_id in data.asu_reallocated[dp_parameters.time]:
            load_info = dp_parameters.load_info[asu_id]  # TODO Зависит от баков в машине, а не всех баков
            for asu_id_new, n in load_info:
                new_depot = data.asu_depot_reallocation[dp_parameters.asu_decoder(asu_id), n, dp_parameters.time]
                if new_depot != depot_current:
                    # print('Depot allocation changed: ' + str(set_asu) + ' to %d' % new_depot)
                    return new_depot

    return depot_current


def calculate_time_to_death(asu, dp_parameters: DParameters, data: StaticData):
    shift_number = 2 - dp_parameters.time % 2
    real_asu = dp_parameters.asu_decoder(asu)

    days_to_death = min([dp_parameters.asu_tank_death[real_asu, n]
                         for asu, n in dp_parameters.load_info.get(asu, {})
                         if dp_parameters.load_info[asu][asu, n][0]], default=99)

    moving_correction = 0.5 * (data.trip_duration(real_asu) // dp_parameters.shift_size) + \
                        0.25 * ((data.trip_duration(real_asu) % dp_parameters.shift_size) / dp_parameters.shift_size)

    if data.asu_work_time[real_asu][shift_number]:
        asu_window = data.asu_work_time[real_asu][shift_number]
        moving_correction = max(moving_correction, 0.5 * asu_window[0] / dp_parameters.shift_size)
    else:
        asu_window = data.asu_work_time[real_asu][3 - shift_number]
        moving_correction = max(moving_correction, 0.5 * (asu_window[0] / dp_parameters.shift_size + 1))

    days_to_death -= moving_correction

    return days_to_death


def sort_asu_by_death(dp_parameters: DParameters, data: StaticData):
    """
    :param dp_parameters: DParameters
    :param data: StaticData
    :return: [asu1, asu2, ...] --- sorted asu by death
    """
    asu_death_dict = dict()
    for asu in dp_parameters.load_info:
        days_to_death = calculate_time_to_death(asu, dp_parameters, data)
        asu_death_dict[asu] = days_to_death - 0.5 * (
            1 if data.asu_work_shift[dp_parameters.asu_decoder(asu)][dp_parameters.time % 2 + 1] == 0 else 0) + \
                              (0.01 if asu in dp_parameters.encoder_decoder and asu // 10000000 > 1 else 0)

    return sorted(asu_death_dict, key=asu_death_dict.get)


def split_asu(ordered_asu: list, dp_parameters: DParameters):
    """
    :param ordered_asu: ordered_asu_list
    :param dp_parameters: dp_parameters.fragmentation_size group_size
    :return: [[asu1, asu_2, ...], [ ...] ]
    """
    clone_object = ordered_asu[:]
    current_set = []
    next_set = []
    result = []
    for idx, val in enumerate(clone_object):
        if dp_parameters.asu_decoder(val) in [dp_parameters.asu_decoder(el) for el in current_set]:
            next_set.append(val)
        else:
            current_set.append(val)

        if len(current_set) >= dp_parameters.fragmentation_size or val == clone_object[-1]:
            result.append(current_set[:])
            new_current_set = next_set[:]
            next_set = []
            current_set = []
            "Проверка на дубли АЗС в следующей группе"
            for _val in new_current_set:
                if dp_parameters.asu_decoder(_val) in [dp_parameters.asu_decoder(el) for el in current_set]:
                    next_set.append(_val)
                else:
                    current_set.append(_val)

    # result = []
    # while len(clone_object) > dp_parameters.fragmentation_size:
    #     pice = clone_object[:dp_parameters.fragmentation_size]
    #     result.append(pice)
    #     clone_object = clone_object[dp_parameters.fragmentation_size:]
    # result.append(clone_object)
    return result


# Run reallocation planning
def depot_allocation_treat(flow_data, departures_data, departures_dict, shift, data,
                           output_states_collection, used_reallocations):

    # Подготовка параметров для модели назначения АЗС

    h_params = {'flow_data': flow_data,
                'departures_data': departures_data,
                'departures_dict': departures_dict,
                'current_shift_id': shift,
                'used_reallocation': used_reallocations}

    # Запуск модели перепривязки АЗС. Получение результата

    asu_nb_connecting_result = asu_nb_connection.calculate(
        h_params, data, output_states_collection=output_states_collection)

    # Обновляем привязки в static data

    asu_nb_connection.update_static_data(data, asu_nb_connecting_result)

    # Обновляем результат интегральной модели для учёта перепривязки

    u_flow_data, u_departures_data, u_departures_dict = \
        asu_nb_connection.update_integral_output(flow_data, departures_data, departures_dict, asu_nb_connecting_result, data)

    return u_flow_data, u_departures_data, u_departures_dict


def update_depot_restr_iter(result_trip_optimization: namedtuple, data: StaticData, dp_parameters: DParameters):
    for asu, truck_num in result_trip_optimization.set_direct:
        loads_sequence = dp_parameters.truck_load_sequence[truck_num, (asu,)]
        loads = dp_parameters.truck_load_volumes[truck_num, (asu,)]
        for idx, asu_n in enumerate(loads_sequence):
            sku = data.tank_sku[asu_n]
            depot = data.asu_depot_reallocation[asu_n]
            depot_sku = data.fuel_in_depot_inverse.get((depot, sku), None)
            shift = (dp_parameters.time + 1) // 2  # TODO ночная смена - следующие открытия ?
            if depot_sku and (depot, depot_sku, shift) in data.restricts:
                data.restricts[depot, depot_sku, shift] -= loads[idx]

    for asu1, asu2, truck_num in result_trip_optimization.set_distribution:
        loads_sequence = dp_parameters.truck_load_sequence[truck_num, (asu1, asu2)]
        loads = dp_parameters.truck_load_volumes[truck_num, (asu1, asu2)]
        for idx, asu_n in enumerate(loads_sequence):  # TODO should be same allocation
            sku = data.tank_sku[asu_n]
            depot = data.asu_depot_reallocation[asu_n]
            depot_sku = data.fuel_in_depot_inverse.get((depot, sku), None)
            day = (dp_parameters.time + 1) // 2
            if depot_sku and (depot, depot_sku, day) in data.restricts:
                data.restricts[depot, depot_sku, day] -= loads[idx]

    for asu1, asu2, truck_num in result_trip_optimization.set_direct_double:
        for asu in [asu1, asu2]:
            loads_sequence = dp_parameters.truck_load_sequence[truck_num, (asu,)]
            loads = dp_parameters.truck_load_volumes[truck_num, (asu,)]
            for idx, asu_n in enumerate(loads_sequence):
                sku = data.tank_sku[asu_n]
                depot = data.asu_depot_reallocation[asu_n]
                depot_sku = data.fuel_in_depot_inverse.get((depot, sku), None)
                day = (dp_parameters.time + 1) // 2
                if depot_sku and (depot, depot_sku, day) in data.restricts:
                    data.restricts[depot, depot_sku, day] -= loads[idx]

    for asu1, asu2, asu3, truck_num in result_trip_optimization.set_distribution_double:
        for asu in [(asu1, asu2), (asu3,)]:
            loads_sequence = dp_parameters.truck_load_sequence[truck_num, asu]
            loads = dp_parameters.truck_load_volumes[truck_num, asu]
            for idx, asu_n in enumerate(loads_sequence):
                sku = data.tank_sku[asu_n]
                depot = data.asu_depot_reallocation[asu_n]
                depot_sku = data.fuel_in_depot_inverse.get((depot, sku), None)
                day = (dp_parameters.time + 1) // 2
                if depot_sku and (depot, depot_sku, day) in data.restricts:
                    data.restricts[depot, depot_sku, day] -= loads[idx]


def asu_truck_double_probs(truck_routes, asu_set, data: StaticData, dp_parameters: DParameters, any_trip_duration_check):
    count_doubles_by_truck = dict()
    count_doubles = dict()

    for (truck, route) in truck_routes:
        if len(route) == 1:
            asu1 = route[0]
            for asu2 in asu_set:
                if asu2 != asu1:
                    trip_route = ((asu1,), (asu2,))
                    is_possible_route, _ = \
                        any_trip_duration_check(data, dp_parameters, truck, *trip_route, is_load=False)

                    if is_possible_route and is_possible_route <= data.parameters.shift_size:
                        count_doubles_by_truck[truck, asu1] = count_doubles_by_truck.get((truck, asu1), 0) + 1
                        count_doubles[asu1] = count_doubles.get(asu1, 0) + 1

    return {(truck, asu1): val / count_doubles[asu1] for (truck, asu1), val in count_doubles_by_truck.items()}


def get_result_sets(result_tuples):
    set_direct, set_distribution, set_direct_double, set_distribution_double, depot_queue = {}, {}, {}, {}, []

    for iteration, result in result_tuples.items():
        set_direct.update(result.set_direct)
        set_distribution.update(result.set_distribution)
        set_direct_double.update(result.set_direct_double)
        set_distribution_double.update(result.set_distribution_double)
        depot_queue.extend(result.depot_queue)

    return set_direct, set_distribution, set_direct_double, set_distribution_double, depot_queue


def update_truck_trip_amount(truck_trip_dict: dict, trip_optimization):
    for key in trip_optimization.set_direct:
        truck_trip_dict[key[1]] += 1
    for key in trip_optimization.set_distribution:
        truck_trip_dict[key[2]] += 1
    for key in trip_optimization.set_direct_double:
        truck_trip_dict[key[2]] += 2
    for key in trip_optimization.set_distribution_double:
        truck_trip_dict[key[3]] += 2


def trip_union(trips_on_the_truck, truck_asu_iter_type_dict, set_direct, set_distribution, set_direct_double, set_distribution_double):
    filter_trucks_double_trip = [key for key, val in trips_on_the_truck.items() if val >= 2]  # Truck numbers with several trips
    set_dict = {'set_direct': set_direct, 'set_distribution': set_distribution}
    trip_filter = [(route, it, type_dict) for route, it, type_dict in truck_asu_iter_type_dict if route[-1] in filter_trucks_double_trip and
                   type_dict in set_dict]

    double_distribution_double = {}

    for truck in filter_trucks_double_trip:
        route_pair = list((route, it, type_dict) for route, it, type_dict in trip_filter if route[-1] == truck)
        if route_pair:
            route_pair.sort(key=lambda x: -len(x[0]))
            new_route = []
            for (route, it, type_dict) in route_pair:
                print(route)
                new_route.extend(route[:-1])
            new_route.append(truck)
            if len(new_route) == 3:
                set_direct_double[tuple(new_route)] = 1
            elif len(new_route) == 4:
                set_distribution_double[tuple(new_route)] = 1
            else:
                double_distribution_double[tuple(new_route)] = 1
            for (route, it, type_dict) in route_pair:
                set_dict[type_dict].pop(route)

    return double_distribution_double


def filter_integral_model_results(flow_data: pd.DataFrame, departures_dict: dict,
                                  renamed_asu_group: list, dp_parameters: DParameters):
    # Результат интегральной модели обрезается для пакета азс (с учётом splitter в текущую смену).

    asu_group = list(map(dp_parameters.asu_decoder, renamed_asu_group))

    cut_flow_data_array = []
    for index, row in flow_data.iterrows():
        if row['id_asu'] not in asu_group or row['time'] != dp_parameters.time:
            continue
        asu_in_group = [renamed_asu for renamed_asu in renamed_asu_group
                        if dp_parameters.asu_decoder(renamed_asu) == row['id_asu']]
        asu_row = row.copy()
        volume = sum(dp_parameters.load_info[asu][asu, tank][0] for asu in asu_in_group
                     for asu, tank in dp_parameters.load_info[asu] if tank == row['n'])
        if volume:
            asu_row.loc['volume'] = volume
        else:
            continue
        cut_flow_data_array.append(asu_row)
    cut_flow_data = pd.DataFrame(data=cut_flow_data_array, columns=flow_data.columns).reset_index(drop=True)

    cut_departures_dict = {(asu, dp_parameters.time): asu_group.count(asu) for asu in set(asu_group)}

    cut_departures_data = cut_flow_data.filter(['id_asu', 'time']).drop_duplicates()
    cut_departures_data_array = []
    for index, row in cut_departures_data.iterrows():
        asu_row = row.tolist()
        asu_row.append(cut_departures_dict[row['id_asu'], row['time']])
        asu_row.append(0)   # TODO Костыль --- depot в flow_data может быть не уникальный для разных баков
        cut_departures_data_array.append(asu_row)
    cut_departures_data = pd.DataFrame(data=cut_departures_data_array,
                                       columns=['id_asu', 'time', 'departures', 'depots'])

    return cut_flow_data, cut_departures_data, cut_departures_dict


def update_integral_model_results(package_flow_data: pd.DataFrame, package_departures_dict: dict,
                                  flow_data: pd.DataFrame, departures_dict: dict,
                                  renamed_asu_group: list, dp_parameters: DParameters):
    # Результат интегральной модели обрезается по текущую смену, замена для азс из пакета после пересчёта привязок
    asu_group = list(map(dp_parameters.asu_decoder, renamed_asu_group))

    result_departures_dict = {key: val for key, val in departures_dict.items() if key[1] == dp_parameters.time}

    result_flow_data = flow_data[(flow_data['time'] == dp_parameters.time) & (~flow_data['id_asu'].isin(asu_group))]

    for asu in set(asu_group):
        renamed_asu_in_group = [renamed_asu for renamed_asu in renamed_asu_group
                                if dp_parameters.asu_decoder(renamed_asu) == asu]
        renamed_asu_list = [renamed_asu for renamed_asu in dp_parameters.load_info
                            if dp_parameters.asu_decoder(renamed_asu) == asu]
        renamed_asu_volumes = {(renamed_asu, tank): dp_parameters.load_info[renamed_asu][renamed_asu, tank][0]
                               for renamed_asu in renamed_asu_list
                               for renamed_asu, tank in dp_parameters.load_info[renamed_asu]}
        asu_volumes = {}
        for (renamed_asu, tank), volume in renamed_asu_volumes.items():
            if not volume:
                continue
            asu_volumes.setdefault((asu, tank), 0)
            if renamed_asu not in renamed_asu_group:
                asu_volumes[asu, tank] += volume
            else:
                asu_n_row = package_flow_data[(package_flow_data['time'] == dp_parameters.time) &
                                                     (package_flow_data['id_asu'] == asu) &
                                                     (package_flow_data['n'] == tank)]
                new_volume = 0 if asu_n_row.empty else float(asu_n_row['volume'])  # TODO сделана заглушка: во flow data и departures не переносятся неиспользованные азс с прошлой смены
                asu_volumes[asu, tank] += new_volume
        for (a, tank), volume in asu_volumes.items():
            if not volume:
                continue
            row = flow_data[(flow_data['time'] == dp_parameters.time) &
                            (flow_data['id_asu'] == asu) & (flow_data['n'] == tank)].copy()
            row.loc[row.index, 'volume'] = volume
            result_flow_data = result_flow_data.append(row).reset_index(drop=True)

        result_departures_dict[asu, dp_parameters.time] = len(renamed_asu_list) - len(renamed_asu_in_group) + \
                                                          package_departures_dict[asu, dp_parameters.time]

    return result_flow_data, result_departures_dict


def remote_shifting_np(data: StaticData, dp_parameters: DParameters):
    restricts = data.restricts.copy()
    day = (dp_parameters.time + 1) // 2
    for truck, routes in dp_parameters.shifting_routes.items():
        for route in routes:
            depot = dp_parameters.shifting_depots[truck, route]
            loads_sequence = dp_parameters.shifting_sequence[truck, route]
            loads = dp_parameters.shifting_volumes[truck, route]
            for idx, asu_n in enumerate(loads_sequence):
                if not asu_n:
                    continue
                asu, n = dp_parameters.asu_decoder(asu_n[0]), asu_n[1]
                # depot restricts
                sku = data.tank_sku[asu, n]
                depot_sku = data.fuel_in_depot_inverse.get((depot, sku), None)
                if depot_sku and (depot, depot_sku, day) in restricts:
                    restricts[depot, depot_sku, day] = max(restricts[depot, depot_sku, day] - loads[idx], 0)
                    if restricts[depot, depot_sku, day] < data.average_section() and \
                            data.sku_vs_sku_name[sku] != 'G100':
                        restricts[depot, depot_sku, day] = 0
    return restricts


def cut_out_trip_optimization_result(result_trip_optimization, flow_data, departures_dict, used_reallocations,
                                     data: StaticData, dp_parameters: DParameters):
    # Апдейт data_iter.volumes_add. Блоки в работе азм проставляются в trip_optimization
    # Апдейт data_iter.restricts. Округление открытий до 0, если меньше средней секции
    # Апдейт flow_data, departures_dict, load_info (удаление использованных рейсов на азс)
    # Использованные привязки (asu_depot_reallocation по использованным азс_бакам)
    # Удаление машины из статуса загруженных

    day = (dp_parameters.time + 1) // 2  # TODO ночная смена - следующие открытия ?

    route_dict = {}
    for asu1, truck in result_trip_optimization.set_direct:
        route = ((asu1,),)
        route_dict[truck] = route
    for asu1, asu2, truck in result_trip_optimization.set_distribution:
        route = ((asu1, asu2),)
        route_dict[truck] = route
    for asu1, asu2, truck in result_trip_optimization.set_direct_double:
        route = ((asu1,), (asu2,))
        route_dict[truck] = route
    for asu1, asu2, asu3, truck in result_trip_optimization.set_distribution_double:
        route = ((asu1, asu2), (asu3,))
        route_dict[truck] = route

    route_depots_copy = {}

    for truck, route in route_dict.items():
        for asu_tuple in route:
            depot = dp_parameters.route_depots[truck, asu_tuple]
            loads_sequence = dp_parameters.truck_load_sequence[truck, asu_tuple]
            loads = dp_parameters.truck_load_volumes[truck, asu_tuple]
            for idx, asu_n in enumerate(loads_sequence):  # TODO should be same allocation
                if not asu_n:
                    continue
                asu, n = dp_parameters.asu_decoder(asu_n[0]), asu_n[1]
                # depot restricts
                sku = data.tank_sku[asu, n]
                depot_sku = data.fuel_in_depot_inverse.get((depot, sku), None)
                if depot_sku and (depot, depot_sku, day) in data.restricts:  # TODO корректировать только там, где не бесконечность.
                    data.restricts[depot, depot_sku, day] = max(data.restricts[depot, depot_sku, day] - loads[idx], 0)
                    if data.restricts[depot, depot_sku, day] < data.average_section() and \
                            data.sku_vs_sku_name[sku] != 'G100':
                        data.restricts[depot, depot_sku, day] = 0
                # asu volume add
                data.volumes_to_add.setdefault((asu, n, dp_parameters.time), 0)
                data.volumes_to_add[asu, n, dp_parameters.time] += loads[idx]

            for asu_n in set(loads_sequence):
                if not asu_n:
                    continue
                asu, n = dp_parameters.asu_decoder(asu_n[0]), asu_n[1]
                # flow_data
                flow_data_row = flow_data[(flow_data['time'] == dp_parameters.time) &
                                          (flow_data['id_asu'] == asu) &
                                          (flow_data['n'] == n)]
                if not flow_data_row.empty:
                    planned_volume = dp_parameters.load_info[asu_n[0]][asu_n][0]  # TODO Из интегральной модели удалять план или факт?
                    new_volume = flow_data_row['volume'].values[0] - planned_volume
                    if new_volume > data.asu_vehicle_avg_section[asu]:  # TODO Нужно сравнение со средней секцией на азс?
                        flow_data.loc[flow_data_row.index, 'volume'] = new_volume
                    else:
                        flow_data.drop(flow_data_row.index, inplace=True)
                        flow_data.reset_index(drop=True, inplace=True)
                # used_reallocation
                used_reallocations[asu, n, dp_parameters.time] = \
                    data.asu_depot_reallocation.get((asu, n, dp_parameters.time), depot)

            for renamed_asu in asu_tuple:
                asu = dp_parameters.asu_decoder(renamed_asu)
                # departures_dict
                departures = departures_dict.get((asu, dp_parameters.time), 0) - 1  # TODO Из интегральной модели удалять план или факт?
                if departures > 0:
                    departures_dict[asu, dp_parameters.time] = departures
                # load_info
                del dp_parameters.load_info[renamed_asu]  # TODO Из интегральной моде ли удалять план или факт?

            route_depots_copy[truck, asu_tuple] = dp_parameters.route_depots[truck, asu_tuple]

        if truck in dp_parameters.truck_loaded:
            del dp_parameters.truck_loaded[truck]

    # удаление дополнительных азс для развозов
    delete_phantom_loads(dp_parameters.load_info, dp_parameters.shifting_load_info)

    dp_parameters.route_depots = route_depots_copy


# удаление дополнительных азс для развозов
def delete_phantom_loads(load_info, shifting):
    for asu in list(load_info):
        if asu in shifting:
            continue
        for asu_n in list(load_info[asu]):
            if load_info[asu][asu_n][0] == 0:
                del load_info[asu][asu_n]
        if not load_info[asu]:
            del load_info[asu]



