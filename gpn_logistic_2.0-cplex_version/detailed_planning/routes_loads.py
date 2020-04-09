from detailed_planning.sections_permutation import load_permutations
from detailed_planning.dp_parameters import DParameters
from detailed_planning.route_generator import route_generator as route_gen, route_duration_calculation
from data_reader.input_data import StaticData, Parameters
from detailed_planning.best_truck_load_linear import best_truck_load_linear, define_depot
from detailed_planning.trip_optimization import is_asu_set_death
from models_connector.integral_detailed_connector import ModelsConnector
from data_reader.input_data import get_distance
import time

"""Intro:
    - best_truck_load_linear and best_truck_load same usage but different algorithms
    - every_truck_load_parallel and every_truck_load same functions, but first one is parallelized"""


'''Information about route:
    - asu_id in the route
    - asu_tanks to be filled
    - volumes from integral model for approximation
    - empty space into the tank
    - possible truck set and their section sizes'''


class TruckLoadParameters:
    def __init__(self, route, asu_tanks, first_model_volumes, empty_spaces, truck_set):
        self.route = route  # (asu1, asu2) --- маршрут по АЗС
        self.asu_tanks = asu_tanks  # {asu1: [(asu1, n1), (asu1, n2),...], ...} --- типы НП для привоза
        self.first_model_volumes = first_model_volumes  # {(asu1, n1): vol, ...} --- объемы НП по типам из интегральной модели
        self.empty_spaces = empty_spaces  # {(asu1, n1): vol, ...} --- свободный объем в баках
        self.truck_set = truck_set  # {1: [sec1, sec2, ...], ...} --- объемы секций машин


# Get the integral model load from storage
def extract_integral_load(vols: list):
    return vols[0]


# Get the empty space from storage
def extract_empty_space(vols: list):
    return vols[1]


# Parse data into the TruckLoadParameters format
def truck_load_parameter_generator(route, load_info):

    asu_tanks = {}  # {asu_id: list(load_info[asu_id].keys()) for asu_id in route}
    first_model_volumes = {}
    empty_spaces = {}
    for asu_id in route:
        asu_tanks[asu_id] = list(load_info[asu_id].keys())
        for tank in asu_tanks[asu_id]:
            first_model_volumes[tank] = extract_integral_load(load_info[asu_id][tank])
            empty_spaces[tank] = extract_empty_space(load_info[asu_id][tank])

    return asu_tanks, first_model_volumes, empty_spaces


# Check: load corresponds to route
def check_load(load_sequence, route):
    sequence_asus = set(asu_n[0] for asu_n in load_sequence if asu_n)
    is_ok_load = all(asu in sequence_asus for asu in route)
    # if not is_ok_load:
    #     print('Удалён рейс с развозом из-за загрузки только на одну АЗС:', route)
    return is_ok_load


"""Algorithm for truck load planning
    - different load sequences planning"""


