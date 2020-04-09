import math
from detailed_planning.dp_parameters import DParameters
from data_reader.input_data import StaticData, unload_time_calculation, get_distance, shift_number_calculation
from docplex.mp.model import Model
from detailed_planning.functions import calculate_time_to_death


def extract_truck(list_of_vals):
    return list_of_vals[0]


"""Check the possibility of any trip by one truck (direct or distribution, single or double)
    return bounds of load time"""


def any_trip_duration_check(data: StaticData, dp_parameters: DParameters,
                            truck: int, trip1_renamed: tuple, trip2_renamed: tuple = None, is_load=True):

    load_time_bounds = {1: tuple()} if trip2_renamed is None else {1: tuple(), 2: tuple()}

    shift_duration_correction = 10.0 / 60  # Hours of allowed overworking time

    shift_number = shift_number_calculation(dp_parameters.time)  # Shift number
    asu1_renamed, asu2_renamed = list(map(lambda x: trip1_renamed[x] if x < len(trip1_renamed) else None, (0, 1)))
    asu3_renamed, asu4_renamed = list(map(lambda x: trip2_renamed[x] if x < len(trip2_renamed) else None, (0, 1))) \
        if trip2_renamed else (None, None)
    asu1, asu2, asu3, asu4 = list(map(dp_parameters.asu_decoder,
                                      (asu1_renamed, asu2_renamed, asu3_renamed, asu4_renamed)))
    trip1 = (asu1, asu2)
    trip2 = (asu3, asu4)

    """ Фильтры на рассмотрение 2-х смен:
        1. Если shift_size - unload_time - drive time <= начало окна в следующей смене, тогда вторую смену не рассматриваем
        2. Очереди <= 12 - truck_load_time 
        3. Если рейс (загрузка, перемещение, слив) находится в следующей смене, то рейс не рассматривается.
    """

    """If truck can't visit asu"""
    if not all([data.asu_vehicles_compatibility(truck, asu_id) for asu_id in (asu1, asu2, asu3, asu4) if asu_id]):
        return False, load_time_bounds

    """If truck-route is not in loads"""
    if not all([(truck, trip) in dp_parameters.truck_load_sequence for trip in (trip1_renamed, trip2_renamed) if trip]) and is_load:
        return False, load_time_bounds

    '''If asu doesn't work at this shift'''
    if any([not data.asu_work_shift[asu_id][shift_number] for asu_id in (asu1, asu2, asu3, asu4) if asu_id]):
        return False, load_time_bounds

    """If second trip is to death asu but first not"""
    if trip2_renamed and not is_asu_set_death(trip1_renamed, dp_parameters, data) and \
            is_asu_set_death(trip2_renamed, dp_parameters, data):
        return False, load_time_bounds

    # trip1_load_sequence = set(dp_parameters.truck_load_sequence[truck, trip1_renamed])
    # if 0 in trip1_load_sequence:
    #     trip1_load_sequence.remove(0)
    # trip2_load_sequence = set(dp_parameters.truck_load_sequence.get((truck, trip2_renamed), []))
    # if 0 in trip2_load_sequence:
    #     trip2_load_sequence.remove(0)

    if is_load:
        depot1 = dp_parameters.route_depots[truck, trip1_renamed]  # Depot connected to asu1 and asu2
        depot2 = dp_parameters.route_depots[truck, trip2_renamed] if trip2_renamed else None  # Depot connected to asu3 and asu4
    else:
        from detailed_planning.best_truck_load_linear import define_depot
        asu_n_1 = [asu_n for asu in trip1_renamed for asu_n in dp_parameters.load_info[asu]]
        depot1 = define_depot(asu_n_1, data, dp_parameters)
        if trip2_renamed:
            asu_n_2 = [asu_n for asu in trip2_renamed for asu_n in dp_parameters.load_info[asu]]
            depot2 = define_depot(asu_n_2, data, dp_parameters)
        else:
            depot2 = None

    hours_busy, location = data.vehicles_busy_hours.get((truck, dp_parameters.time), (None, None))
    cut_off_shift = data.vehicles_cut_off_shift.get((truck, dp_parameters.time), None)
    is_loaded = truck in dp_parameters.truck_loaded and depot1 in dp_parameters.truck_loaded[truck]
    is_own = truck in dp_parameters.own_trucks

    truck_volumes = []
    for trip in (trip1_renamed, trip2_renamed):
        if not trip:
            continue
        trip_volumes = []
        for asu in trip:
            if not asu:
                continue
            truck_volume = {}
            for i, v in enumerate(dp_parameters.truck_load_volumes.get((truck, tuple(asu for asu in trip if asu)), [])):
                asu_n = dp_parameters.truck_load_sequence[truck, tuple(asu for asu in trip if asu)][i]
                if asu_n and asu_n[0] == asu:
                    sku = data.tank_sku[dp_parameters.asu_decoder(asu_n[0]), asu_n[1]]
                    truck_volume.setdefault(sku, 0)
                    truck_volume[sku] += v
            trip_volumes.append(truck_volume)
        truck_volumes.append(trip_volumes)
    truck_sections = [[sum(1 for i, asu_n in enumerate(dp_parameters.truck_load_sequence.get((truck, tuple(asu for asu in trip if asu)), []))
                           if asu_n and asu_n[0] == asu)
                      for asu in trip if asu] for trip in (trip1_renamed, trip2_renamed) if trip]

    max_duration = data.vehicles[truck].shift_size - (cut_off_shift or 0) - shift_duration_correction

    '''Initialize distance of route'''
    start_time = 0 if hours_busy is None else hours_busy
    distance = start_time

    possible_load_end = []

    for index, trip, depot in zip((1, 2), (trip1, trip2), (depot1, depot2)):
        if not depot:
            break

        load_end = lambda x: x

        '''Drive time to depot'''
        if (not is_loaded and (is_own or hours_busy is not None)) or index == 2:

            if index == 2:
                location = asu2 or asu1
            elif location is None and is_own:
                location = data.vehicles[truck].uet
            elif location is None:
                location = depot

            if not isinstance(location, str):
                delta = get_distance(int(location), int(depot), data.distances_asu_depot)
            else:
                delta = get_distance(location, int(depot), data.distances_asu_uet)
            distance += delta
            if index == 2:
                possible_load_end[0] = lambda x, a=delta, f=possible_load_end[0]: f(x-a)
        ############################ TODO Проверить окно нб ####################################

        '''Truck load on depot'''
        if not is_loaded or index == 2:
            load_time_bounds[index] = (distance, )

            '''Shift default duration check'''
            if distance > dp_parameters.load_time_ub:
                return False, load_time_bounds  # If load starts after 12
            else:
                load_end = lambda x, a=dp_parameters.load_time_ub, f=load_end: f(min(x, a))

            """Load time"""
            get_load_time = data.depot_load_time[depot]  # Todo, Налив в зависимости от НБ
            distance += get_load_time  # dp_parameters.petrol_load_time
            load_end = lambda x, a=get_load_time, f=load_end: f(x-a)

        for asu_index, asu in enumerate(trip):
            if not asu:
                break

            '''Drive time to asu'''
            if asu_index == 1:
                delta = get_distance(*trip, data.distances_asu_depot)
            elif not is_loaded or (not is_own and hours_busy is None) or index == 2:
                delta = get_distance(depot, asu, data.distances_asu_depot)
            else:
                if hours_busy is None:
                    location = data.vehicles[truck].uet
                if isinstance(location, (int, float)):
                    delta = get_distance(int(location), asu, data.distances_asu_depot)
                else:
                    delta = get_distance(location, asu, data.distances_asu_uet)
            distance += delta
            load_end = lambda x, a=delta, f=load_end: f(x-a)

            '''Time windows check for asu'''

            '''Half truck or full truck unload time'''
            if is_load:
                unload = unload_time_calculation(asu, dp_parameters, data, truck,
                                                 truck_volumes[index - 1][asu_index],
                                                 truck_sections[index - 1][asu_index])
            else:
                unload = 2 + dp_parameters.docs_fill

            asu_window = define_asu_windows(distance, asu, dp_parameters.time, unload, max_duration, data)

            if not asu_window:
                return False, load_time_bounds  # If asu is closed for trucks

            distance = max(asu_window[0][0], distance)  # Waiting till asu1 opens
            load_end = lambda x, a=(asu, dp_parameters.time, unload, start_time, data, True), f=load_end: \
                f(min(x, define_asu_windows(x, *a)[-1][1]))

            distance += unload
            load_end = lambda x, a=unload, f=load_end: f(x-a)

        possible_load_end.append(load_end)

    '''Drive time from to uet'''
    if is_own:
        delta = get_distance(asu4 or asu3 or asu2 or asu1, data.vehicles[truck].uet, data.distances_asu_uet)
        distance += delta
        possible_load_end[-1] = lambda x, a=delta, f=possible_load_end[-1]: f(x-a)

    if distance > max_duration:
        return False, load_time_bounds

    trip_end_time = max_duration
    if trip2_renamed:
        load_time_bounds[2] = (load_time_bounds[2][0], possible_load_end[1](trip_end_time))
        trip_end_time = load_time_bounds[2][1]
        if load_time_bounds[2][1] < load_time_bounds[2][0]:
            return False, load_time_bounds
    if not is_loaded:
        load_time_bounds[1] = (load_time_bounds[1][0], possible_load_end[0](trip_end_time))
        if load_time_bounds[1][1] < load_time_bounds[1][0]:
            return False, load_time_bounds

    return distance, load_time_bounds


"""Get asu windows taking into account blocks, arrival time and next shift"""


def define_asu_windows(arrival_time, asu, shift_number, unload_time, max_duration, data: StaticData, reverse=False):
    shift = shift_number_calculation(shift_number)
    shifts = ((-1, 3 - shift), (0, shift), (1, 3 - shift))
    asu_windows = []
    shift_asu_windows = []
    block_asu_windows = []

    for sh in shifts:
        if data.asu_work_shift[asu][sh[1]]:
            shift_asu_windows.append([t + data.parameters.shift_size * sh[0] for t in data.asu_work_time[asu][sh[1]]])
            block_asu_windows.extend([[t + data.parameters.shift_size * sh[0] for t in window]
                                      for window in data.block_window_asu[asu, shift_number + sh[0]]]
                                     if (asu, shift_number + sh[0]) in data.block_window_asu else [])
    block_asu_windows.sort()

    for asu_window in shift_asu_windows:
        start = asu_window[0]
        for block in block_asu_windows.copy():
            # блок до окна
            if block[1] < start:
                block_asu_windows.pop(0)
                continue
            # блок начинается до окна
            if block[0] - unload_time < start:
                # блок заканчиватся в окне
                if block[1] < asu_window[1] - 0.01:
                    start = block[1]
                    block_asu_windows.pop(0)
                    continue
                # блок заканчиватся после окна
                else:
                    break
            # блок начинается в окне
            if block[0] - unload_time < asu_window[1]:
                finish = max(block[0] - unload_time - 0.1, start)
                asu_windows.append((start, finish))
                # блок заканчиватся в окне
                if block[1] < asu_window[1] - 0.01:
                    start = block[1]
                    block_asu_windows.pop(0)
                    continue
                # блок заканчиватся после окна
                else:
                    break
            # блок начинается после окна
            finish = max(asu_window[1] - 0.1, start)
            asu_windows.append((start, finish))
            break
        # конец окна
        if not block_asu_windows:
            finish = max(asu_window[1] - 0.1, start)
            asu_windows.append((start, finish))

    if reverse:
        asu_windows = [(b, e) for b, e in asu_windows if e > max_duration]
        filter_asu_windows = [(b, e) for b, e in asu_windows if arrival_time >= b]
        if not filter_asu_windows:
            filter_asu_windows = [(max_duration, max_duration)]
    else:
        asu_windows = [(b, e) for b, e in asu_windows if b < max_duration]
        filter_asu_windows = [(b, e) for b, e in asu_windows if arrival_time < e]

    return filter_asu_windows


