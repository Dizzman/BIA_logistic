"""В данном модуле реализована модель загрузки секций БВ требуемыми видами топлива.

Критерий оптимизации - минимизация штрафа, описанной в целевой функции.

Целевая функция модели детального планирования состоит из следующих элементов:
1. Штраф за недогруз относительно требованиям интегральной модели.
2. Штраф за перегруз относительно требованиям интегральной модели.
3. Штраф за наличие пустых секций.
4. Tank forgetting penalty.
5. Штраф на обязательную загрузку первых трёх секций (бизнес-требование).
6. Штраф за развоз одной секции на одну АЗС.
"""

from detailed_planning.dp_parameters import DParameters
from data_reader.input_data import StaticData, get_distance
from docplex.mp.model import Model

from detailed_planning.functions import calculate_time_to_death
from models_connector.integral_detailed_connector import ModelsConnector
from integral_planning.functions import consumption_filter, overload_risk
from data_reader.objects_classes import Car
from detailed_planning.trip_optimization import define_asu_windows


def objective_lack_load(dp_parameters: DParameters, integral_load, var_set_lack_load, addition_asu_n, data: StaticData):
    """Функция описывает элемент целевой функции, характеризующий недозагруз топлива в БВ к
    требованию интегральной модели. Вес элемента целевой функции - lack_loading_weight.

    :param dp_parameters: элемент класса DParameters. Параметры модели.
    :param integral_load: Требования к загрузке согласно интегральной модели.
    :param var_set_lack_load: Переменные объёмов недостатка детальной модели.
    :param addition_asu_n: Дополнительные баки для заполнения.
    :param data: Входные данные.
    :return: Выражение суммы для целевой функции.
    """

    return sum((dp_parameters.lack_loading_weight + weight_estimation(asu_n[0], asu_n[1], dp_parameters, data) / 5000) *
               var_set_lack_load[asu_n] for asu_n in var_set_lack_load if asu_n not in addition_asu_n)


def get_depot_restricts(dp_parameters: DParameters, data: StaticData, depot_id, asu_sku):
    depot_sku = data.fuel_in_depot_inverse.get((depot_id, asu_sku), None)
    shift = (dp_parameters.time + 1) // 2
    if depot_sku:
        return max(1, data.restricts.get((depot_id, depot_sku, shift), 1000000))
    else:
        return 0.001


def objective_overload(dp_parameters: DParameters, integral_load, var_set_overload, addition_asu_n, data: StaticData, depot_id):
    """Функция описывает построение элемента целевой функции, характеризующего перегруз
    топлива в БВ относительно требований интегральной модели. Вес элемента целевой функции -
    overloading_weight.

    :param dp_parameters: элемент класса DParameters. Параметры модели.
    :param integral_load: Требования к загрузке согласно интегральной модели.
    :param var_set_overload: Переменные объёмов избытка детальной модели.
    :param addition_asu_n: Дополнительные баки для заполнения.
    :param data: Входные данные.
    :param depot_id: Номер НБ
    :return: Выражение суммы для целевой функции.
    """
    return dp_parameters.overloading_weight * sum(
        25000 / get_depot_restricts(dp_parameters, data, depot_id, data.tank_sku[dp_parameters.asu_decoder(asu_n[0]), asu_n[1]]) *
        var_set_overload[asu_n] for asu_n in var_set_overload
        if data.tank_sku[dp_parameters.asu_decoder(asu_n[0]), asu_n[1]] in data.sku_deficit.get(depot_id, []))


def objective_empty_sections(dp_parameters: DParameters, var_set_sec, var_set_scheme, load_schemes, sections_count):
    return dp_parameters.empty_section_weight * \
           sum((1 - var_set_sec[sec] - sum(var for scheme, var in var_set_scheme.items()
                                           if sections_count - sec in load_schemes[scheme])) for sec in var_set_sec)