def truck_load(load_sequence: list, volumes_to_load: list, truck_sections: list, asu_empty_spaces: list):
    """Data validation:
        len(load_sequence) == len(volumes_to_load) == len(asu_empty_spaces)
        len(truck_sections) >= len(load_sequence)"""
    """Data description: 
        - load_sequence: [(asu1, n1), (asu1, n2), (asu2,n4), ...] - Sequence of loads
        - volumes_to_load: [10000.0, 21053.1, ...] - Volumes needed to be loaded. Tanks corresponds to load_sequence
        - truck_sections: [5600, 9000, 3400, ...] - Volumes of truck sections, starting from the end
        - asu_empty_spaces: [1932, 500, ...] - Empty space in the tanks. Tanks corresponds to load_sequence"""

    section_fulfilled = []  # [(asu, n), ...] --- погруженные в БВ
    truck_load_by_np = [0] * len(load_sequence)  # [vol1, vol2, ...] -- объемы НП погруженные в БВ соответствуют load_sequence
    truck_sections_copy = truck_sections.copy()

    for flow_plan_num in range(len(load_sequence)):

        flow_current = volumes_to_load[flow_plan_num]  # сколько нужно компенсировать
        empty_space_current = asu_empty_spaces[flow_plan_num]  # свободное место
        flow_loaded = 0  # сколько загружено

        # Для каждой секции планируем загрузку
        for section in truck_sections_copy:
            if section <= empty_space_current and len(truck_sections_copy) > 0:  # Если секция меньше чем свободное место на АЗС
                """ - If section is less than fuel is needed to load: section load
                    - Else If the considered section and fuel type are last: section load
                    - Else if section is larger than fuel is needed to load:
                        - If section is last: section load
                        - Else if sum of load volume needed to plan is less than sum of empty section volume: 
                            - If fuel types to be loaded is less than amount of empty sections: section load
                        - Else if load of fuel type is 0: section load"""
                if section <= flow_current - flow_loaded:  # Если объем секции меньше чем необходимый объем для доставки
                    # load_iteration_updates(empty_space_current, section_fulfilled, flow_loaded, truck_sections_copy, section,
                    #                        load_sequence[section])
                    flow_loaded += section  # Секция заполняется
                    section_fulfilled.append(load_sequence[flow_plan_num])  # фиксируется тип НП и АЗС при заполнении
                    empty_space_current -= section  # корректируем свободный объем на АЗС
                    truck_sections_copy = truck_sections_copy[1:]  # секция заполнена, убираем из рассмотрения

                elif len(truck_sections_copy) == 1 and flow_plan_num == len(volumes_to_load) - 1:  # если последняя секция и последний тип топлива для распределения (то заливаем все)
                    empty_space_current -= section
                    section_fulfilled.append(load_sequence[flow_plan_num])
                    flow_loaded += section
                    truck_sections_copy = truck_sections_copy[1:]
                    break

                else:  # flow_current - flow_loaded <= section:

                    if flow_plan_num == len(volumes_to_load) - 1:  # если направление последнее, то грузим
                        empty_space_current -= section
                        section_fulfilled.append(load_sequence[flow_plan_num])
                        flow_loaded += section
                        truck_sections_copy = truck_sections_copy[1:]
                        break

                    elif sum(volumes_to_load[flow_plan_num + 1:]) <= sum(truck_sections_copy[1:]):  # Если объем для перевоза меньше чем оставшиеся секции

                        if len(volumes_to_load[flow_plan_num + 1:]) <= len(truck_sections_copy[1:]):  # Если количество типов НП для поставки меньше количества секций
                            empty_space_current -= section
                            section_fulfilled.append(load_sequence[flow_plan_num])
                            flow_loaded += section
                            truck_sections_copy = truck_sections_copy[1:]

                        elif flow_loaded == 0:
                            empty_space_current -= section
                            section_fulfilled.append(load_sequence[flow_plan_num])
                            flow_loaded += section
                            truck_sections_copy = truck_sections_copy[1:]
                            break

                    elif flow_loaded == 0:
                        empty_space_current -= section
                        section_fulfilled.append(load_sequence[flow_plan_num])
                        flow_loaded += section
                        truck_sections_copy = truck_sections_copy[1:]
                        break
                    else:
                        break
            else:
                break

        if flow_loaded != 0:
            truck_load_by_np[flow_plan_num] = flow_loaded
        else:
            if len(truck_sections) > len(section_fulfilled):
                section_fulfilled.append(0)  # no fuel type loaded
                truck_sections_copy = truck_sections_copy[1:]
            else:
                break

    '''If the last sections isn't loaded and load_sequence is filled'''
    while len(truck_sections) > len(section_fulfilled):
        section_fulfilled.append(0)  # no fuel type loaded

    """returns: [float, float, ...], [(asu_id1, n1), (asu_id2, n2), ...]"""
    return truck_load_by_np, section_fulfilled


"""Criteria for load quality estimation
    - Penalty of unfollow the recommendations of integral model
    - Penalty for empty section"""


def load_quality_estimation(volumes_loaded, volumes_forecasted, sections_busy, truck_sections, dp_parameters: DParameters):
    """Input data description:
        - volumes_loaded: [9580.0, 8650.0, 11345.0] --- volumes placed into the truck
        - volumes_forecasted: [5787.0, 22878.8, 8630.0] --- volumes planned to be placed from integral planning
        - sections_busy: [(10028, 4), (10028, 3), (10028, 3), (10028, 3), (10028, 2)] --- type of fuel loaded into the section
        - truck_sections: [5300.0, 4000.0, 6000.0, 7000.0, 10000.0] --- size of every section in truck
        - dp_parameters --- set of weights for quality function"""

    result = 0

    for index in range(len(volumes_loaded)):
        result += max(volumes_forecasted[index] - volumes_loaded[index], 0) * dp_parameters.lack_loading_weight  # штраф за недолив
        result += max(volumes_loaded[index] - volumes_forecasted[index], 0) * dp_parameters.overloading_weight  # штраф за перелив

    result += (len(truck_sections) - len([asu_n for asu_n in sections_busy if asu_n != 0])) * dp_parameters.empty_section_weight

    """Return the load quality"""
    return result