"""Insert result from the model"""


def get_optimization_result(var_set):
    value_set = {}

    for val in var_set:
        if var_set[val].solution_value != 0:
            value_set[val] = var_set[val].solution_value

    return value_set


"""Define shifting routes: all routes except splitted asu, critical asu"""


def update_shifting_routes(route_dict, pd_parameters, data):
    pd_parameters.shifting_routes = {}

    def is_splitted(asu):
        return asu != pd_parameters.asu_decoder(asu)

    def is_critical(asu):
        days_to_death = calculate_time_to_death(asu, pd_parameters, data)
        next_shift = pd_parameters.time % 2 + 1
        is_working_next_shift = data.asu_work_shift[pd_parameters.asu_decoder(asu)][next_shift]
        return days_to_death <= 0.5 or (not is_working_next_shift and days_to_death <= 1.2)

    for truck, route in route_dict.items():
        for i, trip in enumerate(reversed(route)):
            if any(map(lambda x: is_splitted(x) or is_critical(x), trip)):
                break
            else:
                pd_parameters.shifting_routes.setdefault(truck, []).insert(0, trip)
                pd_parameters.shifting_volumes[truck, trip] = pd_parameters.truck_load_volumes[truck, trip]
                pd_parameters.shifting_sequence[truck, trip] = pd_parameters.truck_load_sequence[truck, trip]
                pd_parameters.shifting_depots[truck, trip] = pd_parameters.route_depots[truck, trip]
                for asu in trip:
                    pd_parameters.shifting_load_info[asu] = pd_parameters.load_info[asu]


"""Define shifting routes: all routes except splitted asu, critical asu"""


def clear_route_sets(set_direct, set_distribution, set_direct_double, set_distribution_double, shifting_routes):
    for asu1, truck in set_direct.copy():
        if truck not in shifting_routes:
            continue
        del set_direct[asu1, truck]

    for asu1, asu2, truck in set_distribution.copy():
        if truck not in shifting_routes:
            continue
        del set_distribution[asu1, asu2, truck]

    for asu1, asu2, truck in set_direct_double.copy():
        if truck not in shifting_routes:
            continue
        del set_direct_double[asu1, asu2, truck]
        if len(shifting_routes[truck]) == 1:
            set_direct[asu1, truck] = 1

    for asu12, asu34, truck in set_distribution_double.copy():
        if truck not in shifting_routes:
            continue
        del set_distribution_double[asu12, asu34, truck]
        if len(shifting_routes[truck]) == 1:
            if len(asu12) == 1:
                asu1 = asu12[0]
                set_direct[asu1, truck] = 1
            else:
                asu1, asu2 = asu12
                set_distribution[asu1, asu2, truck] = 1


"""Define blocks of vehicle, blocks of asu, decrease of depot queue based of result"""


def define_blocks(set_direct, set_distribution, set_direct_double, set_distribution_double,
                  depot_queue, depot_queue_accuracy, pd_parameters: DParameters, data: StaticData):
    vehicle_blocks, asu_blocks, depot_blocks = {}, {}, {}

    route_dict = {}
    for asu1, truck in set_direct:
        route = ((asu1,),)
        route_dict[truck] = route
    for asu1, asu2, truck in set_distribution:
        route = ((asu1, asu2),)
        route_dict[truck] = route
    for asu1, asu2, truck in set_direct_double:
        route = ((asu1,), (asu2,))
        route_dict[truck] = route
    for asu12, asu34, truck in set_distribution_double:
        route = (asu12, asu34)
        route_dict[truck] = route

    compact_depot_queue = get_compact_depot_queue(depot_queue, depot_queue_accuracy, route_dict, pd_parameters, data)
    print('compact_depot_queue', compact_depot_queue)
    depot_queue.clear()
    if pd_parameters.clear_shifting_routes:
        update_shifting_routes(route_dict, pd_parameters, data)
    else:
        pd_parameters.shifting_routes = {}
    clear_route_sets(set_direct, set_distribution, set_direct_double,
                     set_distribution_double, pd_parameters.shifting_routes)

    print('shifting_routes', pd_parameters.shifting_routes)
    for truck, route in route_dict.items():
        arrival_time, unload_time, real_asu = 0, 0, 0
        for t_index, trip in enumerate(route):
            if truck in pd_parameters.shifting_routes and trip in pd_parameters.shifting_routes[truck]:
                break
            if (truck, t_index) in compact_depot_queue:
                depot, time_interval = compact_depot_queue[truck, t_index]
                depot_queue[depot, time_interval, truck, (trip, ), t_index] = 1
                load_time = data.depot_load_time[depot]
                load_interval = int(math.ceil(load_time / depot_queue_accuracy))
                for interval in range(time_interval, time_interval + load_interval):
                    if (depot, interval) not in depot_blocks:
                        depot_blocks[depot, interval] = 0
                    depot_blocks[depot, interval] += 1
                arrival_time = time_interval * depot_queue_accuracy  # нужна поправка за ошибку интервала? 0.5 - много
            for a_index, asu in enumerate(trip):
                real_asu = pd_parameters.asu_decoder(asu)
                # Константа движения с uet/нб/азс
                to_distance_const = get_time_distance_from_last_point_to_asu(truck, a_index, t_index,
                                                                             route, pd_parameters, data)
                # Константа слива
                truck_volume = {}
                for i, v in enumerate(pd_parameters.truck_load_volumes[truck, trip]):
                    asu_n = pd_parameters.truck_load_sequence[truck, trip][i]
                    if asu_n and asu_n[0] == asu:
                        sku = data.tank_sku[pd_parameters.asu_decoder(asu_n[0]), asu_n[1]]
                        truck_volume.setdefault(sku, 0)
                        truck_volume[sku] += v
                truck_sections = sum(1 for i, asu_n in enumerate(pd_parameters.truck_load_sequence[truck, trip])
                                     if asu_n and asu_n[0] == asu)
                unload_time += unload_time_calculation(real_asu, pd_parameters, data, truck, truck_volume, truck_sections)

                arrival_time += to_distance_const
                asu_windows = define_asu_windows(arrival_time, real_asu, pd_parameters.time, unload_time,
                                                 pd_parameters.shift_size * 2, data)
                if not asu_windows:
                    asu_windows = define_asu_windows(0, real_asu, pd_parameters.time, unload_time,
                                                     pd_parameters.shift_size * 2, data)
                arrival_time = max(asu_windows[0][0], arrival_time)
                asu_blocks.setdefault((real_asu, pd_parameters.time), []).\
                    append((arrival_time, arrival_time + unload_time))

        if real_asu != 0:
            vehicle_blocks[truck, pd_parameters.time] = (arrival_time + unload_time, real_asu)

    return vehicle_blocks, asu_blocks, depot_blocks, depot_queue


def get_time_distance_from_last_point_to_asu(truck, a_index, t_index, route, pd_parameters, data):
    trip = route[t_index]
    depot = pd_parameters.route_depots[truck, trip]
    is_loaded = truck in pd_parameters.truck_loaded and depot in pd_parameters.truck_loaded[truck]
    real_asu = pd_parameters.asu_decoder(trip[a_index])
    to_distance_const = 0
    if a_index == 0:
        if t_index == 0 and is_loaded:
            hours_busy, location = data.vehicles_busy_hours.get((truck, pd_parameters.time), (None, None))
            to_distance_const += 0 if hours_busy is None else hours_busy
            if hours_busy is None and truck in pd_parameters.own_trucks:
                location = data.vehicles[truck].uet
            elif location is None:
                location = depot
            if isinstance(location, (int, float)):
                to_distance_const += get_distance(int(location), real_asu, data.distances_asu_depot)
            else:
                to_distance_const += get_distance(location, real_asu, data.distances_asu_uet)
        else:
            get_load_time = data.depot_load_time[depot]
            to_distance_const += get_load_time  # pd_parameters.petrol_load_time
            to_distance_const += get_distance(depot, real_asu, data.distances_asu_depot)
    else:
        to_distance_const += pd_parameters.docs_fill
        truck_volume = {}
        for i, v in enumerate(pd_parameters.truck_load_volumes[truck, trip]):
            asu_n = pd_parameters.truck_load_sequence[truck, trip][i]
            if asu_n and asu_n[0] == trip[0]:
                sku = data.tank_sku[pd_parameters.asu_decoder(asu_n[0]), asu_n[1]]
                truck_volume.setdefault(sku, 0)
                truck_volume[sku] += v
        truck_sections = sum(1 for i, asu_n in enumerate(pd_parameters.truck_load_sequence[truck, trip])
                             if asu_n and asu_n[0] == trip[0])
        to_distance_const += unload_time_calculation(pd_parameters.asu_decoder(trip[0]),
                                                     pd_parameters, data, truck, truck_volume, truck_sections)
        to_distance_const += get_distance(pd_parameters.asu_decoder(trip[0]),
                                          real_asu, data.distances_asu_depot)
    return to_distance_const


def get_time_distance_to_next_point_from_asu(truck, a_index, t_index, route, pd_parameters, data):
    trip = route[t_index]
    real_asu = pd_parameters.asu_decoder(trip[a_index])
    truck_volume = {}
    for i, v in enumerate(pd_parameters.truck_load_volumes[truck, trip]):
        asu_n = pd_parameters.truck_load_sequence[truck, trip][i]
        if asu_n and asu_n[0] == trip[a_index]:
            sku = data.tank_sku[pd_parameters.asu_decoder(asu_n[0]), asu_n[1]]
            truck_volume.setdefault(sku, 0)
            truck_volume[sku] += v
    truck_sections = sum(1 for i, asu_n in enumerate(pd_parameters.truck_load_sequence[truck, trip])
                         if asu_n and asu_n[0] == trip[a_index])
    unload_time = unload_time_calculation(real_asu, pd_parameters, data, truck, truck_volume, truck_sections)
    from_distance_const = 0
    if a_index == len(trip) - 1:
        from_distance_const += unload_time
        if t_index == len(route) - 1:
            if truck in pd_parameters.own_trucks:
                from_distance_const += get_distance(real_asu, data.vehicles[truck].uet, data.distances_asu_uet)
        else:
            next_depot = pd_parameters.route_depots[truck, route[1]]
            from_distance_const += get_distance(real_asu, next_depot, data.distances_asu_depot)
    return from_distance_const


# Приведение уменьшение очереди из входных данных к интервалам
def work_decrease_to_interval(depot_queue_accuracy, data: StaticData, pd_parameters: DParameters):
    depot_work_decrease = {}
    for depot in data.depot_capacity:
        blocks = data.get_depot_decrease_for_extended_shift(depot, pd_parameters.time, 12, 12)
        for lb, ub in blocks:
            l_interval = int(math.floor(lb / depot_queue_accuracy))
            u_interval = int(math.ceil(ub / depot_queue_accuracy))
            for time_interval in range(l_interval, u_interval + 1):
                if (depot, time_interval) not in depot_work_decrease:
                    depot_work_decrease[depot, time_interval] = 0
                depot_work_decrease[depot, time_interval] += 1
    return depot_work_decrease


"""Compact depot queue"""