def objective_tank_forgetting(data: StaticData, dp_parameters: DParameters, var_set_asu_n, addition_asu_n):
    return sum(weight_estimation(asu, n, dp_parameters, data) * (1 - var_set_asu_n[asu, n]) for asu, n in var_set_asu_n if
               (asu, n) not in addition_asu_n)


def objective_empty_in_beginning(dp_parameters: DParameters, var_set_sec, var_set_scheme, load_schemes, sections_count):
    return dp_parameters.empty_section_in_beginning_weight * \
           sum((1 - var_set_sec[sec] - sum(var for scheme, var in var_set_scheme.items()
                                           if sections_count - sec in load_schemes[scheme]))
               for sec in var_set_sec if sec in range(sections_count - 3, sections_count - 1))


def objective_first_empty_section(dp_parameters: DParameters, var_set_sec, var_set_scheme, load_schemes, sections_count):
    return dp_parameters.first_empty_section_weight * (1 - var_set_sec[sections_count - 1] -
                                                       sum(var for scheme, var in var_set_scheme.items()
                                                           if 1 in load_schemes[scheme]))


def objective_one_section(dp_parameters: DParameters, var_set_asu_sec, route):
    return dp_parameters.one_section_to_asu_weight * sum((1 - var_set_asu_sec[asu_id]) for asu_id in route)


"""Results collection"""


def result_extractor(sections_count, var_set_tank, var_set_scheme, truck_sections, load_schemes,
                     integral_load, result, var_lack_load, var_overload):
    """Get load penalty value"""
    best_quality = result.get_objective_value()

    work_scheme = load_schemes[[scheme for scheme, var in var_set_scheme.items() if round(var.solution_value) > 0][0]]

    """Get load info"""
    best_truck_load_volumes = []
    best_section_fulfilled = []
    for sec in range(sections_count):
        if (sections_count - sec) not in work_scheme:
            best_truck_load_volumes.append(0)
            best_section_fulfilled.append(0)
            for asu_n in integral_load:
                if round(var_set_tank[asu_n, sec].solution_value) > 0:
                    best_truck_load_volumes[-1] = truck_sections[sec]
                    best_section_fulfilled[-1] = asu_n
    """
        Overload and Lack load penalties are deleted from quality level 
        Reasons:
            - They are intra model parameters and do not have business interpretation
            - They make influence in the trip_optimization model, where two close loads differs by small value
    """
    best_quality -= var_lack_load.solution_value
    best_quality -= var_overload.solution_value

    return round(best_quality, 4), best_truck_load_volumes, best_section_fulfilled


"""Truck load optimization model"""