"""Most qualitative load of the truck"""


def best_truck_load(load_parameters: TruckLoadParameters, truck_sections: list, dp_parameters: DParameters):
    combinations = load_permutations(load_parameters.route, load_parameters.asu_tanks)
    best_quality = 10 ** 10
    best_truck_load_volumes = []
    best_section_fulfilled = []

    for combination in combinations:

        volumes_to_load = [load_parameters.first_model_volumes[val] for val in combination]
        asu_empty_spaces = [load_parameters.empty_spaces[val] for val in combination]

        volumes_loaded_in_truck, section_fulfilled = truck_load(combination,
                                                                volumes_to_load,
                                                                truck_sections,
                                                                asu_empty_spaces)

        combinations_quality = load_quality_estimation(volumes_loaded_in_truck,
                                                       volumes_to_load,
                                                       section_fulfilled,
                                                       truck_sections,
                                                       dp_parameters)
        if combinations_quality < best_quality:
            best_quality = combinations_quality
            best_truck_load_volumes = volumes_loaded_in_truck
            best_section_fulfilled = section_fulfilled

    """Returns: int, [float, float, ...], [(asu_id1, n1), (asu_id2, n2), ...]"""

    return best_quality, best_truck_load_volumes, best_section_fulfilled


def asu_n_list_decoder(asu_tanks, dp_parameters: DParameters):
    tanks = []
    """Asu_n decoding"""
    for asu in asu_tanks:
        asu_n_decoded = [dp_parameters.asu_n_decoder(asu_n) for asu_n in asu_tanks[asu]]
        tanks.extend(asu_n_decoded)

    return tanks


def every_truck_load(load_parameters: TruckLoadParameters, dp_parameters: DParameters,
                     integral_data: ModelsConnector, data: StaticData, calculate_load=True):

    penalty_set = {}
    truck_load_volumes = {}
    truck_load_sequence = {}
    route_depot = {}

    depot = define_depot(list(load_parameters.first_model_volumes), integral_data.data, integral_data.dp_parameters)

    for truck in load_parameters.truck_set:
        if (truck, dp_parameters.time) not in data.vehicles_busy:
            if data.depot_vehicles_compatibility(truck, depot):
                if all([data.asu_vehicles_compatibility(truck, dp_parameters.asu_decoder(asu_id)) for asu_id in load_parameters.route]):
                    if calculate_load:
                        penalty, load_volumes, load_sequence = \
                            best_truck_load_linear(load_parameters, integral_data, truck, depot, dp_parameters, data)
                        if check_load(load_sequence, load_parameters.route):
                            key = truck, load_parameters.route
                            penalty_set[key], truck_load_volumes[key], truck_load_sequence[key], route_depot[key] = \
                                penalty, load_volumes, load_sequence, depot
                    else:
                        key = truck, load_parameters.route
                        penalty_set[key] = 'заглушка'

    """Returns: : {(truck, route): float}, {(truck, route): [float, float, ...]}, {(truck, route): [(asu_id1, n1), (asu_id2, n2), ...]}"""

    return penalty_set, truck_load_volumes, truck_load_sequence, route_depot


"""Process distribution in every_truck_load"""


def every_truck_load_parallel(load_parameters: TruckLoadParameters, dp_parameters: DParameters,
                              integral_data: ModelsConnector, pool, data: StaticData):

    penalty_set = {}
    truck_load_volumes = {}
    truck_load_sequence = {}
    depot_dict = {}

    best_truck_load_param = []
    keys = []

    for truck in load_parameters.truck_set:
        if (truck, dp_parameters.time) not in data.vehicles_busy or truck in dp_parameters.truck_loaded:
            if all([data.asu_vehicles_compatibility(truck, dp_parameters.asu_decoder(asu_id)) for asu_id in load_parameters.route]):
                best_truck_load_param.append((load_parameters, integral_data, truck, dp_parameters, data))
                keys.append((truck, load_parameters.route))

    result_truck_load = pool.starmap(best_truck_load_linear, best_truck_load_param)

    for key, value in zip(keys, result_truck_load):
        penalty, load_volumes, load_sequence, depot = value
        if check_load(load_sequence, load_parameters.route):
            penalty_set[key], truck_load_volumes[key], truck_load_sequence[key], depot_dict[key] = value

    """Returns: : {(truck, route): int}, {(truck, route): [float, float, ...]}, {(truck, route): [(asu_id1, n1), (asu_id2, n2), ...]}"""

    return penalty_set, truck_load_volumes, truck_load_sequence, depot_dict