def get_compact_depot_queue(depot_queue, depot_queue_accuracy, route_dict, pd_parameters, data: StaticData):
    result_depot_queue = {}

    depot_queue_counter = {}
    used_trucks = {}
    depot_waitings = {}
    new_depot_queue = {}

    depot_work_decrease = work_decrease_to_interval(depot_queue_accuracy, data, pd_parameters)

    # Определение ближайшего свободного места в очереди
    def get_free_depot_queue_time(depot, interval):
        load_time = data.depot_load_time[depot]
        for block in data.get_depot_blocks_for_extended_shift(depot, pd_parameters.time, 12, 12):
            if block[0] - load_time < interval * depot_queue_accuracy < block[1] - 0.001:
                next_interval = int(math.ceil(block[1] / depot_queue_accuracy))
                return get_free_depot_queue_time(depot, next_interval)
        queue = depot_queue_counter.setdefault(depot, [])
        load = int(math.ceil(load_time / depot_queue_accuracy))
        capacity = data.depot_capacity[depot]
        before = [t for t in queue if interval - load < t <= interval]
        after = [t for t in queue if interval < t < interval + load]
        for t in sorted({*before, interval}):
            queue_slice = [_ for _ in before + after if t <= _ < t + load]
            for i in range(max(t, interval), t + load):
                fact_capacity = capacity - pd_parameters.depot_queue_decrease.get((depot, i), 0) - \
                                depot_work_decrease.get((depot, i), 0)
                if len(queue_slice) >= fact_capacity:
                    return get_free_depot_queue_time(depot, interval + 1)
        queue.append(interval)
        queue.sort()
        return interval

    # Определение сжатой очереди
    input_depot_queue = list(depot_queue.keys()).copy()
    input_depot_queue.sort()
    for key in input_depot_queue:
        depot, time_interval, truck, route, trip_number = key
        if truck not in used_trucks:
            is_possible_route, load_time_bounds = any_trip_duration_check(data, pd_parameters, truck, *route)
            used_trucks[truck] = load_time_bounds
        load_time_bounds = used_trucks[truck]
        arrival_interval = int(math.ceil(load_time_bounds[trip_number + 1][0] / depot_queue_accuracy)) + \
                           depot_waitings.get(truck, 0)
        time_interval = get_free_depot_queue_time(depot, arrival_interval)
        result_depot_queue[truck, trip_number] = (depot, time_interval)
        depot_waitings[truck] = time_interval - arrival_interval
        new_depot_queue[depot, time_interval, truck, route, trip_number] = 1

    # Добавление в очередь машин длинных рейсов
    for truck in route_dict:
        if truck not in used_trucks:
            route = route_dict[truck]
            #route_list = [asu for trip in route for asu in trip]

            depot = pd_parameters.route_depots[truck, route[0]]
            is_load_before = truck in pd_parameters.truck_loaded and depot in pd_parameters.truck_loaded[truck]
            if not is_load_before:
                is_possible_route, load_time_bounds = any_trip_duration_check(data, pd_parameters, truck, *route)
                arrival_interval = int(math.ceil(load_time_bounds[trip_number + 1][0] / depot_queue_accuracy))
                time_interval = get_free_depot_queue_time(depot, arrival_interval)
                result_depot_queue[truck, 0] = (depot, time_interval)
                new_depot_queue[depot, time_interval, truck, route, 0] = 1

    depot_queue.clear()
    depot_queue.update(new_depot_queue)

    return result_depot_queue  # {(truck, trip_number): (depot, time_interval)}}


"""Update vehicles busy status"""


def update_vehicles_busy_status(data: StaticData, set_direct, dp_parameters: DParameters):
    for asu_id_converted, vehicle in set_direct:
        asu_id = dp_parameters.asu_decoder(asu_id_converted)
        if asu_id in data.far_asu:
            shifts_number = (data.trip_durations[asu_id] - dp_parameters.shift_size) // dp_parameters.shift_size
            for t in range(dp_parameters.time + 1, dp_parameters.time + int(shifts_number) + 1):
                data.vehicles_busy.append((vehicle, t))


"""Update loads for shifting routes"""


def update_shifting_loads(dp_parameters: DParameters):
    dp_parameters.truck_load_volumes.update(dp_parameters.shifting_volumes)
    dp_parameters.truck_load_sequence.update(dp_parameters.shifting_sequence)
    dp_parameters.route_depots.update(dp_parameters.shifting_depots)
    dp_parameters.load_info.update(dp_parameters.shifting_load_info)


"""Create depot queue variables"""


def depot_queue_variables(m: Model, truck: int, route: tuple, trip_number: int, load_time_bounds, depot_queue_accuracy,
                          var_sum_depot_queue: dict, data: StaticData, dp_parameters: DParameters):
    trip = route[trip_number]
    depot = dp_parameters.route_depots[truck, trip]
    load_time = data.depot_load_time[depot]

    var_set = {}
    l_interval = int(math.ceil(load_time_bounds[trip_number + 1][0] / depot_queue_accuracy))
    u_interval = max(l_interval, int(math.floor(load_time_bounds[trip_number + 1][1] / depot_queue_accuracy)))
    for time_interval in range(l_interval, u_interval + 1):
        if any(block[0] - load_time < time_interval * depot_queue_accuracy < block[1]
               for block in data.get_depot_blocks_for_extended_shift(depot, dp_parameters.time, 12, 12)):
            if (trip_number + 2) in load_time_bounds:
                load_time_bounds[trip_number + 2] = (load_time_bounds[trip_number + 2][0] + depot_queue_accuracy,
                                                     load_time_bounds[trip_number + 2][1])
            continue
        if (depot, time_interval) not in var_sum_depot_queue:
            var_sum_depot_queue[depot, time_interval] = []
        time_interval_str = ('_' if time_interval < 0 else '') + str(abs(time_interval))
        var = m.binary_var(name='d_%d_%s_%d_%s_%d' % (depot, time_interval_str, truck, str(route), trip_number))
        var_sum_depot_queue[depot, time_interval].append(var)
        var_set[depot, time_interval, truck, route, trip_number] = var
        load = int(math.ceil(load_time / depot_queue_accuracy))
        for delta in range(1, load):
            if (depot, time_interval + delta) not in var_sum_depot_queue:
                var_sum_depot_queue[depot, time_interval + delta] = []
            var_sum_depot_queue[depot, time_interval + delta].append(var)

    return var_set


def cut_depot_load_queue_interval(m: Model, queue_var_set: dict, load_time_bounds, depot_queue_accuracy):
    if all(trip_number == 0 for *_, trip_number in queue_var_set) or \
            all(trip_number == 1 for *_, trip_number in queue_var_set):
        return

    first_load_start = int(load_time_bounds[1][0] / depot_queue_accuracy)
    second_load_start = int(load_time_bounds[2][0] / depot_queue_accuracy)

    for first_time, second_time in zip(range(int(load_time_bounds[1][0] / depot_queue_accuracy),
                                             int(load_time_bounds[1][1] / depot_queue_accuracy) + 1),
                                       range(int(load_time_bounds[2][0] / depot_queue_accuracy),
                                             int(load_time_bounds[2][1] / depot_queue_accuracy) + 1)):
        m.add_constraint(m.sum(var for (_, time_interval, *_, trip_number), var in queue_var_set.items()
                               if trip_number == 0 and first_load_start <= time_interval <= first_time) >=
                         m.sum(var for (_, time_interval, *_, trip_number), var in queue_var_set.items()
                               if trip_number == 1 and second_load_start <= time_interval <= second_time))


"""Double asu list"""


def get_double_asu(asu_list, dp_parameters):
    real_asu_list = list(map(dp_parameters.asu_decoder, asu_list))
    double_asu_list = [asu for asu in set(real_asu_list) if real_asu_list.count(asu) > 1]
    return double_asu_list


"""Define longest idle-load path"""


def define_longest_idle_load_path(truck, asu1, asu2, dp_parameters, data):
    depot = dp_parameters.route_depots[truck, (asu1, asu2)]
    reverse_depot = dp_parameters.route_depots[truck, (asu2, asu1)]
    distance = get_distance(depot, asu1, data.distances_asu_depot)
    reverse_distance = get_distance(reverse_depot, asu2, data.distances_asu_depot)
    if distance < reverse_distance:
        return asu2, asu1
    elif distance > reverse_distance:
        return asu1, asu2


"""Define longest idle-load path"""


def get_not_priority_route(truck, asu1, asu2, weight_func, dp_parameters: DParameters, data: StaticData):
    weight_asu1 = weight_func(asu1)
    weight_asu2 = weight_func(asu2)

    if weight_asu1 != weight_asu2 and \
       (weight_asu1 == dp_parameters.asu_non_visiting_weight[0] or
        weight_asu2 == dp_parameters.asu_non_visiting_weight[0]):
        not_priority_route = (asu2, asu1) if weight_asu1 > weight_asu2 else (asu1, asu2)
    else:
        not_priority_route = define_longest_idle_load_path(truck, asu1, asu2, dp_parameters, data)

    return not_priority_route


"""Create asu queue variables"""


def asu_queue_variables(m: Model, trip_var, truck, route, var_depot_queue, double_asu_list, depot_queue_accuracy, var_sum_asu_queue, dp_parameters, data):
    arrival_expr = {}
    for t_index, trip in enumerate(route):
        if all(dp_parameters.asu_decoder(asu) not in double_asu_list for asu in trip):
            continue
        depot = dp_parameters.route_depots[truck, trip]
        for a_index, asu in enumerate(trip):
            asu_queue_vars = []
            real_asu = dp_parameters.asu_decoder(asu)
            is_loaded = truck in dp_parameters.truck_loaded and depot in dp_parameters.truck_loaded[truck]
            # Константа движения с uet/нб/азс
            to_distance_const = get_time_distance_from_last_point_to_asu(truck, a_index, t_index,
                                                                         route, dp_parameters, data)
            # Константа слива
            truck_volume = {}
            for i, v in enumerate(dp_parameters.truck_load_volumes[truck, trip]):
                asu_n = dp_parameters.truck_load_sequence[truck, trip][i]
                if asu_n and asu_n[0] == asu:
                    sku = data.tank_sku[dp_parameters.asu_decoder(asu_n[0]), asu_n[1]]
                    truck_volume.setdefault(sku, 0)
                    truck_volume[sku] += v
            truck_sections = sum(1 for i, asu_n in enumerate(dp_parameters.truck_load_sequence[truck, trip])
                                 if asu_n and asu_n[0] == asu)
            unload_time = unload_time_calculation(real_asu, dp_parameters, data, truck, truck_volume, truck_sections)
            # Константа движения до нб/uet
            from_distance_const = get_time_distance_to_next_point_from_asu(truck, a_index, t_index,
                                                                           route, dp_parameters, data)

            cut_off_shift = data.vehicles_cut_off_shift.get((truck, dp_parameters.time), None)
            max_duration = data.vehicles[truck].shift_size - (cut_off_shift or 0)

            asu_window_sum = get_asu_window_sum(real_asu, to_distance_const, unload_time, max_duration,
                                                depot_queue_accuracy, var_sum_asu_queue, dp_parameters, data)
            full_asu_window_sum = get_asu_window_sum(real_asu, 0, 0, 0, depot_queue_accuracy,
                                                     var_sum_asu_queue, dp_parameters, data)

            to_distance_const = int(to_distance_const / depot_queue_accuracy)
            unload_time = int(unload_time / depot_queue_accuracy)
            from_distance_const = int(from_distance_const / depot_queue_accuracy)

            for interval, var_sum in asu_window_sum.items():
                arrival_time = m.binary_var(name='asu_arrival_time_%d_%s_%d_%d' % (truck, str(route), asu, interval))
                arrival_expr[truck, route, asu, interval] = arrival_time
                asu_queue_vars.append(arrival_time)
                var_sum.append(arrival_time)
                # блок азс на время залива
                for delta in range(1, unload_time + 1):
                    if interval + delta in full_asu_window_sum:
                        full_asu_window_sum[interval + delta].append(arrival_time)
                # время в очереди зависит от очереди на нб
                if a_index == 0 and (t_index == 1 or not is_loaded):
                    m.add_constraint(m.sum(var for (_, time_interval, *_, trip_number), var in var_depot_queue.items()
                                           if trip_number == t_index and time_interval <= interval - to_distance_const) >=
                                     arrival_time)
                # время в очереди зависит от предыдущего слива
                if a_index == 1:
                    m.add_constraint(m.sum(var for (*_, _asu, _interval), var in arrival_expr.items()
                                           if _asu == trip[0] and _interval <= interval - to_distance_const) >=
                                     arrival_time)
                # время в очереди влияет на следующую загрузку
                if a_index == len(trip) - 1 and t_index != len(route) - 1:
                    m.add_constraint(m.sum(var for (_, time_interval, *_, trip_number), var in var_depot_queue.items()
                                           if trip_number == 1 and time_interval <= interval + from_distance_const) <=
                                     m.sum(var for (*_, _asu, _interval), var in arrival_expr.items()
                                           if _asu == asu and _interval <= interval))
                # время в очереди влияет на конец смены
                if a_index == len(trip) - 1 and t_index == len(route) - 1:
                    m.add_constraint((interval + from_distance_const) * arrival_time * depot_queue_accuracy <=
                                     max_duration)

            # если рейс выбран, то он должен занять место в очереди
            m.add_constraint(m.sum(asu_queue_vars) == trip_var, ctname='asu_arrival_%d_%s_%d' % (truck, str(route), asu))
    return arrival_expr


