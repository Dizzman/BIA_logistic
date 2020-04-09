from integral_planning.functions import consumption_filter, overload_risk
from docplex.mp.model import Model
from data_reader.input_data import StaticData
from detailed_planning.best_truck_load_linear import empty_space_calculator


# Заполнение пустых секций после расчёта 2й модели
# 1. Получение пустых секций в рейсах и азс, которые можно рассматривать для их заполения согласно маршруту.
# 2. Получение для каждого маршрута списка баков азс, пригодных для рассмотрения под заполнение, чтобы они не меняли
#    обязательно пустой секции.
# 3. В рассмотрение берутся те баки азс, на которые не запланированы рейсы по результатам интегральной модели на эту
#    смену и на следующую смену этого дня (при next_shift_permission==False). Если next_shift_permission==True, баки
#    следующей смены этого дня рассматриваются для заполнения, но при условии, что всё запланированное согласно
#    интегральной модели топливо на эту азс должно быть вывезено.
# 4. Привезённый объём топлива должен поместиться в пустое место бака азс. Расчёт пустого места взят у Лёши, стоит
#    проверить. что он перенесён корректно.
# 5. Вывезенный объём топлива должен соответствовать остаткам на нефтебазе. Расчёт остатков не реализован.
# 6. После расчёта корректируется карта погрузки в pd_parameters, если используются баки азс следующей смены, то азс
#    удаляется из интегральной модели на следующую смену.