"""Generate all possible loads for each truck and route
    - All combinations of load
    - All trucks and route
    - Empty space included
    - Integral model solution as landmark"""


def every_route_load(truck_set: dict, integral_data: ModelsConnector, dp_parameters: DParameters,
                     data: StaticData, parameters: Parameters, asu_group: list = None):
    """Data description:
        - load_info: {asu_id: {(asu_id, n): [integral load, empty space)] ...} ... }
        - truck_set: {truck_num: [section_vol1, ...], }"""

    asu_to_visit = asu_group or list(dp_parameters.load_info.keys())  # set of asu to be visited

    route_set = route_gen(asu_to_visit, data, parameters, dp_parameters)

    penalty_set, truck_load_volumes, truck_load_sequence = {}, {}, {}

    print('=========================== Truck load Start =========================')
    start_time = time.time()
    for route in route_set:
        # if len(route) > 1 and get_depot_allocation(route, data, dp_parameters):
        #     return TODO Filter
        asu_tanks, first_model_volumes, empty_spaces = truck_load_parameter_generator(route, dp_parameters.load_info)

        load_parameters = TruckLoadParameters(route=route,
                                              asu_tanks=asu_tanks,
                                              first_model_volumes=first_model_volumes,
                                              empty_spaces=empty_spaces,
                                              truck_set=truck_set)

        penalty_set_route, truck_load_volumes_route, truck_load_sequence_route, depot_dict = \
            every_truck_load_parallel(load_parameters, dp_parameters, integral_data, parameters.pool, data)

        penalty_set.update(penalty_set_route)
        truck_load_volumes.update(truck_load_volumes_route)
        truck_load_sequence.update(truck_load_sequence_route)
        dp_parameters.route_depots.update(depot_dict)
    duration_sol = time.time() - start_time
    print('=========================== Truck load time = %d =========================' % duration_sol)

    add_distribution_for_empty_section_routes(asu_group, penalty_set, truck_load_volumes, truck_load_sequence,
                                              integral_data, dp_parameters, data, parameters)

    update_load_info(truck_load_sequence, dp_parameters)

    return penalty_set, truck_load_volumes, truck_load_sequence


"""Generate all possible loads for each truck and route
    - All combinations of load
    - All trucks and route
    - Empty space included
    - Integral model solution as landmark"""


def every_route_load_parallel(truck_set: dict, integral_data: ModelsConnector, dp_parameters: DParameters,
                              data: StaticData, parameters: Parameters, asu_group: list = None, calculate_loads=True):
    """Data description:
        - load_info: {asu_id: {(asu_id, n): [integral load, empty space)] ...} ... }
        - truck_set: {truck_num: [section_vol1, ...], }"""

    asu_to_visit = asu_group or list(dp_parameters.load_info.keys())  # set of asu to be visited

    route_set = route_gen(asu_to_visit, data, parameters, dp_parameters)

    penalty_set, truck_load_volumes, truck_load_sequence = {}, {}, {}

    print('=========================== Truck load Start =========================')
    start_time = time.time()

    every_truck_load_param = []
    print(route_set)
    for route in route_set:
        # if len(route) > 1 and get_depot_allocation(route, data, dp_parameters):
        #     return TODO Filter
        asu_tanks, first_model_volumes, empty_spaces = truck_load_parameter_generator(route, dp_parameters.load_info)

        load_parameters = TruckLoadParameters(route=route,
                                              asu_tanks=asu_tanks,
                                              first_model_volumes=first_model_volumes,
                                              empty_spaces=empty_spaces,
                                              truck_set=truck_set)

        every_truck_load_param.append((load_parameters, dp_parameters, integral_data, data, calculate_loads))

    result_truck_load = parameters.pool.starmap(every_truck_load, every_truck_load_param)

    for penalty_set_route, truck_load_volumes_route, truck_load_sequence_route, depot_dict in result_truck_load:
        penalty_set.update(penalty_set_route)
        truck_load_volumes.update(truck_load_volumes_route)
        truck_load_sequence.update(truck_load_sequence_route)
        dp_parameters.route_depots.update(depot_dict)

    if calculate_loads:
        add_distribution_for_empty_section_routes(asu_to_visit, penalty_set, truck_load_volumes, truck_load_sequence,
                                                  integral_data, dp_parameters, data, parameters)
        update_load_info(truck_load_sequence, dp_parameters)

    duration_sol = time.time() - start_time
    print('=========================== Truck load time = %d =========================' % duration_sol)

    return penalty_set, truck_load_volumes, truck_load_sequence