"""Create asu queue sum variables"""


def get_asu_window_sum(asu, arrival_time, unload_time, max_duration, depot_queue_accuracy, var_sum_asu_queue, dp_parameters, data):

    asu_window_sum = {}

    if asu not in var_sum_asu_queue:
        asu_windows = define_asu_windows(0, asu, dp_parameters.time, 0, dp_parameters.shift_size * 2, data)
        if asu_windows:
            var_sum_asu_queue[asu] = {}
        for window in asu_windows:
            for time_interval in range(int(window[0] / depot_queue_accuracy),
                                       int(window[1] / depot_queue_accuracy) + 1):
                if time_interval not in var_sum_asu_queue:
                    var_sum_asu_queue[asu][time_interval] = []

    asu_windows = define_asu_windows(arrival_time, asu, dp_parameters.time, unload_time, max_duration or dp_parameters.shift_size * 2, data)
    for window in asu_windows:
        for time_interval in range(int(window[0] / depot_queue_accuracy),
                                   int(window[1] / depot_queue_accuracy) + 1):
            asu_window_sum[time_interval] = var_sum_asu_queue[asu][time_interval]

    return asu_window_sum


"""Fill depot restrict dict"""


def add_to_depot_restricts(truck, trip_route, var, depot_restrict_vars: dict,
                           dp_parameters: DParameters, data: StaticData):
    day = (dp_parameters.time + 1) // 2
    for trip in trip_route:
        loads = dp_parameters.truck_load_volumes[truck, trip]
        tanks = dp_parameters.truck_load_sequence[truck, trip]
        depot = dp_parameters.route_depots[truck, trip]
        for asu_n, volume in zip(tanks, loads):
            if asu_n == 0:
                continue
            asu, n = asu_n
            decoded_asu = dp_parameters.asu_decoder(asu)
            sku = data.tank_sku[decoded_asu, n]
            if (depot, sku) in data.fuel_in_depot_inverse:
                depot_sku = data.fuel_in_depot_inverse[depot, sku]
                if (depot, depot_sku, day) in data.restricts:
                    depot_restrict_vars.setdefault((depot, depot_sku), [])
                    depot_restrict_vars[depot, depot_sku].append(volume * var)
            else:
                print('Загрузка с несуществующим на депоте топливом: truck %d, route %s, depot % d, sku %d' %
                      (truck, str(trip_route), depot, sku))


"""Create objective function"""