def best_truck_load_linear(load_parameters, integral_data: ModelsConnector, truck, depot,
                           dp_parameters: DParameters, data: StaticData,
                           addition_distribution_tanks=False):
    integral_load = load_parameters.first_model_volumes.copy()  # Loads volumes from integral model
    route = load_parameters.route
    truck_sections = data.vehicles[truck].sections_volumes
    sections_count = len(truck_sections)  # Amount of sections in truck

    # depot = define_depot(list(integral_load), integral_data.data, integral_data.dp_parameters)

    # если рейс без развозов и асу не была в сплиттере, то рассматриваются дополнительные баки на данной асу
    # если addition_distribution_tanks=True, то рассматриваются дополнительные баки в рейсах с развозами
    addition_asu_n = get_addition_asu_n_dict(route, integral_load, integral_data) \
        if (len(route) == 1 and route[0] == dp_parameters.asu_decoder(route[0])) or addition_distribution_tanks else {}
    integral_load.update({asu_n: 0 for asu_n in addition_asu_n})

    empty_space = {asu_n: empty_space_calculator(asu_n, truck, depot, integral_data.initial_states, data, dp_parameters)
                   for asu_n in integral_load.keys()}

    load_scheme_dict, load_schemes = dictionary_of_load_schemes(data.vehicles[truck], integral_load.keys(),
                                                                data.tank_sku, data.fuel_groups, dp_parameters)

    '''Model initialization'''

    m = Model('Truck load')

    '''VarDict initialization'''

    var_set_tank = {}  # binary variable 'x' with indices asu_id, n, section_number; Section is filled with (asu_id, n)
    var_set_tank_number = {}  # integer variable 'number' with indices asu_id, n, section_number; Filled section number
    var_set_sec = {}  # binary variable 's' with indices section_number; Section usage status
    var_set_asu_sec = {}  # binary variable 'a' with indices asu_n; Loaded section number to asu is greater than 1
    var_set_asu_n = {}  # binary variable 'l' with indices asu_id, n; The tank is loaded
    var_set_sum = {}  # continuous variable 'sum' with indices asu_id, n; Sum of load to tank
    var_set_overload = {}  # continuous variable 'osum' with indices asu_id, n; Sum of overload to tank
    var_set_lack_load = {}  # continuous variable 'usum' with indices asu_id, n; Sum of lack load to tank
    var_set_scheme = {}  # binary variable 'scheme' with indices scheme; Load scheme

    """Auxiliary variables"""
    var_lack_load = m.continuous_var(lb=0, name='lack_load_penalty')  # The variable to collect the lackload penalty size
    var_overload = m.continuous_var(lb=0, name='overload_penalty')  # The variable to collect the overload penalty size

    '''Variables initialization: 
        - Section is filled with (asu_id, n): x
        - Filled section number: number
        - Tank loads status: l
        - Sum of load to tank: sum
        - Sum of overload to tank: osum
        - Sum of lack load to tank: usum
        - Load scheme: scheme'''

    for asu_n in integral_load:
        asu_id, n = asu_n
        for sec in range(sections_count):

            var_set_tank[asu_n, sec] = m.binary_var(name='x_%d_%d_%d' % (asu_id, n, sec))

            # If route contains two and more asu, they should be loaded in certain sequence
            if len(route) > 1 and not dp_parameters.asu_mixed_possibility:
                var_set_tank_number[asu_n, sec] = m.integer_var(name='number_%d_%d_%d' % (asu_id, n, sec))

                '''Constraint for estimation the used truck section number from truck head'''

                if route[0] == asu_id:
                    m.add_constraint_(var_set_tank_number[asu_n, sec] == var_set_tank[asu_n, sec] * (sec + 1),
                                      ctname='truck_section_number_%d_%d_%d' % (asu_id, n, sec))
                else:
                    m.add_constraint_(var_set_tank_number[asu_n, sec] == var_set_tank[asu_n, sec] * (sections_count - sec),
                                      ctname='truck_section_number_%d_%d_%d' % (asu_id, n, sec))
        var_set_asu_n[asu_n] = m.binary_var(name='l_%d_%d' % (asu_id, n))
        var_set_sum[asu_n] = m.continuous_var(lb=0, ub=empty_space[asu_n] if empty_space[asu_n] > 0 else 0,
                                              name='sum_%d_%d' % (asu_id, n))

        var_set_overload[asu_n] = m.continuous_var(lb=0, name='osum_%d_%d' % (asu_id, n))
        var_set_lack_load[asu_n] = m.continuous_var(lb=0, name='usum_%d_%d' % (asu_id, n))

        '''Tanks visit calculation'''
        m.add_constraint_(m.max(var_set_tank[asu_n, sec] for sec in range(sections_count)) == var_set_asu_n[asu_n],
                          ctname='l_%d_%d' % (asu_id, n))

        '''Volume to be loaded into tank'''
        m.add_constraint_(var_set_sum[asu_n] == sum(var_set_tank[asu_n, sec] * truck_sections[sec] for sec in range(sections_count)),
                          ctname='load_sum_%d_%d' % (asu_id, n))

        '''Lack load calculation comparison with integral model estimations'''
        m.add_constraint_(var_set_sum[asu_n] + var_set_lack_load[asu_n] >= integral_load[asu_n],
                          ctname='Underload_%d_%d' % (asu_id, n))

        '''Overload calculation comparison with integral model estimations'''
        m.add_constraint_(var_set_sum[asu_n] <= integral_load[asu_n] + var_set_overload[asu_n],
                          ctname='Overload_%d_%d' % (asu_id, n))

        '''Zero depot residue'''
        sku = data.tank_sku[dp_parameters.asu_decoder(asu_id), n]
        depot_residue = data.restricts.get((depot, data.fuel_in_depot_inverse[depot, sku], (dp_parameters.time + 1) // 2), 1) \
            if (depot, sku) in data.fuel_in_depot_inverse else 0
        if depot_residue == 0:
            m.add_constraint(var_set_asu_n[asu_n] == 0, ctname='zero_depot_residie_%d_%d' % (asu_id, n))

    '''Union empty space of splitted asu'''
    if len(route) == 2 and dp_parameters.asu_decoder(route[0]) == dp_parameters.asu_decoder(route[1]):
        asu1, asu2 = route
        unique_tanks = set(n for asu, n in empty_space if asu1 == asu).\
            intersection(set(n for asu, n in empty_space if asu2 == asu))
        for n in unique_tanks:
            m.add_constraint_(var_set_sum.get((asu1, n), 0) + var_set_sum.get((asu2, n), 0) <=
                              max(empty_space.get((asu1, n), 0), empty_space.get((asu2, n), 0)),
                              ctname='same_asu_tank_%d' % n)

    # '''Every asu should be visited'''
    # for asu_id in route:
    #     var_set_asu_sec[asu_id] = m.addVar(vtype=GRB.BINARY, name='a_%d' % asu_id)
    #     m.addConstr(var_set_asu_sec[asu_id] <= sum(var_set_tank[asu_n, sec] for asu_n, sec in var_set_tank if asu_n[0] == asu_id),
    #                 name='asu_sec_visit_%d' % asu_id)  # TODO исправить

    '''Integrality constraint: each section can be loaded only for one tank'''
    for sec in range(sections_count):
        var_set_sec[sec] = m.binary_var(name='s_%d' % sec)
        m.add_constraint_(sum(var_set_tank[asu_n, sec] for asu_n in integral_load) == var_set_sec[sec], ctname='Unique_section_%d' % sec)

    '''Section between two loaded section should be loaded'''
    if not dp_parameters.empty_in_the_middle_possibility:
        for sec in range(sections_count - 1):
            m.add_constraint_(var_set_sec[sec + 1] >= var_set_sec[sec], ctname='load_sec_%d' % sec)

    '''Constraint for load sequence in case: route contains two asu to be visited'''
    # Asu should be loaded in certain sequence
    if len(route) > 1 and not dp_parameters.asu_mixed_possibility:
        # integer variable: last section number of first asu tanks load
        first_asu_max = m.integer_var(lb=0, ub=sections_count, name='f_max')
        m.add_constraint_(
            first_asu_max == m.max(var_set_tank_number[asu_n, sec] for asu_n, sec in var_set_tank_number if asu_n[0] == route[0]),
            ctname='first_asu_max')
        # integer variable: first section number of second asu tanks load
        second_asu_min = m.integer_var(lb=0, ub=sections_count, name='s_min')
        m.add_constraint_(
            second_asu_min == m.max(var_set_tank_number[asu_n, sec] for asu_n, sec in var_set_tank_number if asu_n[0] == route[1]),
            ctname='second_asu_min')

        m.add_constraint_(second_asu_min + first_asu_max <= sections_count, ctname='load_sequence_control')
    # First section must not be drained on first asu
    elif len(route) > 1:
        m.add_constraint_(sum(var for ((asu, n), sec), var in var_set_tank.items()
                              if asu == route[0] and sec == sections_count - 1) == 0,
                          ctname='load_sequence_control')

    for num in range(len(load_schemes)):
        var_set_scheme[num] = m.binary_var(name='scheme_%d' % num)
    m.add_constraint_(sum(var_set_scheme.values()) == 1, ctname='scheme_constraint')

    '''Fixed section scheme'''
    section_fuel = data.vehicles[truck].section_fuel
    if section_fuel is not None:
        if 'diesel' not in section_fuel and 'none' not in section_fuel:
            m.add_constraint_(var_set_scheme[0] == 1, ctname='fixed_scheme')
        elif 'petrol' not in section_fuel and 'none' not in section_fuel:
            m.add_constraint_(var_set_scheme[1] == 1, ctname='fixed_scheme')

        for sec, fuel in enumerate(section_fuel, start=1):
            if fuel != 'none':
                fuel_id = 0 if fuel == 'petrol' else 1
                m.add_constraint_(sum(var_set_tank[asu_n, sections_count - sec]
                                      for asu_n in load_scheme_dict[1 - fuel_id]) == 0,
                                  ctname='fixed_scheme_section_%d' % sec)

    '''Constraints for load schemes'''
    for scheme, asu_n_list in load_scheme_dict.items():
        m.add_constraint_(sum(var_set_asu_n[asu_n] for asu_n in integral_load if asu_n in asu_n_list) <=
                          (1 - var_set_scheme[1 - scheme]) * 10, ctname='scheme_constraint_%d' % scheme)
        m.add_constraint_(sum(var_set_asu_n[asu_n] for asu_n in integral_load if asu_n in asu_n_list) >= var_set_scheme[2],
                          ctname='scheme_constraint_%d_mix' % scheme)

    '''Empty spaces for load schemes'''
    for scheme_number, scheme_var in var_set_scheme.items():
        for sec in load_schemes[scheme_number]:
            if not sec:
                break
            m.add_constraint_(var_set_sec[sections_count - sec] <= 1 - scheme_var,
                              ctname='scheme_empty_section_%d_%d' % (scheme_number, sections_count - sec))

    '''Objective function initialization'''
    objective = 0

    """Lack of load penalty"""
    if dp_parameters.lack_load_penalty:
        objective += objective_lack_load(dp_parameters, integral_load, var_set_lack_load, addition_asu_n, data)
        m.add_constraint_(var_lack_load == objective_lack_load(dp_parameters, integral_load, var_set_lack_load, addition_asu_n, data),
                          ctname='lack_load_penalty_size')
    """Overloading penalty"""
    if dp_parameters.overloading_penalty:
        objective += objective_overload(dp_parameters, integral_load, var_set_overload, addition_asu_n, data, depot)
        m.add_constraint_(var_overload == objective_overload(dp_parameters, integral_load, var_set_overload, addition_asu_n, data, depot),
                          ctname='overload_penalty_size')
    """Empty section penalty"""
    if dp_parameters.empty_section_penalty:
        objective += objective_empty_sections(dp_parameters, var_set_sec, var_set_scheme, load_schemes, sections_count)
    """Tank forgetting penalty"""
    if dp_parameters.tank_forgetting_penalty:
        objective += objective_tank_forgetting(data, dp_parameters, var_set_asu_n, addition_asu_n)
    """First section unload big penalty"""
    if dp_parameters.first_empty_section_penalty:
        objective += objective_first_empty_section(dp_parameters, var_set_sec, var_set_scheme, load_schemes, sections_count)
    """Second and third three sections unload penalty"""
    if dp_parameters.empty_section_in_beginning_penalty:
        objective += objective_empty_in_beginning(dp_parameters, var_set_sec, var_set_scheme, load_schemes, sections_count)
    """If asu is visited with one section penalty"""
    if dp_parameters.one_section_to_asu_penalty:
        objective += objective_one_section(dp_parameters, var_set_asu_sec, route)

    m.minimize(objective)

    '''Gurobi parameters'''
    m.log_output = False  # Console output switcher
    m.parameters.threads = 1
    result = m.solve()

    '''Bug report in LP'''
    if not result:
        m.export_as_lp('./output/Load_model_%d_%s_%d.lp' % (dp_parameters.time, str(load_parameters.route), truck))
        print(empty_space)
        print(integral_load)
        print("<FOR_USER>\nНЕ НАЙДЕНО решение Загрузки БВ № %d. Проверьте входные данные.\n</FOR_USER>" % truck)

    """Returns: int, [float, float, ...], [(asu_id1, n1), (asu_id2, n2), ...]"""

    return result_extractor(sections_count, var_set_tank, var_set_scheme, truck_sections,
                            load_schemes, integral_load, result, var_lack_load, var_overload)


"""Dictionary of load schemes"""


def dictionary_of_load_schemes(truck: Car, asu_n_set: list, asu_n_sku: dict, fuel_groups: dict, dp_parameters: DParameters):
    load_dict = {0: [], 1: []}
    load_schemes = (truck.sec_empty['np_petrol'], truck.sec_empty['np_diesel'], truck.sec_empty['np_mix'])

    for asu, n in asu_n_set:
        if fuel_groups[asu_n_sku[dp_parameters.asu_decoder(asu), n]] == 'diesel':
            load_dict[1].append((asu, n))
        else:
            load_dict[0].append((asu, n))

    return load_dict, load_schemes


"""Dict of tanks to load"""


def get_addition_asu_n_dict(route: list, integral_load: dict, integral_data: ModelsConnector):
    result = set()
    dp_parameters = integral_data.dp_parameters
    data = integral_data.data
    for asu, n in integral_data.initial_states:
        if asu in route and (asu, n) not in integral_load:
            real_asu = dp_parameters.asu_decoder(asu)
            sku = data.tank_sku[real_asu, n]
            if data.sku_vs_sku_name[sku] != 'G100':  # TODO Костыль на запрет дозагрузки G100
                result.add((asu, n))
    return result


def define_empty_space(asu: int, n: int, depot: int, integral_data: ModelsConnector):
    data = integral_data.data
    dp_parameters = integral_data.dp_parameters
    asu_capacity = float(data.tanks[(data.tanks['asu_id'] == asu) & (data.tanks['n'] == n)]['capacity'])
    overload_risk_value = overload_risk(asu, depot, dp_parameters, data)
    asu_consumption = overload_risk_value * consumption_filter(data.consumption, asu, n, dp_parameters.time)  # то что не успеют потребить
    return asu_capacity - integral_data.initial_states[
        asu, n] - asu_consumption  # в initial_states учтено потребление за всю смену и volumes_add


def weight_estimation(asu, n, dp_parameters: DParameters, data: StaticData):
    real_asu = dp_parameters.asu_decoder(asu)
    time_to_death = dp_parameters.asu_tank_death[real_asu, n]
    if not data.asu_work_shift[real_asu][dp_parameters.time % 2 + 1]:
        full_shift_count = int(time_to_death / 0.5)
        time_to_death = (full_shift_count + 1) // 2 * 0.5 + \
                        (1 - full_shift_count % 2) * (time_to_death - 0.5 * full_shift_count)
    if time_to_death < 0.5:
        return dp_parameters.tank_not_loaded_weight[0] * 0.2 + 1 / (time_to_death if time_to_death > 0 else 0.01)
    elif time_to_death < 1:
        return dp_parameters.tank_not_loaded_weight[1] * 0.1
    elif time_to_death < 1.375:
        return dp_parameters.tank_not_loaded_weight[2] * 0.1
    else:
        return 0


# def define_depot(asu_n_list: list, data: StaticData, dp_parameters: DParameters):
#     depot_set = set()
#     relocated_depot_set = set()
#     first_asu = asu_n_list[0][0]
#     first_asu_relocated_depot_set = set()
#     for (asu, n) in asu_n_list:
#         real_asu = dp_parameters.asu_decoder(asu)
#         depot = data.asu_depot[real_asu]
#         depot_set.add(depot)
#         relocated_key = (real_asu, n, dp_parameters.time)
#         if relocated_key in data.asu_depot_reallocation:
#             relocated_depot = data.asu_depot_reallocation[relocated_key]
#             if relocated_depot != depot:
#                 relocated_depot_set.add(relocated_depot)
#                 if asu == first_asu:
#                     first_asu_relocated_depot_set.add(relocated_depot)
#     if len(relocated_depot_set) > 1:
#         if len(first_asu_relocated_depot_set) > 1:
#             # print('Разные изменённые депоты для %s: %s, basic: %s.' %
#             #       (str(asu_n_list), str(relocated_depot_set), str(depot_set)) +
#             #       'Депот не выбран: %s (%d).' % (str(first_asu_relocated_depot_set), first_asu))
#             return
#         else:
#             depot = first_asu_relocated_depot_set.pop()
#             # print('Разные изменённые депоты для %s: %s, basic: %s.' %
#             #       (str(asu_n_list), str(relocated_depot_set), str(depot_set)) +
#             #       'Выбран депот: %d (%d).' % (depot, first_asu))
#             return depot
#     if relocated_depot_set:
#         relocated_depot = relocated_depot_set.pop()
#         return relocated_depot
#     if len(depot_set) > 1:
#         depot = data.asu_depot[dp_parameters.asu_decoder(first_asu)]
#         # print('Разные депоты для %s: %s.' % (str(asu_n_list), str(depot_set)) +
#         #       'Выбран депот: %d (%d).' % (depot, first_asu))
#         return depot
#     if depot_set:
#         depot = depot_set.pop()
#         return depot
#     return


def define_depot(asu_n_list: list, data: StaticData, dp_parameters: DParameters):
    """
    Функция расчета привязки АЗС к НБ на основе поданных резервуаров:
        1. Если расчет привязки проводится впервые, то возвращаяется привязка наиболее критичного резервуара АЗС
        2. Если расчет привязок повторный ---> пропускается привязка наиболее критичного резервуара,
        берется следующая отличная от пропущенной НБ
    :param asu_n_list: список резервуаров запланированных к посещению
    :param data: набор входных данных
    :param dp_parameters: параметры модели
    :return: НБ или None
    """
    "Декодируем идетификаторы АЗС. Вычисляем время до остановки"
    decode_asu_n = {(dp_parameters.asu_decoder(asu), n): calculate_time_to_death(asu, dp_parameters, data)
                    for asu, n in asu_n_list}
    "Сортировка резервуаров АЗС по критичности"
    sorted_death = {k: v for k, v in sorted(decode_asu_n.items(), key=lambda item: item[1])}

    "Идентификатор НБ, который был в предыдущей привязке"
    skipped_depot = None

    for asu, n in sorted_death:
        "Экстрактим НБ для наиболее критичного резервуара"
        relocated_depot = data.asu_depot_reallocation.get((asu, n, dp_parameters.time), None)
        "Проверка наличия привязки"
        if not relocated_depot:
            "Если нет привязки - продолжаем"
            continue
        "Если номер итерации - целый, то возвращаем привязку"
        if not dp_parameters.partial_package_iter:
            return relocated_depot
        "Если номер итерации дробный и ранее не было пропуска резервуара в цикле, то добавляем пропуск текущей НБ"
        if dp_parameters.partial_package_iter and not skipped_depot:
            skipped_depot = relocated_depot
            continue
        "Если итерация дробная и предыдущая привязка не равна текущей ---> возвращаем текущую"
        if dp_parameters.partial_package_iter and skipped_depot != relocated_depot:
            return relocated_depot

    return skipped_depot


def empty_space_calculator(asu_n, truck, depot, initial_states, data: StaticData, dp_parameters: DParameters):
    asu_id = dp_parameters.asu_decoder(asu_n[0])
    n = asu_n[1]

    # Initial tank state
    init_stat = initial_states[asu_id, n]

    distance = 0

    if (truck, dp_parameters.time) in data.vehicles_busy:
        return 0

    # If truck is used in the beginning of the shift
    if (truck, dp_parameters.time) in data.vehicles_busy_hours:
        busy_hours, location = data.vehicles_busy_hours[truck, dp_parameters.time]

        distance += busy_hours

        if location is None and data.vehicles[truck].is_own:
            location = data.vehicles[truck].uet
        elif location is None:
            location = depot
        # If truck is loaded, the drive direction is asu TODO dp_parameters update status of truck loaded, if truck is used
        if depot in dp_parameters.truck_loaded.get(truck, []):
            if not isinstance(location, str):
                delta = get_distance(int(location), asu_id, data.distances_asu_depot)
            else:
                delta = get_distance(location, asu_id, data.distances_asu_uet)
            distance += delta
        # Else, truck goes to load (depot)
        else:
            if not isinstance(location, str):
                delta = get_distance(int(location), depot, data.distances_asu_depot)
            else:
                delta = get_distance(location, depot, data.distances_asu_uet)
            distance += delta
            distance += data.parameters.petrol_load_time
            distance += get_distance(depot, asu_id, data.distances_asu_depot)
    else:
        if data.vehicles[truck].is_own:
            location = data.vehicles[truck].uet
        else:
            location = depot
        if truck in dp_parameters.truck_loaded:
            if not isinstance(location, str):
                delta = get_distance(int(location), asu_id, data.distances_asu_depot)
            else:
                delta = get_distance(location, asu_id, data.distances_asu_uet)
            distance += delta
        # Else, truck goes to load (depot)
        else:
            if not isinstance(location, str):
                delta = get_distance(int(location), depot, data.distances_asu_depot)
            else:
                delta = get_distance(location, depot, data.distances_asu_uet)
            distance += delta
            distance += data.parameters.petrol_load_time
            distance += get_distance(depot, asu_id, data.distances_asu_depot)

    # Window left bound
    window_in = define_asu_windows(distance, asu_id, dp_parameters.time, 0, data.vehicles[truck].shift_size, data)

    if window_in:
        # Time to get asu
        time_to_asu = max(distance, window_in[0][0])
        time_to_asu -= data.parameters.risk_tank_overload

        "Если БВ приезжает на АЗС до начала смены, то корректируем свободный объем в большую сторону"
        if time_to_asu < 0:
            "Часть смены в предыдущую смену приезда на АЗС"
            shift_part = abs(distance) / dp_parameters.shift_size
            "Потребленный объем, который не потребится к началу смены"
            volume_consumed = shift_part * data.consumption[asu_id, n, dp_parameters.time + 1]
            "Палновая поставка"
            volumes_added = data.volumes_to_add.get((asu_id, n, dp_parameters.time), 0)
            "Прогноз остатка на АЗС"
            tank_state_forecast = max(data.tank_death_vol[asu_id, n], init_stat + volume_consumed + volumes_added)
            return max(0, data.tank_max_vol[asu_id, n] - tank_state_forecast)

        shift_amount = time_to_asu // data.parameters.shift_size
        shift_part = (time_to_asu % data.parameters.shift_size) / data.parameters.shift_size
        volume_consumed = 0
        volumes_added = 0

        # Sum shifts consumptions
        for shift in range(0, int(shift_amount)):
            volume_consumed += data.consumption[asu_id, n, dp_parameters.time + shift]
            volumes_added += data.volumes_to_add.get((asu_id, n, dp_parameters.time + shift), 0)

        # Part of shift consumption
        volume_consumed += shift_part * data.consumption[asu_id, n, dp_parameters.time + shift_amount]
        volumes_added += data.volumes_to_add.get((asu_id, n, dp_parameters.time + shift_amount), 0)
        volume_consumed_full_shift = data.consumption[asu_id, n, dp_parameters.time + shift_amount]

        # Initial state is greater than death volume
        initial_stat_corrected = max(data.tank_death_vol[asu_id, n], init_stat - volume_consumed + volumes_added)
        
        if volume_consumed_full_shift / data.tank_max_vol[asu_id, n] <= 0.08:
            initial_stat_corrected += 0.5 * volume_consumed_full_shift
        
        # Empty space calculation
        empty_space = max(0, data.tank_max_vol[asu_id, n] - initial_stat_corrected)

        return empty_space
    else:
        return 0.0