def fill_empty_sections(set_direct, set_distribution, set_direct_double, set_distribution_double, pd_parameters,
                        integral_data, data: StaticData, next_shift_permission=False, next_shift_strong=False):
    print('Fill empty sections')
    # Получение списка пустых секций {truck, route, section, asu}
    #   и изменённые номера азс, используемые в маршруте {truck, route: asu: ch_asu}
    # Получение списка заполняемых баков в этот день/смену {asu: tank: load_volume}
    empty_sections, loaded_asu_n, changed_asu_numbers = \
        get_empty_section_and_load_map(set_direct, set_distribution, set_direct_double, set_distribution_double, pd_parameters)
    # Получение списка заполняемых баков в этот день/смену {asu: tank: load_volume}
    next_shift_loaded_asu_n = get_visited_asu_tank_list(pd_parameters, integral_data)
    # Получение списка баков подходящих для заполнения {truck, route, section, asu, tank: section_volume}
    possible_loads, next_shift_possible_loads = get_possible_loaded_list(empty_sections, loaded_asu_n, next_shift_loaded_asu_n,
                                                                         next_shift_permission, data, pd_parameters)
    # Получение списка нефтебаз {truck, route: depot}
    route_depots = get_route_depots(possible_loads, next_shift_possible_loads, pd_parameters)
    # Получение свободного места на азс {asu, tank: empty_volume},  {asu, tank, truck, route: empty_volume}
    # TODO должно быть вынесено в отдельную синхронизированную с Лёшей версию
    asu_empty_spaces, route_asu_empty_spaces = get_asu_empty_spaces(possible_loads, next_shift_possible_loads,
                                                                    loaded_asu_n, route_depots, data,
                                                                    pd_parameters, integral_data)
    # Получение списка остатков открытий с учётом дня/смены {depot, sku: rest_volume}
    # TODO получить остатки нп на нб. Сейчас убираются нп с 0-ми остатками на начало дня.
    depot_residues = {(depot, depot_sku): value for (depot, depot_sku, day), value in data.restricts.items()
                      if day == (pd_parameters.time + 1) // 2 and value == 0}
    # Распределить топливо по бакам с учётом {truck, route, section, asu, tank}
    result_loads = empty_filling_model(possible_loads, next_shift_possible_loads, asu_empty_spaces, route_asu_empty_spaces,
                                       route_depots, depot_residues, next_shift_loaded_asu_n, next_shift_strong, data)
    result_loads and print(result_loads)
    # Обновить карту погрузки, свободное место в азс и остатки на нефтебазе
    update_loads(pd_parameters, result_loads, possible_loads, next_shift_possible_loads, changed_asu_numbers, integral_data)

    # Вывод результата заполения
    empty_section_count = len(set((truck, route, section) for truck, route, section, asu in empty_sections))
    print('\t%d of %d sections was filled' % (len(result_loads), empty_section_count))
    if next_shift_permission:
        used_next_shift_asu = len(set(asu for (truck, route, section, asu, tank) in result_loads
                                      if (truck, route, section, asu, tank) in next_shift_possible_loads))
        all_next_shift_asu = len(set(asu for (truck, route, section, asu, tank) in next_shift_possible_loads))
        print('\t%d of %d next shift asu was used ' % (used_next_shift_asu, all_next_shift_asu))


def update_loads(pd_parameters, result_loads, possible_loads, next_shift_possible_loads, changed_asu_numbers, integral_data):
    for truck, route, section, asu, tank in result_loads:
        if (truck, route, section, asu, tank) in possible_loads:
            pd_parameters.truck_load_volumes[truck, route][section] = possible_loads[truck, route, section, asu, tank]
        else:
            pd_parameters.truck_load_volumes[truck, route][section] = next_shift_possible_loads[truck, route, section, asu, tank]
            if (asu, pd_parameters.time + 1) in integral_data.departures:
                integral_data.departures.pop((asu, pd_parameters.time + 1))
            integral_data.fuel_to_load.drop(integral_data.fuel_to_load[(integral_data.fuel_to_load['id_asu'] == asu)
                                                                       & (integral_data.fuel_to_load['time'] ==
                                                                          pd_parameters.time + 1)].index, inplace=True)
            integral_data.fuel_to_load.reset_index(drop=True, inplace=True)
        route_asu = asu if (truck, route) not in changed_asu_numbers else changed_asu_numbers[truck, route].get(asu, asu)
        pd_parameters.truck_load_sequence[truck, route][section] = (route_asu, tank)


def empty_filling_model(possible_loads, next_shift_possible_loads, asu_empty_spaces, route_asu_empty_spaces, route_depots,
                        depot_residues, next_shift_loaded_asu_n, next_shift_strong, data: StaticData):
    model = Model('Timetable')

    # Variables
    section_vars = {}
    next_shift_asu_vars = {}

    # Expressions
    section_expr = {}
    asu_expr = {}
    route_tank_expr = {}
    depot_expr = {}
    next_shift_asu_expr = {}

    next_shift_asu_set = set(asu for truck, route, section, asu, tank in next_shift_possible_loads)
    for next_shift_asu in next_shift_asu_set:
        next_shift_asu_vars[next_shift_asu] = model.binary_var(name='next_shift_asu_%d' % next_shift_asu)

    loads = possible_loads.copy()
    loads.update(next_shift_possible_loads)

    for truck, route, section, asu, tank in loads:
        depot = route_depots[truck, route]
        sku = data.tank_sku[asu, tank]
        if (depot, sku) not in data.fuel_in_depot:
            continue

        var = model.binary_var(name='section_%d_%s_%d_%d_%d' % (truck, str(route), section, asu, tank))
        section_vars[truck, route, section, asu, tank] = var

        if (truck, route, section) not in section_expr:
            section_expr[truck, route, section] = 0
        section_expr[truck, route, section] += var

        if (asu, tank) not in asu_expr:
            asu_expr[asu, tank] = 0
        asu_expr[asu, tank] += var * loads[truck, route, section, asu, tank]

        if (asu, tank, truck, route) not in route_tank_expr:
            route_tank_expr[asu, tank, truck, route] = 0
        route_tank_expr[asu, tank, truck, route] += var * loads[truck, route, section, asu, tank]

        if (depot, sku) not in depot_expr:
            depot_expr[depot, sku] = 0
        depot_expr[depot, sku] += var * loads[truck, route, section, asu, tank]

        if (truck, route, section, asu, tank) in next_shift_possible_loads:
            if (asu, tank) not in next_shift_asu_expr:
                next_shift_asu_expr[asu, tank] = 0
            next_shift_asu_expr[asu, tank] += var * loads[truck, route, section, asu, tank]
            model.add_constraint_(var <= next_shift_asu_vars[asu],
                                  ctname='next_shift_asu_existence_%d_%s_%d_%d_%d' % (truck, str(route), section, asu, tank))

    # Constrains
    # Only one tank in section
    for truck, route, section in section_expr:
        model.add_constraint_(section_expr[truck, route, section] <= 1,
                              ctname='one_tank_to_section_%d_%s_%d' % (truck, str(route), section))

    # Sum route fuel volume less than route asu empty space
    for asu, tank, truck, route in route_tank_expr:
        model.add_constraint_(route_tank_expr[asu, tank, truck, route] <=
                              max(0, route_asu_empty_spaces[asu, tank, truck, route]),
                              ctname='route_asu_tank_empty_volume_%d_%d_%d_%s' % (asu, tank, truck, str(route)))

    # Sum fuel volume less than asu empty space
    for asu, tank in asu_expr:
        model.add_constraint_(asu_expr[asu, tank] <= max(0, asu_empty_spaces[asu, tank]),
                              ctname='asu_tank_empty_volume_%d_%d' % (asu, tank))

    # Sum fuel volume less than depot volume rest
    for depot, depot_sku in depot_residues:
        model.add_constraint_(sum(depot_expr.get((depot, sku), 0) for sku in data.fuel_in_depot[depot, depot_sku]) <=
                              depot_residues[depot, depot_sku],
                              ctname='depot_sku_volume_rest_%d_%d' % (depot, depot_sku))

    # Next shift asu must be filled out entirely
    if next_shift_strong:
        for asu, tank in next_shift_asu_expr:
            model.add_constraint_(next_shift_asu_expr[asu, tank] >= next_shift_asu_vars[asu] *
                                  next_shift_loaded_asu_n[asu][tank],
                                  ctname='next_shift_asu_volume_rest_%d_%d' % (asu, tank))

    # Objective
    model.maximize(sum(section_vars.values()))

    model.log_output = False  # Console output switcher
    model.solve()

    #    model.write('empty_%d.lp' % pd_parameters.time)
    #
    #    if model.status == GRB.INFEASIBLE:
    #        model.computeIIS()
    #        model.write('empty_%d.ilp' % pd_parameters.time)
    #
    #    model.write('empty_%d.sol' % pd_parameters.time)

    result_loads = [key for key, value in section_vars.items() if round(value.solution_value, 0) == 1]

    return result_loads


def get_asu_empty_spaces(possible_loads, next_shift_possible_loads, loaded_asu_n, route_depots, data, pd_parameters, integral_data):
    route_asu_empty_spaces = {}
    loads = possible_loads.copy()
    loads.update(next_shift_possible_loads)
    route_asu_tank_set = set((asu, tank, truck, route) for truck, route, section, asu, tank in loads)
    for asu, tank, truck, route in route_asu_tank_set:
        depot = route_depots[truck, route]
        asu_departures = 0
        if asu in loaded_asu_n and tank in loaded_asu_n[asu]:
            asu_departures += loaded_asu_n[asu][tank]
        route_asu_empty_spaces[asu, tank, truck, route] = empty_space_calculator((asu, tank), truck, depot,
                                                                                 integral_data.initial_states,
                                                                                 data, pd_parameters) - asu_departures
    asu_tank_set = set((asu, tank) for truck, route, section, asu, tank in loads)
    asu_empty_spaces = {(asu, tank): max(volume for (a, t, _, _), volume in route_asu_empty_spaces.items()
                                         if a == asu and t == tank) for asu, tank in asu_tank_set}
    return asu_empty_spaces, route_asu_empty_spaces


def get_possible_loaded_list(empty_sections, loaded_asu_n, next_shift_loaded_asu_n, next_shift_permission, data: StaticData, pd_parameters):
    possible_loads = {}
    next_shift_possible_loads = {}
    for truck, route, section, asu in empty_sections:
        tank_list = [tank for dict_asu, tank in data.tank_sku if dict_asu == asu]
        for tank in tank_list:
            real_asu = pd_parameters.asu_decoder(asu)
            sku = data.tank_sku[real_asu, tank]
            if data.sku_vs_sku_name[sku] == 'G100':  # TODO Костыль на запрет дозагрузки G100
                continue
            truck_load_sequence = pd_parameters.truck_load_sequence[truck, route]
            # Проверка sku на неизменение обязательно пустой секции
            empty_sections = check_should_be_empty_section(truck, truck_load_sequence, (asu, tank), data, pd_parameters)
            if not empty_sections:
                continue
            # Проверка на соответсвие типа НП секции
            real_section = get_real_section_number(section, empty_sections)
            if data.vehicles[truck].section_fuel is not None and \
                not check_np_scheme_section(truck, section, truck_load_sequence, (asu, tank), data, pd_parameters):
                continue
            truck_section_volume = data.vehicles[truck].sections_volumes[real_section]
            # Проверка, что бак не везётся в этот день
            # if tank not in loaded_asu_n[asu] and (asu not in next_shift_loaded_asu_n or tank not in next_shift_loaded_asu_n[asu]):  # TODO убран запрет на рассмотрение баков этого дня
            if asu not in next_shift_loaded_asu_n or tank not in next_shift_loaded_asu_n[asu]:  #
                possible_loads[truck, route, section, asu, tank] = truck_section_volume
            # Рассматривать баки следующей смены
            elif next_shift_permission and asu in next_shift_loaded_asu_n and tank in next_shift_loaded_asu_n[asu]:
                next_shift_possible_loads[truck, route, section, asu, tank] = truck_section_volume
    return possible_loads, next_shift_possible_loads


def check_np_scheme_section(truck_num, section, truck_load_sequence, addition_asu_n, data: StaticData, pd_parameters):
    vehicle = data.vehicles[truck_num]

    sections = vehicle.sections_volumes.copy()
    number_of_sections = len(sections)

    real_asu_n = (pd_parameters.asu_decoder(addition_asu_n[0]), addition_asu_n[1])

    return vehicle.section_fuel[number_of_sections - section - 1] == data.fuel_groups[data.tank_sku[real_asu_n]] \
            or vehicle.section_fuel[number_of_sections - section - 1] == 'none'


def check_should_be_empty_section(truck, truck_load_sequence, addition_asu_n, data: StaticData, pd_parameters):
    load_sequence = set(truck_load_sequence)
    if 0 in load_sequence:
        load_sequence.remove(0)

    load_sequence = set((pd_parameters.asu_decoder(asu), n) for asu, n in load_sequence)
    current_empty_section = data.empty_section_number(truck, load_sequence)

    load_sequence.add(addition_asu_n)
    possible_empty_section = data.empty_section_number(truck, load_sequence)

    if current_empty_section == possible_empty_section:
        return current_empty_section


def get_real_section_number(section, empty_sections):
    if empty_sections == [0]:
        return section

    real_section_number = section
    for empty_section in sorted(empty_sections):
        if empty_section <= real_section_number:
            real_section_number += 1
        else:
            break

    return real_section_number


def get_route_depots(possible_loads, next_shift_possible_loads, pd_parameters):
    loads = possible_loads.copy()
    loads.update(next_shift_possible_loads)
    truck_route_set = set((truck, route) for truck, route, section, asu, tank in loads)
    route_depots = {(truck, route): pd_parameters.route_depots[truck, route] for truck, route in truck_route_set}
    return route_depots


def get_visited_asu_tank_list(pd_parameters, integral_data):
    # current_shift_loaded = pd_parameters.load_info
    # loaded_tanks = get_shift_loaded_tanks(current_shift_loaded, pd_parameters)
    next_shift_loaded_tanks = {}
    if pd_parameters.time % 2 == 1:
        second_shift_loaded = get_integral_load_by_time(integral_data, pd_parameters.time + 1)
        next_shift_loaded_tanks = get_shift_loaded_tanks(second_shift_loaded, pd_parameters)
    return next_shift_loaded_tanks


def get_integral_load_by_time(integral_data, time):
    pandas_filter = integral_data.fuel_to_load.loc[integral_data.fuel_to_load['time'] == time]
    integral_load = {}
    for idx, row in pandas_filter.iterrows():
        asu = int(row['id_asu'])
        n = int(row['n'])
        volume = int(row['volume'])
        if asu in integral_load:
            integral_load[asu][asu, n] = (volume,)
        else:
            integral_load[asu] = {(asu, n): (volume,)}
    return integral_load


def get_shift_loaded_tanks(shift_loaded, pd_parameters):
    loaded_tanks = {}
    for asu in shift_loaded:
        orig_asu = pd_parameters.asu_decoder(asu)
        for asu, tank in shift_loaded[asu]:
            if orig_asu not in loaded_tanks:
                loaded_tanks[orig_asu] = {}
            if tank not in loaded_tanks[orig_asu]:
                loaded_tanks[orig_asu][tank] = shift_loaded[asu][asu, tank][0]
            else:
                loaded_tanks[orig_asu][tank] += shift_loaded[asu][asu, tank][0]
    return loaded_tanks


def get_empty_section_and_load_map(set_direct, set_distribution, set_direct_double, set_distribution_double, pd_parameters):
    empty_section_map = {}
    route_asu_numbers = {}
    load_volume_map = {}
    key_list = []
    for asu1, truck in set_direct:
        key_list.append((truck, (asu1,)))
    for asu1, asu2, truck in set_distribution:
        key_list.append((truck, (asu1, asu2)))
    for asu1, asu2, truck in set_direct_double:
        key_list.append((truck, (asu1,)))
        key_list.append((truck, (asu2,)))
    for asu1, asu2, asu3, truck in set_distribution_double:
        key_list.append((truck, (asu1, asu2)))
        key_list.append((truck, (asu3,)))
    for key in key_list:
        empty_section_map[key], route_asu_numbers[key] = \
            get_empty_sections_from_load_sequence(key, pd_parameters.truck_load_sequence, pd_parameters)
        update_load_volume_map(load_volume_map, key, pd_parameters)
    empty_section_map = [(*key, *value) for key, value_list in empty_section_map.items() for value in value_list]
    route_asu_numbers = {key: route_asu_numbers[key] for key in route_asu_numbers if route_asu_numbers[key]}
    return empty_section_map, load_volume_map, route_asu_numbers


def update_load_volume_map(load_volume_map, key, pd_parameters):
    for index, asu_n in enumerate(pd_parameters.truck_load_sequence[key]):
        if not asu_n:
            continue
        asu, n = asu_n
        real_asu = pd_parameters.asu_decoder(asu)
        if real_asu not in load_volume_map:
            load_volume_map[real_asu] = {}
        if n not in load_volume_map[real_asu]:
            load_volume_map[real_asu][n] = 0
        load_volume_map[real_asu][n] += pd_parameters.truck_load_volumes[key][index]


def get_empty_sections_from_load_sequence(key, truck_load_sequence, pd_parameters):
    load_empty_section_list = []
    route_asu_numbers = {}
    if key in truck_load_sequence:  # TODO Кать, Ключа может не быть
        load_sequence = truck_load_sequence[key]
        section_count = len(load_sequence)
        asu, n = [asu_n for asu_n in reversed(load_sequence) if asu_n][0]
        orig_asu = pd_parameters.asu_decoder(asu)
        if orig_asu != asu:
            route_asu_numbers[orig_asu] = asu
        # reverse
        for section, asu_n in enumerate(reversed(load_sequence)):
            if asu_n == 0:
                load_empty_section_list.append((section_count - section - 1, orig_asu))
            else:
                asu, n = asu_n
                orig_asu = pd_parameters.asu_decoder(asu)
                if orig_asu != asu:
                    route_asu_numbers[orig_asu] = asu
        asu, n = [asu_n for asu_n in load_sequence if asu_n][0]
        orig_asu = pd_parameters.asu_decoder(asu)
        # direct
        for section, asu_n in enumerate(load_sequence):
            if asu_n == 0:
                if (section, orig_asu) not in load_empty_section_list:
                    load_empty_section_list.append((section, orig_asu))
            else:
                asu, n = asu_n
                orig_asu = pd_parameters.asu_decoder(asu)
                if orig_asu != asu:
                    route_asu_numbers[orig_asu] = asu
    return load_empty_section_list, route_asu_numbers