def objective_generator(dp_parameters: DParameters, var_set_direct: dict, var_set_distribution: dict, var_set_direct_double: dict,
                        var_set_distribution_double: dict, var_set_asu_visiting: dict, var_set_restricts_excess: dict, penalty_set: dict,
                        distances: dict, far_asu, asu_work_shift: dict, busy_truck: dict, data: StaticData, truck_in_use=None):

    objective_function = 0
    min_time_to_death = {}
    for asu in dp_parameters.load_info:
        min_time_to_death[asu] = min(dp_parameters.asu_tank_death[dp_parameters.asu_decoder(asu2), n]
                                     for asu2, n in dp_parameters.load_info[asu])

    """Load penalties"""
    if dp_parameters.load_penalties_obj:

        objective_function += dp_parameters.load_penalties_weight * sum(var_set_direct[asu, truck] * penalty_set.get((truck, (asu,)), 0)
                                                                        for (asu, truck) in var_set_direct)
        objective_function += dp_parameters.load_penalties_weight * sum(
            var_set_distribution[asu1, asu2, truck] * penalty_set.get((truck, (asu1, asu2)), 0)
            for (asu1, asu2, truck) in var_set_distribution)
        objective_function += dp_parameters.load_penalties_weight * sum(
            var_set_direct_double[asu1, asu2, truck] * (penalty_set.get((truck, (asu1,)), 0) + penalty_set.get((truck, (asu2,)), 0))
            for (asu1, asu2, truck) in var_set_direct_double)
        objective_function += dp_parameters.load_penalties_weight * sum(
            var_set_distribution_double[asu12, asu34, truck] * (penalty_set.get((truck, asu12), 0) + penalty_set.get((truck, asu34), 0))
            for (asu12, asu34, truck) in var_set_distribution_double)

    """Own trucks use priority"""
    if dp_parameters.own_truck_obj:
        objective_function += dp_parameters.own_truck_weight * sum(var_set_direct[asu, truck]
                                                                   for (asu, truck) in var_set_direct if truck in dp_parameters.own_trucks)

        objective_function += dp_parameters.own_truck_weight * sum(var_set_distribution[asu1, asu2, truck]
                                                                   for (asu1, asu2, truck) in var_set_distribution if
                                                                   truck in dp_parameters.own_trucks)

        objective_function += dp_parameters.own_truck_weight * sum(var_set_direct_double[asu1, asu2, truck]
                                                                   for (asu1, asu2, truck) in var_set_direct_double if
                                                                   truck in dp_parameters.own_trucks)

        objective_function += dp_parameters.own_truck_weight * sum(var_set_distribution_double[asu12, asu34, truck]
                                                                   for (asu12, asu34, truck) in var_set_distribution_double if
                                                                   truck in dp_parameters.own_trucks)

    """Double trip growth """
    if dp_parameters.double_trips_loaded_truck:
        objective_function += dp_parameters.double_trips_weight * sum(var_set_direct_double[asu1, asu2, truck]
                                                                      for (asu1, asu2, truck) in var_set_direct_double if
                                                                      data.vehicles[truck].shift_size <= 14)

        # objective_function += dp_parameters.double_trips_weight * sum(var_set_distribution_double[asu12, asu34, truck]
        #                                                               for (asu12, asu34, truck) in var_set_distribution_double)

    """Double trip use loaded trucks """
    if dp_parameters.double_trips_obj:
        objective_function += dp_parameters.double_trips_loaded_truck_weight * sum(var_set_direct_double[asu1, asu2, truck]
                                                                                   for (asu1, asu2, truck) in var_set_direct_double if
                                                                                   truck in dp_parameters.truck_loaded)

        objective_function += dp_parameters.double_trips_loaded_truck_weight * sum(var_set_distribution_double[asu12, asu34, truck]
                                                                                   for (asu12, asu34, truck) in var_set_distribution_double
                                                                                   if truck in dp_parameters.truck_loaded)
    """Turnaround increase"""
    if dp_parameters.turnaround_obj:
        objective_function += dp_parameters.turnaround_weight * sum(var_set_direct[asu, truck]
                                                                    for (asu, truck) in var_set_direct if
                                                                    truck in dp_parameters.trucks_used)

        objective_function += dp_parameters.turnaround_weight * sum(var_set_distribution[asu1, asu2, truck]
                                                                    for (asu1, asu2, truck) in var_set_distribution if
                                                                    truck in dp_parameters.trucks_used)

        objective_function += dp_parameters.turnaround_weight * sum(var_set_direct_double[asu1, asu2, truck]
                                                                    for (asu1, asu2, truck) in var_set_direct_double if
                                                                    truck in dp_parameters.trucks_used)

        objective_function += dp_parameters.turnaround_weight * sum(var_set_distribution_double[asu12, asu34, truck]
                                                                    for (asu12, asu34, truck) in var_set_distribution_double if
                                                                    truck in dp_parameters.trucks_used)

    """Distance between asu penalties"""
    if dp_parameters.distance_penalties_obj:
        objective_function += dp_parameters.distance_penalties_weight * \
                              sum(var_set_distribution[asu1, asu2, truck] *
                                  get_distance(dp_parameters.asu_decoder(asu1), dp_parameters.asu_decoder(asu2), distances)
                                  for (asu1, asu2, truck) in var_set_distribution)

        objective_function += dp_parameters.distance_penalties_weight * \
                              sum(var_set_distribution_double[asu12, asu34, truck] *
                                  ((get_distance(dp_parameters.asu_decoder(asu12[0]), dp_parameters.asu_decoder(asu12[1]), distances)
                                    if len(asu12) == 2 else 0) +
                                   (get_distance(dp_parameters.asu_decoder(asu34[0]), dp_parameters.asu_decoder(asu34[1]), distances)
                                    if len(asu34) == 2 else 0))
                                  for (asu12, asu34, truck) in var_set_distribution_double)

    def weight_non_visiting_asu(asu):
        days_to_death = calculate_time_to_death(asu, dp_parameters, data)
        # days_to_death = min([dp_parameters.asu_tank_death[dp_parameters.asu_decoder(asu), n]
        #                      for asu, n in dp_parameters.load_info[asu]
        #                      if dp_parameters.load_info[asu][asu, n][0]])
        #
        # moving_correction = 0.5 * (trip_duration_func(dp_parameters.asu_decoder(asu)) // dp_parameters.shift_size)
        # days_to_death = days_to_death - moving_correction
        # days_to_death = days_to_death - 0.25 * ((trip_duration_func(dp_parameters.asu_decoder(asu)) % dp_parameters.shift_size) / dp_parameters.shift_size)  # TODO for test
        next_shift = dp_parameters.time % 2 + 1
        if (days_to_death <= 0.5 or (asu_work_shift[dp_parameters.asu_decoder(asu)][next_shift] == 0 and days_to_death <= 1.2)) \
                and dp_parameters.asu_trip_number.get(asu, 1) == 1:  # shift in days
            weight = dp_parameters.asu_non_visiting_weight[0]
        elif days_to_death <= 1:  # shift + next shift in days
            weight = dp_parameters.asu_non_visiting_weight[1]
        elif days_to_death <= 1.5:  # shift + next shift in days
            weight = dp_parameters.asu_non_visiting_weight[2]
        else:  # other shifts
            weight = dp_parameters.asu_non_visiting_weight[3]
        return weight

    """Idle distance for distributions"""
    if dp_parameters.idle_distance_penalties_obj:
        distributions = list(var_set_distribution.keys())
        while distributions:
            asu1, asu2, truck = distributions.pop(0)
            if (asu2, asu1, truck) in distributions:
                not_priority_route = get_not_priority_route(truck, asu1, asu2,
                                                            weight_non_visiting_asu, dp_parameters, data)
                if not_priority_route:
                    objective_function += dp_parameters.idle_distance_penalties_weight * \
                                          var_set_distribution[(*not_priority_route, truck)]
                distributions.remove((asu2, asu1, truck))

        distributions = list(var_set_distribution_double.keys())
        while distributions:
            asu12, asu34, truck = distributions.pop(0)
            if len(asu12) == 2:
                asu1, asu2 = asu12
                if ((asu2, asu1), asu34, truck) in distributions:
                    not_priority_route = get_not_priority_route(truck, asu1, asu2,
                                                                weight_non_visiting_asu, dp_parameters, data)
                    if not_priority_route:
                        objective_function += dp_parameters.idle_distance_penalties_weight * \
                                          var_set_distribution_double[not_priority_route, asu34, truck]
                    distributions.remove(((asu2, asu1), asu34, truck))
            else:
                asu3, asu4 = asu34
                if (asu12, (asu4, asu3), truck) in distributions:
                    not_priority_route = get_not_priority_route(truck, asu3, asu4,
                                                                weight_non_visiting_asu, dp_parameters, data)
                    if not_priority_route:
                        objective_function += dp_parameters.idle_distance_penalties_weight * \
                                          var_set_distribution_double[asu12, not_priority_route, truck]
                    distributions.remove((asu12, (asu4, asu3), truck))

    """Far asu visits with non-own park bonus"""
    if dp_parameters.far_asu_third_party_vehicles:
        objective_function += dp_parameters.far_asu_third_party_vehicles_weight * sum(var_set_direct[asu, truck]
                                                                    for (asu, truck) in var_set_direct if
                                                                    truck not in dp_parameters.own_trucks and
                                                                                      asu in far_asu)

    """Penalties for non visiting asu. Penalties for asu with death in shift or next shift are increased"""
    if dp_parameters.asu_non_visiting_penalties_obj:
        for asu in var_set_asu_visiting:
            objective_function += weight_non_visiting_asu(asu) * (1 - var_set_asu_visiting[asu])

    def weight_truck_loaded(death_t):
        if death_t <= 0.375:  # shift in days
            return dp_parameters.loaded_truck_priority_weight[0]
        elif death_t <= 0.875:  # shift + next shift in days
            return dp_parameters.loaded_truck_priority_weight[1]
        else:  # other shifts
            return 0

    """Loaded truck for critical asu"""
    if dp_parameters.loaded_truck_priority:
        objective_function += sum(weight_truck_loaded(min_time_to_death[asu]) * var_set_direct[asu, truck]
                                  for (asu, truck) in var_set_direct if
                                  truck in dp_parameters.truck_loaded and dp_parameters.asu_trip_number.get(asu, 1) == 1)

        objective_function += sum(
            min(weight_truck_loaded(min_time_to_death[asu1]), weight_truck_loaded(min_time_to_death[asu2]) + 30) *
            var_set_distribution[asu1, asu2, truck]
            for (asu1, asu2, truck) in var_set_distribution if
            truck in dp_parameters.truck_loaded and (dp_parameters.asu_trip_number.get(asu1, 1) == 1 or dp_parameters.asu_trip_number.get(asu2, 1) == 1))

        objective_function += sum(
            min(weight_truck_loaded(min_time_to_death[asu1]), weight_truck_loaded(min_time_to_death[asu2]) + 30) *
            var_set_direct_double[asu1, asu2, truck]
            for (asu1, asu2, truck) in var_set_direct_double if
            truck in dp_parameters.truck_loaded and dp_parameters.asu_trip_number.get(asu1, 1) == 1)

        objective_function += sum(
            weight_truck_loaded(min_time_to_death[asu12[0]]) *
            var_set_distribution_double[asu12, asu34, truck]
            for (asu12, asu34, truck) in var_set_distribution_double if
            truck in dp_parameters.truck_loaded and dp_parameters.asu_trip_number.get(asu12[0], 1) == 1)

    "============================ Штраф за поздний выезд на критичную АЗС ============================"

    def weight_truck_busy_penalty(death_t, busy_hours):

        if busy_hours >= 3:
            if death_t <= 0.5:  # shift in days
                return dp_parameters.empty_section_weight * dp_parameters.load_penalties_weight
            elif death_t <= 0.875:  # shift + next shift in days
                return dp_parameters.empty_section_weight * dp_parameters.load_penalties_weight * 0.25
            else:  # other shifts
                return 0
        else:
            return 0

    if True:  # dp_parameters.busy_truck_non_critical_asu:
        objective_function += sum(
            weight_truck_busy_penalty(calculate_time_to_death(asu, dp_parameters, data), busy_truck[truck, dp_parameters.time][0]) *
            var_set_direct[asu, truck] for (asu, truck) in var_set_direct if
            (truck, dp_parameters.time) in busy_truck)

        objective_function += sum(
            weight_truck_busy_penalty(min(calculate_time_to_death(asu1, dp_parameters, data),
                                          calculate_time_to_death(asu2, dp_parameters, data)),
                                      busy_truck[truck, dp_parameters.time][0]) * var_set_distribution[asu1, asu2, truck]
            for (asu1, asu2, truck) in var_set_distribution if
            (truck, dp_parameters.time) in busy_truck)

        objective_function += sum(
            weight_truck_busy_penalty(min(calculate_time_to_death(asu1, dp_parameters, data),
                                          calculate_time_to_death(asu2, dp_parameters, data)),
                                      busy_truck[truck, dp_parameters.time][0]) * var_set_direct_double[asu1, asu2, truck]
            for (asu1, asu2, truck) in var_set_direct_double if
            (truck, dp_parameters.time) in busy_truck)

        objective_function += sum(
            weight_truck_busy_penalty(calculate_time_to_death(asu12[0], dp_parameters, data),
                                      busy_truck[truck, dp_parameters.time][0]) * var_set_distribution_double[asu12, asu34, truck]
            for (asu12, asu34, truck) in var_set_distribution_double if
            (truck, dp_parameters.time) in busy_truck)

    "======================================================================================================"

    """Used truck NOT for critical asu"""
    if dp_parameters.busy_truck_non_critical_asu:
        objective_function -= sum(
            weight_truck_loaded(min_time_to_death[asu]) * busy_truck[truck, dp_parameters.time][0] * var_set_direct[asu, truck]
            for (asu, truck) in var_set_direct if
            (truck, dp_parameters.time) in busy_truck)

        objective_function -= sum(
            min(weight_truck_loaded(min_time_to_death[asu1]), weight_truck_loaded(min_time_to_death[asu2]) - 30) *
            busy_truck[truck, dp_parameters.time][0] * var_set_distribution[asu1, asu2, truck]
            for (asu1, asu2, truck) in var_set_distribution if
            (truck, dp_parameters.time) in busy_truck)

        objective_function -= sum(
            min(weight_truck_loaded(min_time_to_death[asu1]), weight_truck_loaded(min_time_to_death[asu2]) - 30) *
            busy_truck[truck, dp_parameters.time][0] * var_set_direct_double[asu1, asu2, truck]
            for (asu1, asu2, truck) in var_set_direct_double if
            (truck, dp_parameters.time) in busy_truck)

        objective_function -= sum(
            weight_truck_loaded(min_time_to_death[asu12[0]]) *
            busy_truck[truck, dp_parameters.time][0] * var_set_distribution_double[asu12, asu34, truck]
            for (asu12, asu34, truck) in var_set_distribution_double if
            (truck, dp_parameters.time) in busy_truck)

    """Cutoff trucks first in queue"""
    if dp_parameters.cut_off_truck_first:
        objective_function -= sum(450 * var_set_direct[asu, truck]
                                  for (asu, truck) in var_set_direct if
                                  data.vehicles_cut_off_shift.get((truck, dp_parameters.time), 0) >= 2.5 and
                                  data.vehicles[truck].shift_size <= 13)

        objective_function -= sum(350 * var_set_distribution[asu1, asu2, truck]
                                  for (asu1, asu2, truck) in var_set_distribution if
                                  data.vehicles_cut_off_shift.get((truck, dp_parameters.time), 0) >= 2.5 and
                                  data.vehicles[truck].shift_size <= 13)

    """Penalties for non visiting asu, closed next shift"""
    if dp_parameters.asu_closed_next_shift_penalties_obj:
        for asu in var_set_asu_visiting:
            next_shift = dp_parameters.time % 2 + 1
            is_work = asu_work_shift[dp_parameters.asu_decoder(asu)][next_shift]
            if not is_work:
                objective_function += dp_parameters.asu_closed_next_shift_weight * (1 - var_set_asu_visiting[asu])

    """Penalties for double trip if in each half there is asu with time to death in current shift"""
    if dp_parameters.double_death_route_penalties_obj:
        def is_double_death_route(first_asu_set, second_asu_set):
            return is_asu_set_death(first_asu_set, dp_parameters, data) and \
                   is_asu_set_death(second_asu_set, dp_parameters, data)

        route_asu_sets = set(((asu1,), (asu2,)) for (asu1, asu2, truck) in var_set_direct_double)
        route_asu_sets.update(set((asu12, asu34) for (asu12, asu34, truck) in var_set_distribution_double))
        route_asu_sets = set(filter(lambda x: is_double_death_route(*x), route_asu_sets))

        objective_function += dp_parameters.double_death_route_weight * sum(var_set_direct_double[asu1, asu2, truck]
                                                                            for (asu1, asu2, truck) in var_set_direct_double
                                                                            if ((asu1,), (asu2,)) in route_asu_sets)
        objective_function += dp_parameters.double_death_route_weight * sum(var_set_distribution_double[asu12, asu34, truck]
                                                                            for (asu12, asu34, truck) in var_set_distribution_double
                                                                            if (asu12, asu34) in route_asu_sets)

        objective_function += dp_parameters.double_death_route_weight * sum(var_set_direct[asu, truck]
                                                                            for (asu, truck) in var_set_direct
                                                                            if truck_in_use and truck_in_use[truck] >= 1)
        objective_function += dp_parameters.double_death_route_weight * sum(var_set_distribution[asu1, asu2, truck]
                                                                            for (asu1, asu2, truck) in var_set_distribution
                                                                            if truck_in_use and truck_in_use[truck] >= 1)

    """Penalties for distribution route"""
    if dp_parameters.route_with_distribution:
        objective_function += dp_parameters.route_with_distribution_weight * sum(var_set_distribution.values())

    """Penalties for distribution route where both asu in current group"""
    if dp_parameters.route_with_distribution_both_asu_in_group:
        objective_function += sum(var * (min(map(weight_non_visiting_asu, (asu1, asu2))) + 1) * 0.8
                                  for (asu1, asu2, truck), var in var_set_distribution.items()
                                  if asu1 in var_set_asu_visiting and asu2 in var_set_asu_visiting)
                                  
        objective_function += sum(var * (min(map(weight_non_visiting_asu, (asu12[0], asu12[1]))) + 1) * 0.8 if len(asu12) == 2 else
                                  var * (min(map(weight_non_visiting_asu, (asu34[0], asu34[1]))) + 1) * 0.8
                                  for (asu12, asu34, truck), var in var_set_distribution_double.items()
                                  if (len(asu12) == 2 and (asu12[0] in var_set_asu_visiting and asu12[1] in var_set_asu_visiting)) or
                                  (len(asu34) == 2 and (asu34[0] in var_set_asu_visiting and asu34[1] in var_set_asu_visiting)))

    """Penalties for distribution route where one asu in group"""
    if dp_parameters.route_with_distribution_one_asu_in_group:
        objective_function += sum(var
                                  for (asu1, asu2, truck), var in var_set_distribution.items() if
                                  (asu1 in var_set_asu_visiting and asu2 not in var_set_asu_visiting) or
                                  (asu2 in var_set_asu_visiting and asu1 not in var_set_asu_visiting))

    """Penalty for waiting while truck is loaded"""
    if dp_parameters.loaded_truck_waiting:
        objective_function += dp_parameters.loaded_truck_waiting_weight * sum(wait_time_asu_open(asu, truck, data, dp_parameters) * val
                                                                              for (asu, truck), val in var_set_direct.items() if
                                                                              truck in dp_parameters.truck_loaded)

        objective_function += dp_parameters.loaded_truck_waiting_weight * sum(wait_time_asu_open(asu1, truck, data, dp_parameters) * val
                                                                              for (asu1, asu2, truck), val in var_set_distribution.items() if
                                                                              truck in dp_parameters.truck_loaded)

        objective_function += dp_parameters.loaded_truck_waiting_weight * sum(wait_time_asu_open(asu1, truck, data, dp_parameters) * val
                                                                              for (asu1, asu2, truck), val in var_set_direct_double.items() if
                                                                              truck in dp_parameters.truck_loaded)

        objective_function += dp_parameters.loaded_truck_waiting_weight * sum(wait_time_asu_open(asu12[0], truck, data, dp_parameters) * val
                                                                              for (asu12, asu34, truck), val in var_set_distribution_double.items() if
                                                                              truck in dp_parameters.truck_loaded)

    """Penalties for critical asu in second route for 24-hours vehicles"""
    if dp_parameters.critical_asu_on_second_long_route:
        objective_function += dp_parameters.critical_asu_on_second_long_route_weight * \
                              sum(var for (asu, truck), var in var_set_direct.items()
                                  if data.vehicles[truck].shift_size > dp_parameters.shift_size and
                                  min_time_to_death[asu] <= 0.875 and truck_in_use.get(truck, 0) >= 1)

        objective_function += dp_parameters.critical_asu_on_second_long_route_weight * \
                              sum(var for (asu1, asu2, truck), var in var_set_distribution.items()
                                  if data.vehicles[truck].shift_size > dp_parameters.shift_size and
                                  (min_time_to_death[asu1] <= 0.875 or min_time_to_death[asu2] <= 0.875) and
                                  truck_in_use.get(truck, 0) >= 1)

        objective_function += dp_parameters.critical_asu_on_second_long_route_weight * \
                              sum(var for (asu1, asu2, truck), var in var_set_direct_double.items()
                                  if data.vehicles[truck].shift_size > dp_parameters.shift_size and
                                  min_time_to_death[asu2] <= 0.875)

        objective_function += dp_parameters.critical_asu_on_second_long_route_weight * \
                              sum(var for (asu12, asu34, truck), var in var_set_distribution_double.items()
                                  if data.vehicles[truck].shift_size > dp_parameters.shift_size and
                                  any(map(lambda x: min_time_to_death[x] <= 0.875, asu34)))

    """Asu_truck double trip probabilities"""
    if dp_parameters.double_trip_probs:
        objective_function += dp_parameters.double_trips_probs_weight * sum(val * var_set_direct[asu, truck]
                                                                            for (truck, asu), val in dp_parameters.double_trip_probs_dict.items()
                                                                            if (asu, truck) in var_set_direct)

    """Excess depot restricts"""
    if dp_parameters.depot_restrict_excess:
        for (depot, depot_sku), var in var_set_restricts_excess.items():
            penalty = dp_parameters.deficit_depot_restrict_excess_weight \
                if depot_sku in data.sku_deficit.get(depot, []) \
                else dp_parameters.depot_restrict_excess_weight
            objective_function += penalty * var

    return objective_function