"""Add distribution asu for route with empty spaces"""


def add_distribution_for_empty_section_routes(asu_to_visit, penalty_set, truck_load_volumes, truck_load_sequence,
                                                  integral_data, dp_parameters, data: StaticData, parameters: Parameters):  # TODO ускорить
    asu_set = set(asu for asu, n in data.initial_fuel_state)
    integral_asus = set(dp_parameters.asu_decoder(asu) for asu in dp_parameters.load_info)

    bad_truck_routes = []
    bad_routes_set = set()

    def check_possible_routes(renamed_asu, possible_asu, full_matrix, reverse=False):
        possible_routes = []
        asu_versions = (0, 1, 2, 3, 4)

        if possible_asu == renamed_asu:
            return possible_routes

        asu = dp_parameters.asu_decoder(renamed_asu)
        route = (possible_asu, asu) if reverse else (asu, possible_asu)

        if not full_matrix and not (route[1] in data.distributions.get(route[0], []) or possible_asu == asu):
            return possible_routes

        if full_matrix and (route[1] in data.distributions.get(route[0], []) or possible_asu == asu):
            return possible_routes

        if possible_asu not in integral_asus:
            renamed_route = (possible_asu, renamed_asu) if reverse else (renamed_asu, possible_asu)
            if route_duration_calculation(*renamed_route, dp_parameters.time, data, parameters,
                                          dp_parameters, dp_parameters.shift_size):
                possible_routes.append(renamed_route)
        else:
            for version in asu_versions:
                version_possible_asu = possible_asu + version * 10000000
                if version_possible_asu == renamed_asu:
                    continue
                if version_possible_asu in dp_parameters.load_info and \
                   (version_possible_asu not in asu_to_visit or full_matrix):
                        renamed_route = (version_possible_asu, renamed_asu) if reverse \
                            else (renamed_asu, version_possible_asu)
                        if route_duration_calculation(*renamed_route, dp_parameters.time, data, parameters,
                                                      dp_parameters, dp_parameters.shift_size):
                            possible_routes.append(renamed_route)
        return possible_routes

    def get_possible_routes(full_matrix=False):
        possible_distribution_map = {}

        for route in bad_routes_set:
            renamed_asu = route[0]
            asu = dp_parameters.asu_decoder(renamed_asu)
            possible_distribution_list = []
            accepted_distribution_to = set(data.distributions.get(route[0], []))
            accepted_distribution_from = set(a for a in asu_set if asu in data.distributions.get(a, []))
            accepted_distribution = accepted_distribution_to.union(accepted_distribution_from)
            accepted_distribution.intersection_update(asu_set)
            accepted_distribution.add(asu)
            full_matrix_distribution = asu_set - (accepted_distribution_to.intersection(accepted_distribution_from))
            asu in full_matrix_distribution and full_matrix_distribution.remove(asu)
            possible_asus = full_matrix_distribution if full_matrix else accepted_distribution

            for possible_asu in possible_asus:
                possible_routes = check_possible_routes(renamed_asu, possible_asu, full_matrix)
                possible_distribution_list.extend(possible_routes)
                possible_routes = check_possible_routes(renamed_asu, possible_asu, full_matrix, reverse=True)
                possible_distribution_list.extend(possible_routes)

            if possible_distribution_list:
                possible_distribution_map[renamed_asu] = possible_distribution_list
                full_matrix_str = ' (full matrix)' if full_matrix else ''
                print('Additional_distributions%s %d:' % (full_matrix_str, renamed_asu),
                      ', '.join(map(str, possible_distribution_list)))

        return possible_distribution_map

    # развозы по разрешённой матрице
    for (truck, route), sequence in truck_load_sequence.copy().items():
        renamed_asu = route[0]
        if 0 in sequence and len(route) == 1 and renamed_asu not in dp_parameters.shifting_load_info:
            bad_truck_routes.append((truck, route))
            bad_routes_set.add(route)

    possible_routes = get_possible_routes()

    additional_distribution_parallel(bad_truck_routes, possible_routes, integral_data,
                                     penalty_set, truck_load_volumes, truck_load_sequence,
                                     data, dp_parameters, parameters)
    # развозы по полной матрице
    for route in bad_routes_set:
        asu = route[0]
        critical_asu = 1 if is_asu_set_death([asu], dp_parameters, data) else 2
        empty_section_count = min(seq.count(0) for (t, r), seq in truck_load_sequence.items() if asu in r)
        if empty_section_count <= critical_asu:
            for (t, r) in bad_truck_routes.copy():
                if asu in r:
                    bad_truck_routes.remove((t, r))

    bad_routes_set = set(r for t, r in bad_truck_routes)

    possible_routes = get_possible_routes(full_matrix=True)

    additional_distribution_parallel(bad_truck_routes, possible_routes, integral_data,
                                     penalty_set, truck_load_volumes, truck_load_sequence,
                                     data, dp_parameters, parameters, without_empty=True)
    # остаток
    for route in bad_routes_set:
        asu = route[0]
        critical_asu = 1 if is_asu_set_death([asu], dp_parameters, data) else 2
        empty_section_count = min(seq.count(0) for (t, r), seq in truck_load_sequence.items() if asu in r)
        if empty_section_count <= critical_asu:
            for (t, r) in bad_truck_routes.copy():
                if asu in r:
                    bad_truck_routes.remove((t, r))


def additional_distribution_parallel(routes, possible_routes, integral_data, penalty_set, truck_load_volumes,
                                     truck_load_sequence, data: StaticData, dp_parameters: DParameters,
                                     parameters: Parameters, without_empty=False):
    best_truck_load_param = []
    keys = []

    for truck, route in routes:
        renamed_asu = route[0]
        possible_route_list = possible_routes.get(renamed_asu, [])
        truck_set = {truck: data.vehicles[truck].sections_volumes}

        for distribution_route in possible_route_list:
            if all([data.asu_vehicles_compatibility(truck, dp_parameters.asu_decoder(asu_id))
                    for asu_id in distribution_route]):

                if all(map(lambda x: x in dp_parameters.load_info, distribution_route)):
                    asu_tanks, first_model_volumes, empty_spaces = \
                        truck_load_parameter_generator(distribution_route, dp_parameters.load_info)
                else:
                    asu_tanks, first_model_volumes, empty_spaces = \
                        truck_load_parameter_generator(route, dp_parameters.load_info)

                load_parameters = TruckLoadParameters(route=distribution_route,
                                                      asu_tanks=asu_tanks,
                                                      first_model_volumes=first_model_volumes,
                                                      empty_spaces=empty_spaces,
                                                      truck_set=truck_set)

                depot = define_depot(list(load_parameters.first_model_volumes),
                                     integral_data.data, integral_data.dp_parameters)
                if data.depot_vehicles_compatibility(truck, depot):
                    best_truck_load_param.append((load_parameters, integral_data, truck, depot, dp_parameters, data, True))
                    key = truck, distribution_route
                    dp_parameters.route_depots[key] = depot
                    keys.append(key)

    result_truck_load = parameters.pool.starmap(best_truck_load_linear, best_truck_load_param)

    for (truck, distribution_route), (penalty, load_volumes, load_sequence) in zip(keys, result_truck_load):
        if check_load(load_sequence, distribution_route):
            key = truck, distribution_route
            if not (without_empty and load_sequence.count(0) >= 2):
                penalty_set[key], truck_load_volumes[key], truck_load_sequence[key] = penalty, load_volumes, load_sequence


"""Update load info in dp_parameters for additional asu and tanks"""


def update_load_info(truck_load_sequence, dp_parameters):
    for key, sequence in truck_load_sequence.items():
        for asu_n in sequence:
            if asu_n:
                asu, n = asu_n
                dp_parameters.load_info.setdefault(asu, {}).setdefault(asu_n, [0, 0])