"""Check is asu_set death in current shift or closed next shift"""


def is_asu_set_death(asu_set, dp_parameters, data):
    if all(dp_parameters.asu_trip_number.get(asu, 1) != 1 for asu in asu_set if asu):
        return False

    min_time_to_death = min(calculate_time_to_death(asu, dp_parameters, data) for asu in asu_set if asu)

    next_shift = dp_parameters.time % 2 + 1
    asu_work = sum(1 for asu in asu_set if asu and data.asu_work_shift[dp_parameters.asu_decoder(asu)][next_shift] == 0)

    return min_time_to_death <= 0.5 or (min_time_to_death <= 1.25 and asu_work > 0)


"""Calculate the waiting time to open asu while truck is loaded"""


def wait_time_asu_open(asu_id: int, truck_id: int, data: StaticData, dp_parameters: DParameters):

    start_point = data.vehicles[truck_id].uet
    end_point = dp_parameters.asu_decoder(asu_id)
    distance = get_distance(start_point, end_point, data.distances_asu_uet)
    asu_work_start = data.asu_work_time[end_point][shift_number_calculation(dp_parameters.time)][0]
    return max(0, asu_work_start - distance)


def minimize_penalties_iter(penalty_set: dict, load_info: dict, dp_parameters: DParameters, data: StaticData, asu_in_model,
                            visited_asu: list, trips_on_the_truck: dict, iteration: int):

    import time as tt
    start = tt.time()

    m = Model('Trucks selection')
    asu_list = list(load_info.keys())  # asu to visit
    double_asu_list = get_double_asu(asu_list, dp_parameters)
    truck_set = set([extract_truck(val) for val in penalty_set])
    update_shifting_loads(dp_parameters)
    first_shifting_routes = [(truck, routes[0]) for truck, routes in dp_parameters.shifting_routes.items()]
    shifting_asu = [asu for routes in dp_parameters.shifting_routes.values() for route in routes for asu in route]

    var_set_direct = {}  # variables corresponds to one trip: x_asu_truck
    var_set_distribution = {}  # variables corresponds to one trip with distribution: y_asu1_asu2_truck
    var_set_direct_double = {}  # variables corresponds to two trip: z_asu1_asu2_truck
    var_set_distribution_double = {}  # variables corresponds to two trip: w_asu1_asu2_asu3_truck
    var_set_asu_visiting = {}  # variables corresponds to asu: asu_asu; 0 - not visiting, 1 - visiting
    var_set_depot_queue = {}
    var_set_asu_arrivals = {}
    var_set_restricts_excess = {}

    var_sum_asu_queue = {}
    var_sum_depot_queue = {}
    var_sum_two_truck_one_asu = {}  # two trips to one asu is first in double trip
    var_sum_two_truck_one_asu_2 = dict()  # two trips to one asu in second in double
    var_sum_two_truck_one_asu_loaded = dict()
    var_sum_depot_restricts = {}  # {(depot, depot_sku): volume * trip_var}
    var_sum_shifting = {}

    depot_queue_accuracy = dp_parameters.petrol_load_time / 5

    depot_work_decrease = work_decrease_to_interval(depot_queue_accuracy, data, dp_parameters)  # TODO если depot_queue_accuracy вынести в параметры модели, можно записать это в словарь dp_parameters.depot_queue_decrease

    """Create variables"""
    for (truck, route) in list(penalty_set) + first_shifting_routes:
        # одинарный рейс
        if len(route) == 1 and not ((truck, route) in first_shifting_routes and
                                    len(dp_parameters.shifting_routes[truck]) == 2 and
                                    len(dp_parameters.shifting_routes[truck][1]) == 2):
            asu1 = route[0]
            if False and dp_parameters.asu_decoder(asu1) in data.far_asu:
                if (truck, dp_parameters.time) not in data.vehicles_busy_hours and \
                        (truck, dp_parameters.time) not in data.vehicles_cut_off_shift:
                    x = m.binary_var(name='x_%d_%d' % (asu1, truck))
                    var_set_direct[asu1, truck] = x
                    # БВ загружена, нельзя две БВ на одну АЗС загружать под сменщика
                    if truck in dp_parameters.truck_loaded and asu1 in dp_parameters.encoder_decoder:
                        var_sum_two_truck_one_asu_loaded.setdefault(dp_parameters.asu_decoder(asu1), []).append(x)
                    add_to_depot_restricts(truck, ((asu1,),), x, var_sum_depot_restricts, dp_parameters, data)
                    # далёкие азс не рассматриваются в очереди!
            elif (truck, route) not in first_shifting_routes or len(dp_parameters.shifting_routes[truck]) == 1:
                trip_route = ((asu1,),)
                is_possible_route, load_time_bounds = any_trip_duration_check(data, dp_parameters, truck, *trip_route)
                if (truck, route) in first_shifting_routes and not is_possible_route:
                    print('НЕВОЗМОЖНЫЙ СЛУЧАЙ', truck, route)
                if is_possible_route:
                    x = m.binary_var(name='x_%d_%d' % (asu1, truck))
                    var_set_direct[asu1, truck] = x
                    if (truck, route) in first_shifting_routes:
                        var_sum_shifting.setdefault((truck, route), []).append(x)
                    # БВ загружена, нельзя две БВ на одну АЗС загружать под сменщика
                    if truck in dp_parameters.truck_loaded and asu1 in dp_parameters.encoder_decoder:
                        var_sum_two_truck_one_asu_loaded.setdefault(dp_parameters.asu_decoder(asu1), []).append(x)
                    var_depot_queue = {}
                    for trip in load_time_bounds:
                        if load_time_bounds[trip]:
                            trip_var_depot_queue = depot_queue_variables(m, truck, trip_route, trip - 1, load_time_bounds, depot_queue_accuracy,
                                                                    var_sum_depot_queue, data, dp_parameters)
                            var_depot_queue.update(trip_var_depot_queue)
                            m.add_constraint(m.sum(trip_var_depot_queue.values()) == var_set_direct[asu1, truck], ctname='xd_%d_%d_%d' % (asu1, truck, trip))
                    var_set_depot_queue.update(var_depot_queue)
                    if dp_parameters.asu_queue:
                        asu_queue = asu_queue_variables(m, x, truck, trip_route, var_depot_queue, double_asu_list,
                                                        depot_queue_accuracy, var_sum_asu_queue, dp_parameters, data)
                        var_set_asu_arrivals.update(asu_queue)
                    add_to_depot_restricts(truck, trip_route, x, var_sum_depot_restricts, dp_parameters, data)

                for asu2 in asu_list:
                    if asu2 != asu1 and trips_on_the_truck[truck] == 0:
                        trip_route = ((asu1,), (asu2,))
                        is_possible_route, load_time_bounds = any_trip_duration_check(data, dp_parameters, truck, *trip_route)
                        if is_possible_route:
                            z = m.binary_var(name='z_%d_%d_%d' % (asu1, asu2, truck))
                            var_set_direct_double[asu1, asu2, truck] = z
                            if (truck, route) in first_shifting_routes:
                                var_sum_shifting.setdefault((truck, route), []).append(z)
                            # На АЗС 2 рейса
                            if asu1 in dp_parameters.encoder_decoder:
                                var_sum_two_truck_one_asu.setdefault(dp_parameters.asu_decoder(asu1), []).append(z)
                                if truck in dp_parameters.truck_loaded:
                                    var_sum_two_truck_one_asu_loaded.setdefault(dp_parameters.asu_decoder(asu1), []).append(z)
                            if asu2 in dp_parameters.encoder_decoder:
                                var_sum_two_truck_one_asu_2.setdefault(dp_parameters.asu_decoder(asu2), []).append(z)
                            var_depot_queue = {}
                            for trip in load_time_bounds:
                                if load_time_bounds[trip]:
                                    trip_var_depot_queue = depot_queue_variables(m, truck, trip_route, trip - 1, load_time_bounds, depot_queue_accuracy,
                                                                            var_sum_depot_queue, data, dp_parameters)
                                    var_depot_queue.update(trip_var_depot_queue)
                                    m.add_constraint(m.sum(trip_var_depot_queue.values()) == var_set_direct_double[asu1, asu2, truck], ctname='zd_%d_%d_%d_%d' % (asu1, asu2, truck, trip))
                            cut_depot_load_queue_interval(m, var_depot_queue, load_time_bounds, depot_queue_accuracy)
                            var_set_depot_queue.update(var_depot_queue)
                            if dp_parameters.asu_queue:
                                asu_queue = asu_queue_variables(m, z, truck, trip_route, var_depot_queue, double_asu_list,
                                                                depot_queue_accuracy, var_sum_asu_queue, dp_parameters, data)
                                var_set_asu_arrivals.update(asu_queue)
                            add_to_depot_restricts(truck, trip_route, z, var_sum_depot_restricts, dp_parameters, data)
            # готовый рейс
            elif (truck, route) in first_shifting_routes and \
                    len(dp_parameters.shifting_routes[truck]) == 2 and \
                    len(dp_parameters.shifting_routes[truck][1]) == 1:
                asu2 = dp_parameters.shifting_routes[truck][1][0]
                trip_route = tuple(dp_parameters.shifting_routes[truck])
                is_possible_route, load_time_bounds = any_trip_duration_check(data, dp_parameters, truck, *trip_route)
                if not is_possible_route:
                    print('НЕВОЗМОЖНЫЙ СЛУЧАЙ', truck, trip_route)
                if is_possible_route:
                    z = m.binary_var(name='z_%d_%d_%d' % (asu1, asu2, truck))
                    var_set_direct_double[asu1, asu2, truck] = z
                    if (truck, route) in first_shifting_routes:
                        var_sum_shifting.setdefault((truck, trip_route), []).append(z)
                    # На АЗС 2 рейса
                    if asu1 in dp_parameters.encoder_decoder:
                        var_sum_two_truck_one_asu.setdefault(dp_parameters.asu_decoder(asu1), []).append(z)
                        if truck in dp_parameters.truck_loaded:
                            var_sum_two_truck_one_asu_loaded.setdefault(dp_parameters.asu_decoder(asu1), []).append(z)
                    if asu2 in dp_parameters.encoder_decoder:
                        var_sum_two_truck_one_asu_2.setdefault(dp_parameters.asu_decoder(asu2), []).append(z)
                    var_depot_queue = {}
                    for trip in load_time_bounds:
                        if load_time_bounds[trip]:
                            trip_var_depot_queue = depot_queue_variables(m, truck, trip_route, trip - 1, load_time_bounds, depot_queue_accuracy,
                                                                    var_sum_depot_queue, data, dp_parameters)
                            var_depot_queue.update(trip_var_depot_queue)
                            m.add_constraint(m.sum(trip_var_depot_queue.values()) == var_set_direct_double[asu1, asu2, truck], ctname='zd_%d_%d_%d_%d' % (asu1, asu2, truck, trip))
                    cut_depot_load_queue_interval(m, var_depot_queue, load_time_bounds, depot_queue_accuracy)
                    var_set_depot_queue.update(var_depot_queue)
                    if dp_parameters.asu_queue:
                        asu_queue = asu_queue_variables(m, z, truck, trip_route, var_depot_queue, double_asu_list,
                                                        depot_queue_accuracy, var_sum_asu_queue, dp_parameters, data)
                        var_set_asu_arrivals.update(asu_queue)
                    add_to_depot_restricts(truck, trip_route, z, var_sum_depot_restricts, dp_parameters, data)

        # рейс с развозом
        else:
            if (truck, route) not in first_shifting_routes or \
                    (len(dp_parameters.shifting_routes[truck]) == 1 and len(route) == 2):
                asu1 = route[0]
                asu2 = route[1]
                trip_route = ((asu1, asu2),)
                is_possible_route, load_time_bounds = any_trip_duration_check(data, dp_parameters, truck, *trip_route)
                if (truck, route) in first_shifting_routes and not is_possible_route:
                    print('НЕВОЗМОЖНЫЙ СЛУЧАЙ', truck, trip_route)
                if is_possible_route:
                    y = m.binary_var(name='y_%d_%d_%d' % (asu1, asu2, truck))
                    var_set_distribution[asu1, asu2, truck] = y
                    if (truck, route) in first_shifting_routes:
                        var_sum_shifting.setdefault((truck, trip_route), []).append(y)
                    if truck in dp_parameters.truck_loaded:
                        var_sum_two_truck_one_asu_loaded.setdefault(
                            dp_parameters.asu_decoder(asu1 if asu1 in dp_parameters.encoder_decoder else asu2), []).append(y)
                    var_depot_queue = {}
                    for trip in load_time_bounds:
                        if load_time_bounds[trip]:
                            trip_var_depot_queue = depot_queue_variables(m, truck, trip_route, trip - 1, load_time_bounds, depot_queue_accuracy,
                                                                    var_sum_depot_queue, data, dp_parameters)
                            var_depot_queue.update(trip_var_depot_queue)
                            m.add_constraint(m.sum(trip_var_depot_queue.values()) == var_set_distribution[asu1, asu2, truck], ctname='yd_%d_%d_%d_%d' % (asu1, asu2, truck, trip))
                    var_set_depot_queue.update(var_depot_queue)
                    if dp_parameters.asu_queue:
                        asu_queue = asu_queue_variables(m, y, truck, trip_route, var_depot_queue, double_asu_list,
                                                        depot_queue_accuracy, var_sum_asu_queue, dp_parameters, data)
                        var_set_asu_arrivals.update(asu_queue)
                    add_to_depot_restricts(truck, trip_route, y, var_sum_depot_restricts, dp_parameters, data)

                for asu3 in asu_list:
                    if asu3 != asu1 and asu3 != asu2:
                        trip_route = ((asu1, asu2), (asu3,))
                        is_possible_route, load_time_bounds = any_trip_duration_check(data, dp_parameters, truck, *trip_route)
                        if trips_on_the_truck[truck] == 0 and is_possible_route:
                            wd = m.binary_var(name='w_%d_%d_%d_%d' % (asu1, asu2, asu3, truck))
                            var_set_distribution_double[(*trip_route, truck)] = wd
                            if (truck, route) in first_shifting_routes:
                                var_sum_shifting.setdefault((truck, ((asu1, asu2),)), []).append(wd)
                            # На АЗС 2 рейса
                            if (asu1 in dp_parameters.encoder_decoder) or (asu2 in dp_parameters.encoder_decoder):
                                var_sum_two_truck_one_asu.setdefault(
                                    dp_parameters.asu_decoder(asu1 if asu1 in dp_parameters.encoder_decoder else asu2), []).append(wd)
                                if truck in dp_parameters.truck_loaded:
                                    var_sum_two_truck_one_asu_loaded.setdefault(dp_parameters.asu_decoder(asu1 if asu1 in dp_parameters.encoder_decoder else asu2), []).append(wd)
                            if asu3 in dp_parameters.encoder_decoder:
                                var_sum_two_truck_one_asu_2.setdefault(dp_parameters.asu_decoder(asu3), []).append(wd)
                            var_depot_queue = {}
                            for trip in load_time_bounds:
                                if load_time_bounds[trip]:
                                    trip_var_depot_queue = depot_queue_variables(m, truck, trip_route, trip - 1, load_time_bounds, depot_queue_accuracy,
                                                                            var_sum_depot_queue, data, dp_parameters)
                                    var_depot_queue.update(trip_var_depot_queue)
                                    m.add_constraint(m.sum(trip_var_depot_queue.values()) == var_set_distribution_double[(*trip_route, truck)], ctname='wd_%d_%d_%d_%d_%d' % (asu1, asu2, asu3, truck, trip))
                            cut_depot_load_queue_interval(m, var_depot_queue, load_time_bounds, depot_queue_accuracy)
                            var_set_depot_queue.update(var_depot_queue)
                            if dp_parameters.asu_queue:
                                asu_queue = asu_queue_variables(m, wd, truck, trip_route, var_depot_queue, double_asu_list,
                                                                depot_queue_accuracy, var_sum_asu_queue, dp_parameters, data)
                                var_set_asu_arrivals.update(asu_queue)
                            add_to_depot_restricts(truck, trip_route, wd, var_sum_depot_restricts, dp_parameters, data)

                        if (truck, route) in first_shifting_routes:
                            continue
                        trip_route = ((asu3,), (asu1, asu2))
                        is_possible_route, load_time_bounds = any_trip_duration_check(data, dp_parameters, truck, (asu3,), (asu1, asu2))
                        if trips_on_the_truck[truck] == 0 and is_possible_route:
                            rw = m.binary_var(name='rw_%d_%d_%d_%d' % (asu1, asu2, asu3, truck))
                            var_set_distribution_double[(*trip_route, truck)] = rw
                            # На АЗС 2 рейса
                            if asu3 in dp_parameters.encoder_decoder:
                                var_sum_two_truck_one_asu.setdefault(dp_parameters.asu_decoder(asu3), []).append(rw)
                                if truck in dp_parameters.truck_loaded:
                                    var_sum_two_truck_one_asu_loaded.setdefault(dp_parameters.asu_decoder(asu3), []).append(rw)
                            if (asu1 in dp_parameters.encoder_decoder) or (asu2 in dp_parameters.encoder_decoder):
                                var_sum_two_truck_one_asu.setdefault(
                                    dp_parameters.asu_decoder(asu1 if asu1 in dp_parameters.encoder_decoder else asu2), []).append(rw)
                            var_depot_queue = {}
                            for trip in load_time_bounds:
                                if load_time_bounds[trip]:
                                    trip_var_depot_queue = depot_queue_variables(m, truck, trip_route, trip - 1, load_time_bounds, depot_queue_accuracy,
                                                                            var_sum_depot_queue, data, dp_parameters)
                                    var_depot_queue.update(trip_var_depot_queue)
                                    m.add_constraint(m.sum(trip_var_depot_queue.values()) == var_set_distribution_double[(*trip_route, truck)], ctname='rwd_%d_%d_%d_%d_%d' % (asu1, asu2, asu3, truck, trip))
                            cut_depot_load_queue_interval(m, var_depot_queue, load_time_bounds, depot_queue_accuracy)
                            var_set_depot_queue.update(var_depot_queue)
                            if dp_parameters.asu_queue:
                                asu_queue = asu_queue_variables(m, rw, truck, trip_route, var_depot_queue, double_asu_list,
                                                                depot_queue_accuracy, var_sum_asu_queue, dp_parameters, data)
                                var_set_asu_arrivals.update(asu_queue)
                            add_to_depot_restricts(truck, trip_route, rw, var_sum_depot_restricts, dp_parameters, data)
            # готовый рейс
            else:
                trip_route = tuple(dp_parameters.shifting_routes[truck])
                asu1, asu2, asu3 = [asu for route in trip_route for asu in route]
                is_possible_route, load_time_bounds = any_trip_duration_check(data, dp_parameters, truck, *trip_route)
                if not is_possible_route:
                    print('НЕВОЗМОЖНЫЙ СЛУЧАЙ', truck, trip_route)
                if trips_on_the_truck[truck] == 0 and is_possible_route:
                    wd = m.binary_var(name='w_%d_%d_%d_%d' % (asu1, asu2, asu3, truck))
                    var_set_distribution_double[(*trip_route, truck)] = wd
                    if (truck, route) in first_shifting_routes:
                        var_sum_shifting.setdefault((truck, trip_route), []).append(wd)
                    # На АЗС 2 рейса
                    if len(route) == 2:
                        if (asu1 in dp_parameters.encoder_decoder) or (asu2 in dp_parameters.encoder_decoder):
                            var_sum_two_truck_one_asu.setdefault(
                                dp_parameters.asu_decoder(asu1 if asu1 in dp_parameters.encoder_decoder else asu2), []).append(wd)
                            if truck in dp_parameters.truck_loaded:
                                var_sum_two_truck_one_asu_loaded.setdefault(dp_parameters.asu_decoder(asu1 if asu1 in dp_parameters.encoder_decoder else asu2), []).append(wd)
                        if asu3 in dp_parameters.encoder_decoder:
                            var_sum_two_truck_one_asu_2.setdefault(dp_parameters.asu_decoder(asu3), []).append(wd)
                    else:
                        if asu1 in dp_parameters.encoder_decoder:
                            var_sum_two_truck_one_asu.setdefault(dp_parameters.asu_decoder(asu1), []).append(wd)
                            if truck in dp_parameters.truck_loaded:
                                var_sum_two_truck_one_asu_loaded.setdefault(dp_parameters.asu_decoder(asu3), []).append(wd)
                        if (asu2 in dp_parameters.encoder_decoder) or (asu3 in dp_parameters.encoder_decoder):
                            var_sum_two_truck_one_asu.setdefault(
                                dp_parameters.asu_decoder(asu2 if asu2 in dp_parameters.encoder_decoder else asu3), []).append(wd)
                    var_depot_queue = {}
                    for trip in load_time_bounds:
                        if load_time_bounds[trip]:
                            trip_var_depot_queue = depot_queue_variables(m, truck, trip_route, trip - 1, load_time_bounds, depot_queue_accuracy,
                                                                    var_sum_depot_queue, data, dp_parameters)
                            var_depot_queue.update(trip_var_depot_queue)
                            m.add_constraint(m.sum(trip_var_depot_queue.values()) == var_set_distribution_double[(*trip_route, truck)], ctname='wd_%d_%d_%d_%d_%d' % (asu1, asu2, asu3, truck, trip))
                    cut_depot_load_queue_interval(m, var_depot_queue, load_time_bounds, depot_queue_accuracy)
                    var_set_depot_queue.update(var_depot_queue)
                    if dp_parameters.asu_queue:
                        asu_queue = asu_queue_variables(m, wd, truck, trip_route, var_depot_queue, double_asu_list,
                                                        depot_queue_accuracy, var_sum_asu_queue, dp_parameters, data)
                        var_set_asu_arrivals.update(asu_queue)
                    add_to_depot_restricts(truck, trip_route, wd, var_sum_depot_restricts, dp_parameters, data)

    for asu in asu_list:
        if asu not in asu_in_model:
            continue
        var_set_asu_visiting[asu] = m.binary_var(name='asu_%d' % asu)
        if not dp_parameters.asu_non_visiting_penalties_obj:
            var_set_asu_visiting[asu] = 1

    """Constraint: one truck for can be assigned to: 
                                                    a) One asu trip
                                                    b) Trip with distribution
                                                    c) Two asu trip
                                                    c) Double distribution trip"""
    for truck in truck_set:
        m.add_constraint_(m.sum(var_set_direct[asu, truck_iter] for (asu, truck_iter) in var_set_direct if truck_iter == truck) +
                          m.sum(var_set_distribution[asu1, asu2, truck_iter] for (asu1, asu2, truck_iter) in var_set_distribution if
                                truck_iter == truck) +
                          m.sum(var_set_direct_double[asu1, asu2, truck_iter] for (asu1, asu2, truck_iter) in var_set_direct_double if
                                truck_iter == truck) +
                          m.sum(var_set_distribution_double[asu12, asu34, truck_iter] for (asu12, asu34, truck_iter) in
                                var_set_distribution_double if truck_iter == truck)
                          <= 1, ctname='One_truck_one_asu_%d' % truck)
        # TODO should be 1 for self trucks

    """Constraint: each shifting route should be done"""
    for (truck, route), vars in var_sum_shifting.items():
        m.add_constraint_(m.sum(vars) == 1, ctname='Shifting_should_be_served_%d_%s' % (truck, route))

    """Constraint: each asu should be served by one trip"""
    for asu in asu_in_model:
        if asu in asu_list:
            m.add_constraint_(m.sum(var_set_direct[asu1, truck] for (asu1, truck) in var_set_direct if asu1 == asu) +
                              m.sum(var_set_distribution[asu1, asu2, truck] for (asu1, asu2, truck) in var_set_distribution if
                                    asu1 == asu or asu2 == asu) +
                              m.sum(var_set_direct_double[asu1, asu2, truck] for (asu1, asu2, truck) in var_set_direct_double if
                                    asu1 == asu or asu2 == asu) +
                              m.sum(var_set_distribution_double[asu12, asu34, truck] for (asu12, asu34, truck) in var_set_distribution_double
                                    if asu in asu12 or asu in asu34)
                              == var_set_asu_visiting[asu], ctname='Asu_should_be_served_%d' % asu)
        else:
            m.add_constraint_(m.sum(var_set_direct[asu1, truck] for (asu1, truck) in var_set_direct if asu1 == asu) +
                              m.sum(var_set_distribution[asu1, asu2, truck] for (asu1, asu2, truck) in var_set_distribution if
                                    asu1 == asu or asu2 == asu) +
                              m.sum(var_set_direct_double[asu1, asu2, truck] for (asu1, asu2, truck) in var_set_direct_double if
                                    asu1 == asu or asu2 == asu) +
                              m.sum(var_set_distribution_double[asu12, asu34, truck] for (asu12, asu34, truck) in var_set_distribution_double
                                    if asu in asu12 or asu in asu34)
                              <= 1, ctname='Asu_should_be_served_%d' % asu)

    """Constraint: queue on depot should be less than depot capacity"""
    for depot, time in var_sum_depot_queue:
        time_str = ('_' if time < 0 else '') + str(abs(time))
        m.add_constraint_(m.sum(var_sum_depot_queue[depot, time]) <=
                          max(0, data.depot_capacity[depot] - dp_parameters.depot_queue_decrease.get((depot, time), 0) -
                          depot_work_decrease.get((depot, time), 0)),
                          ctname='Depot_queue_%d_%s' % (depot, time_str))

    """Constraint: queue on asu must not be more than one"""
    for asu, time_list in var_sum_asu_queue.items():
        for interval in time_list:
            m.add_constraint_(m.sum(var_sum_asu_queue[asu][interval]) <= 1, ctname='Asu_queue_%d_%d' % (asu, interval))

    """Constraint: two trips to one asu not allowed"""
    for asu, list_vals in var_sum_two_truck_one_asu.items():
        m.add_constraint_(m.sum(list_vals) <= 1,  ctname='Two_truck_one_asu_%d' % asu)

    for asu, list_vals in var_sum_two_truck_one_asu_2.items():
        m.add_constraint_(m.sum(list_vals) <= 1,  ctname='Two_truck_one_asu_2_%d' % asu)

    """Constraint: excess depot restricts"""
    day = (dp_parameters.time + 1) // 2
    for (depot, depot_sku), vars in var_sum_depot_restricts.items():
        excess_var = m.continuous_var(name='Depot_restrict_excess_%d_%d' % (depot, depot_sku))
        deficit_coef = 1 if depot_sku in data.sku_deficit.get(depot, []) \
            else (1 + dp_parameters.free_not_deficit_restrict_excess_part)
        m.add_constraint_(m.sum(vars) <= data.restricts[depot, depot_sku, day] * deficit_coef + excess_var,
                          ctname='Depot_restrict_constr_%d_%d' % (depot, depot_sku))
        var_set_restricts_excess[depot, depot_sku] = excess_var / (data.restricts[depot, depot_sku, day]
                                                                   if data.restricts[depot, depot_sku, day] > 1 else 2)

    # TODO Загрузка под сменщика: нельзя две БВ ставить на одну АЗС если они загружены под сменщика. Может быть печально в определенных ситуациях
    for asu, list_vals in var_sum_two_truck_one_asu_loaded.items():
        m.add_constraint_(m.sum(list_vals) <= 1,  ctname='Two_truck_one_asu_loaded_%d' % asu)

    """Objective function:
        - Load penalties
        - Own trucks use priority
        - Double trip increase 
        - Turnaround increase
        - Asu not visiting penalties
        - Double trip with semideath asu in each"""

    m.minimize(objective_generator(dp_parameters=dp_parameters,
                                   var_set_direct=var_set_direct,
                                   var_set_distribution=var_set_distribution,
                                   var_set_direct_double=var_set_direct_double,
                                   var_set_distribution_double=var_set_distribution_double,
                                   var_set_asu_visiting=var_set_asu_visiting,
                                   var_set_restricts_excess=var_set_restricts_excess,
                                   penalty_set=penalty_set,
                                   distances=data.distances_asu_depot,
                                   far_asu=data.far_asu,
                                   asu_work_shift=data.asu_work_shift,
                                   busy_truck=data.vehicles_busy_hours,
                                   data=data,
                                   truck_in_use=trips_on_the_truck))

    print("End to create minimization problem model shift = %d, (%d)" % (dp_parameters.time, tt.time() - start))

    """Run optimization"""

    print("Start solve penalties minimization problem shift = %d" % dp_parameters.time)

    m.export_as_lp('./output/trip_optimization/Trip_optimization_%d_iter_%.1f.lp' % (dp_parameters.time, iteration))

    m.parameters.mip.tolerances.mipgap = 0.005
    m.parameters.timelimit = 50

    # m.parameters.preprocessing.presolve = 0
    m.log_output = True

    start = tt.time()
    result = m.solve()

    # Reliability
    it_add = 1
    if not result:
        if it_add >= 4:
            print('Problem: Sorry, the problem is unsolved due to data values')
            print("<FOR_USER>\nНЕ НАЙДЕНО решение Trip_optimization. Большое количество БВ в расчете.\n</FOR_USER>")
            exit(1)
        print('The additional iteration for trip_optimization: iteration %d' % it_add)
        m.parameters.timelimit = 100
        m.solve()
        it_add += 1

    '''Bug report in LP'''
    if not result:
        print('Problem in trip_optimization_%d_iter_%.1f' % (dp_parameters.time, iteration))
        m.export_as_lp('Trip_optimization.lp')

    for key, var in var_set_asu_visiting.items():
        print(var.name, var.solution_value)

    print("End to solve penalties minimization problem shift = %d, (%d seconds)" % (dp_parameters.time, tt.time() - start))

    """Get result"""

    set_direct = get_optimization_result(var_set_direct)  # results corresponds to one trip: x_asu_truck
    """Update long trip vehicles availability"""
    update_vehicles_busy_status(data, set_direct, dp_parameters)
    set_distribution = get_optimization_result(var_set_distribution)  # results corresponds to one trip with distribution: y_asu1_asu2_truck
    set_direct_double = get_optimization_result(var_set_direct_double)  # results corresponds to two trip: z_asu1_asu2_truck
    set_distribution_double = get_optimization_result(var_set_distribution_double)  # results corresponds to two trip: w_asu1_asu2_truck
    depot_queue = get_optimization_result(var_set_depot_queue)

    """Collect all visiting asu"""
    for asu1, truck in set_direct:
        visited_asu.append(asu1)
    for asu1, asu2, truck in set_distribution:
        visited_asu.extend((asu1, asu2))
    for asu1, asu2, truck in set_direct_double:
        visited_asu.extend((asu1, asu2))
    for asu12, asu34, truck in set_distribution_double:
        visited_asu.extend((*asu12, *asu34))

    vehicle_blocks, asu_blocks, depot_blocks, depot_queue = \
        define_blocks(set_direct, set_distribution, set_direct_double, set_distribution_double,
                      depot_queue, depot_queue_accuracy, dp_parameters, data)

    set_distribution_double = {((*asu12, *asu34, truck) if len(asu12) == 2 else (*asu34, *asu12, truck)):
                               value for (asu12, asu34, truck), value in set_distribution_double.items()}
    depot_queue = [(depot, round(time_interval * depot_queue_accuracy, 1), truck, route, trip_number)
                   for depot, time_interval, truck, route, trip_number in depot_queue]

    data.vehicles_busy_hours.update(vehicle_blocks)
    data.block_window_asu.update({key: val + data.block_window_asu.get(key, []) for key, val in asu_blocks.items()})
    dp_parameters.depot_queue_decrease.update({key: val + dp_parameters.depot_queue_decrease.get(key, 0)
                                               for key, val in depot_blocks.items()})

    return set_direct, set_distribution, set_direct_double, set_distribution_double, depot_queue
