import copy
import itertools
import multiprocessing
import os
import sys
from collections import namedtuple
from copy import deepcopy

import config
from asu_nb_connecting.update_static_data import update_static_data
from data_reader.calc_percent import percents
from data_reader.input_data import Parameters
from detailed_planning.empty_section_filling import fill_empty_sections
from detailed_planning.functions import *
from detailed_planning.routes_loads import every_route_load_parallel
from detailed_planning.trip_optimization import minimize_penalties_iter, any_trip_duration_check
from integral_planning.integral_planning import ConstraintSwitcher, IntegralModel
from integral_planning.integral_read import IntegralRead
from models_connector.integral_detailed_connector import ModelsConnector
from output_writer.output_stations_state import OutputCreatorStations
from output_writer.output_trips_load import OutputCreatorTrips
from schedule_writer.schedule_writer import Schedule
from timetable_calculator.timetable_calculator import TimetableCreator
from validation.components.prevalidate_reservoir_overflow import validate_reservoir_overflow

# Переключатели дополнений для моделей

LAUNCH_ASU_NB_CONNECTING_ALGORITHM = True
LAUNCH_BEFORE_CALC_VALIDATION = True
LAUNCH_AFTER_CALC_VALIDATION = config.configuration['launch_after_calc_validation']
VALIDATION_ONLY_MODE = False
TESTPACK_MODE = False

if not os.path.exists("../logs"):
    os.mkdir("../logs")


class Model:
    def __init__(self, scenario, path: str, planning_start: int, planning_duration: int):
        self.scenario = scenario  # input data scenario version
        self.path = path + str(scenario)  # input data path
        self.parameters = Parameters()  # Parameters initialization
        self.constraint_switcher = ConstraintSwitcher(self.path)  # Constraint switcher initialization
        self.data = StaticData(self.path, self.parameters)  # Initial data initialization
        self.planning_start = planning_start  # Shift number of planning start
        self.planning_duration = planning_duration  # Planning period durations in shifts
        self.previous_period_loaded_sku = {row['sku']: 0 for idx, row in
                                           self.data.absolute_period_consumption.iterrows()}  # SKU volumes loaded in balance period
        self.initial_state = self.data.initial_fuel_state.copy()  # Initial state

        # if LAUNCH_BEFORE_CALC_VALIDATION:
        #     validate_reservoir_overflow(data=self.data,
        #                                 parameters=self.parameters,
        #                                 horizon=(self.planning_start, self.planning_duration))

    '''Run integral model'''

    def integral_model_run(self, shift, output_states_collection: OutputCreatorStations, read_from_file=False):

        if LAUNCH_ASU_NB_CONNECTING_ALGORITHM:

            print("Работа алгоритма привязки АЗС к НБ.")

            # Генерируем информацию для работы интегральной модели с фиктивной АЗС

            updated_data = deepcopy(self.data)
            update_static_data(updated_data)

            if LAUNCH_BEFORE_CALC_VALIDATION:
                validate_reservoir_overflow(data=updated_data,
                                            parameters=self.parameters,
                                            horizon=(self.planning_start, self.planning_duration))
                self.initial_state = updated_data.initial_fuel_state.copy()

            # Построение интегральной модели для общей НБ

            integral_model = IntegralModel(parameters=self.parameters,
                                           data=updated_data,
                                           initial_state=self.initial_state,
                                           period_start=shift,
                                           period_duration=self.parameters.absolute_period_duration,
                                           constraint_switcher=self.constraint_switcher,
                                           previous_period_loaded_sku=self.previous_period_loaded_sku,
                                           output_states_collection=output_states_collection)

            # Решение интегральной модели без учёта привязок НБ и с суммарными
            # объёмами открытия
            if read_from_file:
                integral_model = IntegralRead(self.path + '/integral_model.xlsx', self.data, shift)
                flow_data = integral_model.pd_flows
                departures_dict = integral_model.departures
                departures_data = flow_data.filter(['id_asu', 'time']).drop_duplicates()
                cut_departures_data_array = []
                for index, row in departures_data.iterrows():
                    asu_row = row.tolist()
                    asu_row.append(departures_dict[row['id_asu'], row['time']])
                    asu_row.append(0)  # TODO Костыль --- depot в flow_data может быть не уникальный для разных баков
                    cut_departures_data_array.append(asu_row)
                departures_data = pd.DataFrame(data=cut_departures_data_array,
                                               columns=['id_asu', 'time', 'departures', 'depots'])
                integral_model.period_duration = self.parameters.absolute_period_duration
            else:
                integral_model.optimize()
                flow_data, departures_data, departures_dict = integral_model.output_data(write_results=True)

            percents.display_percent()

            # Подготовка параметров для модели назначения АЗС

            h_params = {'flow_data': flow_data,
                        'departures_data': departures_data,
                        'departures_dict': departures_dict,
                        'current_shift_id': shift}

            # Запуск модели перепривязки АЗС. Получение результата

            asu_nb_connecting_result = asu_nb_connection.calculate(
                h_params, self.data, output_states_collection=output_states_collection)

            # Обновляем привязки в static data

            asu_nb_connection.update_static_data(self.data, asu_nb_connecting_result)

            # Обновляем результат интегральной модели для учёта перепривязки

            u_flow_data, u_departures_data, u_departures_dict = \
                asu_nb_connection.update_integral_output(flow_data,
                                                         departures_data,
                                                         departures_dict,
                                                         asu_nb_connecting_result,
                                                         self.data,
                                                         update_departures=True)

            # Перезапись основного файла интегральной модели с результатами перепривязки
            writer = pd.ExcelWriter('./output/integral_model_from_%d_to_%d.xlsx' %
                                    (integral_model.period_start,
                                     integral_model.period_start + integral_model.period_duration - 1))
            u_flow_data.to_excel(writer, 'volumes')
            u_departures_data.to_excel(writer, 'departures')
            writer.save()

            percents.display_percent()

            return u_flow_data, u_departures_data, u_departures_dict
        else:
            integral_model = IntegralModel(parameters=self.parameters,
                                           data=self.data,
                                           initial_state=self.initial_state,
                                           period_start=shift,
                                           period_duration=self.parameters.absolute_period_duration,
                                           constraint_switcher=self.constraint_switcher,
                                           previous_period_loaded_sku=self.previous_period_loaded_sku,
                                           output_states_collection=output_states_collection)

            integral_model.optimize()
            flow_data, departures_data, departures_dict = integral_model.output_data(write_results=True)

            return flow_data, departures_data, departures_dict

    '''Run detailed planning Iterative version'''

    def detailed_model_iterative_run(self, shift, flow_data, departures_dict, fuel_to_load_corrections,
                                     departure_corrections, used_truck_set, truck_loaded, output_states_collection,
                                     solve_flag):
        # for time in [converter_day_to_shift(day), converter_day_to_shift(day) + 1]:
        pd_parameters = DParameters(shift, self.path)
        '''Trucks used in previous shift update'''
        pd_parameters.trucks_used = used_truck_set
        '''Trucks own'''
        pd_parameters.own_trucks = [truck for truck in self.data.vehicles if self.data.vehicles[truck].is_own == 1]
        '''Trucks loaded'''
        pd_parameters.truck_loaded = truck_loaded
        '''Asu_tank time to death'''
        pd_parameters.asu_tank_death = {(asu, n): output_states_collection.get_time_to_death(shift - 1, asu, n)
                                        for asu, n in self.data.tank_sku}
        parse_data = ModelsConnector(initial_states=self.initial_state,
                                     fuel_to_load=flow_data,
                                     time=shift,
                                     departures_dict=departures_dict,
                                     data=self.data,
                                     dp_parameters=pd_parameters,
                                     fuel_to_load_corrections=fuel_to_load_corrections,
                                     departure_corrections=departure_corrections)

        load_info = parse_data.convert_data()  # load_info: {asu_id: {(asu_id, n): [integral load, empty space)] ...} ... }
        pd_parameters.load_info = load_info.copy()

        # Truck filter for load_after
        truck_set = {truck_num: self.data.vehicles[truck_num].sections_volumes for truck_num in self.data.vehicles}
        print(truck_set)

        print(
            "<FOR_USER>\nНачало планирования загрузок БВ " + ("на текущую смену." if solve_flag else " под сменщика."))
        print('</FOR_USER>')
        self.parameters.pool = multiprocessing.Pool(processes=self.parameters.core_count)  # Pool creating
        try:
            penalty_set, pd_parameters.truck_load_volumes, pd_parameters.truck_load_sequence = \
                every_route_load_parallel(truck_set, parse_data, pd_parameters, self.data, self.parameters, list(),
                                          False)
        except (KeyboardInterrupt, SystemExit):
            sys.exit()
        finally:
            self.parameters.pool.close()
            self.parameters.pool.terminate()
            self.parameters.pool.join()
            self.parameters.__getstate__()
        print("<FOR_USER>\nЗавершение планирования загрузок БВ " + (
            "на текущую смену." if solve_flag else " под сменщика."))
        print('</FOR_USER>')
        delete_phantom_loads(pd_parameters.load_info, pd_parameters.shifting_load_info)
        pd_parameters.double_trip_probs_dict = asu_truck_double_probs(penalty_set, list(load_info.keys()), self.data,
                                                                      pd_parameters,
                                                                      any_trip_duration_check)
        print('double_trip_probs')
        print(pd_parameters.double_trip_probs_dict)

        # ------------------------------------------------------------------------------------------------------------------------
        TripOptimization = namedtuple('TripOptimization',
                                      'set_direct set_distribution set_direct_double set_distribution_double depot_queue')
        result_trip_optimization = dict()
        iteration_init = 1
        sorted_asu_tuple = sort_asu_by_death(pd_parameters, self.data)
        asu_groups = split_asu(sorted_asu_tuple, pd_parameters)

        data_iter = copy.deepcopy(self.data)
        dp_parameters_iter = copy.deepcopy(pd_parameters)
        dp_parameters_iter.double_trip_probs = True
        asu_visited_iter = []
        trips_on_the_truck = {truck: 0 for truck in truck_set}  # Number of trips on truck {truck_num: amount}
        truck_asu_iter_type_dict = []
        used_reallocations = {}
        truck_set_iter = copy.deepcopy(truck_set)

        parse_data_iter = copy.deepcopy(parse_data)
        parse_data_iter.data = data_iter
        parse_data_iter.dp_parameters = dp_parameters_iter
        parse_data_iter.departures = {(asu, pd_parameters.time): sorted_asu_tuple.count(asu)
                                      for asu in set(sorted_asu_tuple)}
        pd_parameters.route_depots.clear()
        print('sorted_asu_tuple')
        print(sorted_asu_tuple)
        print('asu_groups')
        print(asu_groups)
        print('departures')
        print(parse_data_iter.departures)
        print('load_info')
        print(load_info)
        print('depot restrict')
        print(data_iter.restricts)
        print('reallocation')
        print({k: v for k, v in data_iter.asu_depot_reallocation.items() if k[-1] == dp_parameters_iter.time})
        print('used_reallocations')
        print(used_reallocations)

        percents.display_percent()
        percents.set_asu_group_count(len(asu_groups))

        for package_id, asu_package in enumerate(
                asu_groups):  # TODO во flow data и departures не переносятся неиспользованные азс с прошлой смены
            print('------------ Trip_optimization iteration No %.1f ----------------' % iteration_init)
            if iteration_init % 1 == 0:
                asu_package = [i for i in asu_package if i not in asu_visited_iter]
            else:
                asu_package = []
                for package in reversed(asu_groups[:(package_id + 1)]):
                    for asu in reversed(package):
                        if asu not in asu_visited_iter and all(map(lambda x: dp_parameters_iter.asu_decoder(x) !=
                                                                             dp_parameters_iter.asu_decoder(asu),
                                                                   asu_package)):
                            asu_package.insert(0, asu)
            print(asu_package)

            print('##########Filter integral result for reallocation')
            "Filter integral result for reallocation"
            package_integral_result = filter_integral_model_results(parse_data_iter.fuel_to_load,
                                                                    parse_data_iter.departures,
                                                                    asu_package, dp_parameters_iter)
            print('flow_data')
            print(package_integral_result[0])
            print('departures')
            print(package_integral_result[2])

            print('##########Reallocation')
            "Reallocation"
            package_reallocation_result = depot_allocation_treat(*package_integral_result, shift, data_iter,
                                                                 output_states_collection, used_reallocations)
            package_flow_data, package_departures_data, package_departures_dict = package_reallocation_result
            print('flow_data')
            print(package_flow_data)
            print('departures')
            print(package_departures_dict)
            print('reallocation')
            print({k: v for k, v in data_iter.asu_depot_reallocation.items() if k[-1] == dp_parameters_iter.time})

            # TODO Пересчитать группы, если произошло деление азс

            print('##########Update integral result after reallocation')
            "Update integral result after reallocation"
            parse_data_iter.fuel_to_load, parse_data_iter.departures = \
                update_integral_model_results(package_flow_data, package_departures_dict,
                                              parse_data_iter.fuel_to_load, parse_data_iter.departures,
                                              asu_package, dp_parameters_iter)

            print('departures')
            print(parse_data_iter.departures)
            print('load_info')
            print(dp_parameters_iter.load_info)
            print('basic_asu_depot_connections')
            print(data_iter.asu_depot)

            "Delete shifting np for loading"
            depot_restricts_iter = data_iter.restricts
            data_iter.restricts = remote_shifting_np(data_iter, dp_parameters_iter)

            "Truck loads"  # Это самый долгий процесс
            print("<FOR_USER>\nНачало планирования загрузок БВ " +
                  (("на текущую смену (iteration No %.1f)." % iteration_init) if solve_flag else " под сменщика."))
            print('</FOR_USER>')
            self.parameters.pool = multiprocessing.Pool(processes=self.parameters.core_count)  # Pool creating
            try:
                penalty_set, dp_parameters_iter.truck_load_volumes, dp_parameters_iter.truck_load_sequence = \
                    every_route_load_parallel(truck_set, parse_data_iter, dp_parameters_iter,
                                              data_iter, self.parameters, asu_package)
            except (KeyboardInterrupt, SystemExit):
                sys.exit()
            finally:
                self.parameters.pool.close()
                self.parameters.pool.terminate()
                self.parameters.pool.join()
                self.parameters.__getstate__()
            print("<FOR_USER>\nЗавершение планирования загрузок БВ " +
                  ("на текущую смену." if solve_flag else "под сменщика."))
            print('</FOR_USER>')
            print("penalty_set")
            print(penalty_set)
            print("route depots")
            print(dp_parameters_iter.route_depots)

            data_iter.restricts = depot_restricts_iter

            "Update full dp_parameters"
            pd_parameters.truck_load_volumes.update(dp_parameters_iter.truck_load_volumes)
            pd_parameters.truck_load_sequence.update(dp_parameters_iter.truck_load_sequence)

            print('##########Filter the asu for calculations')
            "Filter the asu for calculations"
            penalty_set_iter = {key: penalty for key, penalty in penalty_set.items()
                                if set(key[1]).intersection(asu_package) and trips_on_the_truck[key[0]] < 2}
            load_info_iter = {asu: val for asu, val in dp_parameters_iter.load_info.items() if
                              asu in asu_package}  # Развозы с АЗС из другой группы --- не влияют на целевую функцию
            asu_in_model = list(set((itertools.chain(*list([key[1] for key in
                                                            penalty_set_iter.keys()])))))  # asu to visit (not only package, but trips with distribution)
            print('penalty_set_iter')
            print(penalty_set_iter)
            print('volumes')
            print(dp_parameters_iter.truck_load_volumes)
            print('tanks')
            print(dp_parameters_iter.truck_load_sequence)
            print('load_info_iter')
            print(load_info_iter)
            print('asu_in_model')
            print(asu_in_model)

            print('##########Run trip_optimization on pack')
            "Run trip_optimization on pack"
            if len(asu_groups) == package_id + 1:
                dp_parameters_iter.clear_shifting_routes = False
            result_trip_optimization[iteration_init] = TripOptimization(
                *minimize_penalties_iter(penalty_set_iter,
                                         load_info_iter,
                                         dp_parameters_iter,
                                         data_iter,
                                         asu_in_model,
                                         asu_visited_iter,
                                         trips_on_the_truck, iteration_init))
            print('set_direct')
            print(result_trip_optimization)
            print('set_distribution')
            print(result_trip_optimization[iteration_init].set_distribution)
            print('set_direct_double')
            print(result_trip_optimization[iteration_init].set_direct_double)
            print('set_distribution_double')
            print(result_trip_optimization[iteration_init].set_distribution_double)
            print('depot_queue')
            print(result_trip_optimization[iteration_init].depot_queue)

            print('##########Update routes')
            "Update routes"
            truck_asu_iter_type_dict.extend([(key, iteration_init, 'set_direct')
                                             for key in result_trip_optimization[iteration_init].set_direct])
            truck_asu_iter_type_dict.extend([(key, iteration_init, 'set_distribution')
                                             for key in result_trip_optimization[iteration_init].set_distribution])
            update_truck_trip_amount(trips_on_the_truck, result_trip_optimization[iteration_init])

            # Фильтр БВ по количеству рейсов (если 2 рейса, то БВ долой)
            truck_set_iter = {truck: val for truck, val in truck_set_iter.items() if trips_on_the_truck[truck] < 2}

            print('##########Update asu, depots, integral result, used reallocation')
            "Update asu, depots, integral result, used reallocation"
            # Блоки в работе азм проставляются в trip_optimization
            cut_out_trip_optimization_result(result_trip_optimization[iteration_init],
                                             parse_data_iter.fuel_to_load, parse_data_iter.departures,
                                             used_reallocations, data_iter, dp_parameters_iter)
            pd_parameters.route_depots.update(dp_parameters_iter.route_depots)
            print('departures')
            print(parse_data_iter.departures)
            print('load_info')
            print(dp_parameters_iter.load_info)
            print('asu volume')
            print(data_iter.volumes_to_add)
            print('asu block')
            print(data_iter.block_window_asu)
            print('depot restrict')
            print(data_iter.restricts)
            print('used_reallocations')
            print(used_reallocations)

            if iteration_init % 1 == 0:
                unvisited_asu = [asu for asu in asu_package if asu not in asu_visited_iter]
                if (unvisited_asu and unvisited_asu != asu_package) or \
                        (len(asu_groups) == package_id + 1 and dp_parameters_iter.shifting_routes):
                    asu_groups.insert(package_id + 1, unvisited_asu)
                else:
                    iteration_init += 0.5

            iteration_init += 0.5
            dp_parameters_iter.set_partial_package_flag(iteration_init)

            if iteration_init % 1 == 0 and len(asu_groups) > package_id + 1:
                percents.display_percent()

        # ------------------------------------------------------------------------------------------------------------------------
        set_direct, set_distribution, set_direct_double, set_distribution_double, depot_queue = get_result_sets(
            result_trip_optimization)
        set_double_distribution_double = trip_union(trips_on_the_truck, truck_asu_iter_type_dict, set_direct,
                                                    set_distribution,
                                                    set_direct_double, set_distribution_double)
        self.data.restricts.update(data_iter.restricts)

        "Открытия на первый день для вечерней смены включают открытия следующего дня"
        if self.parameters.absolute_period_start == 2 and shift == 2:
            for (depot, depot_sku, day) in list(self.data.restricts):
                if day == 1:
                    volume = self.data.restricts[depot, depot_sku, day]
                    self.data.restricts[depot, depot_sku, 2] = min(volume,
                                                                   self.data.restricts.get((depot, depot_sku, 2),
                                                                                           10 ** 10))

        print("route depots")
        print(pd_parameters.route_depots)

        fill_empty_sections(set_direct, set_distribution, set_direct_double, set_distribution_double,
                            pd_parameters, parse_data, self.data, next_shift_permission=True,
                            next_shift_strong=all(day[-1] != shift for day in self.day_shift_connection().values()))

        return set_direct, set_distribution, set_direct_double, set_distribution_double, set_double_distribution_double, depot_queue, pd_parameters

    def update_initial_state_by_loads(self, loaded_volumes: dict):
        for asu_n in loaded_volumes:
            self.initial_state[asu_n] += loaded_volumes[asu_n]

    def update_initial_state_by_consumption(self, time):
        consumption_filtered = {(asu, n): self.data.consumption[asu, n, t] for asu, n, t in self.data.consumption if
                                t == time}
        for asu_n in consumption_filtered:
            self.initial_state[asu_n] -= consumption_filtered[asu_n]

    def update_initial_state_by_planned_load(self, time):  # TODO Катя добавляет. Эта функция возможно не работает.
        planned_load_filtered = {(asu, n): self.data.volumes_to_add[asu, n, t] for asu, n, t in self.data.volumes_to_add
                                 if t == time}
        for asu_n in planned_load_filtered:
            self.initial_state[asu_n] += planned_load_filtered[asu_n]

    def update_previous_period_loaded_sku(self, loaded_volumes: dict):
        for asu_n in loaded_volumes:
            self.previous_period_loaded_sku[self.data.tank_sku[asu_n]] += loaded_volumes[asu_n]

    """Update initial volumes. Including consumption and loads"""  # Не используется

    def update_initial_state(self, loaded_volumes: dict, time):
        self.update_initial_state_by_loads(loaded_volumes)
        self.update_initial_state_by_consumption(time)

    def day_shift_connection(self):
        day_shift = {}
        for shift in range(self.planning_start, self.planning_start + self.planning_duration):
            if (shift + 1) // 2 in day_shift:
                day_shift[(shift + 1) // 2].append(shift)
            else:
                day_shift[(shift + 1) // 2] = [shift]
            # Дополнительная смена для загрузки под сменщика
            if shift + 1 == self.planning_start + self.planning_duration:
                day_shift[(shift + 1) // 2].append(shift + 1)
        return day_shift

    @staticmethod
    def calculate_integral_models_result_correction(loads_results, pd_parameters):
        diff_dict = {}
        for asu, asu_dict in pd_parameters.load_info.items():
            for asu_n, (load_volume, empty_space) in asu_dict.items():
                real_asu_n = (pd_parameters.asu_decoder(asu), asu_n[-1])
                if real_asu_n in diff_dict:
                    continue
                elif real_asu_n in loads_results:
                    diff_dict[real_asu_n] = load_volume - loads_results[real_asu_n]
                else:
                    print("Asu = %d and n = %d isn't loaded in detailed model" % real_asu_n)
                    diff_dict[real_asu_n] = load_volume
        return diff_dict

    @staticmethod
    def calculate_departure_correction(output_collection, integral_departures_dict, departure_corrections, shift):

        departures = ModelsConnector.correct_departures(integral_departures_dict, departure_corrections, shift)

        diff_dict = {asu: count for (asu, time), count in departures.items() if time == shift}

        for asu, truck in output_collection.set_direct:
            asu = output_collection.pd_parameters.asu_decoder(asu)
            if asu in diff_dict:
                diff_dict[asu] -= 1

        for asu1, asu2, truck in output_collection.set_distribution:
            asu1 = output_collection.pd_parameters.asu_decoder(asu1)
            asu2 = output_collection.pd_parameters.asu_decoder(asu2)
            for asu in (asu1, asu2):
                if asu in diff_dict:
                    diff_dict[asu] -= 1

        for asu1, asu2, truck in output_collection.set_direct_double:
            asu1 = output_collection.pd_parameters.asu_decoder(asu1)
            asu2 = output_collection.pd_parameters.asu_decoder(asu2)
            for asu in (asu1, asu2):
                if asu in diff_dict:
                    diff_dict[asu] -= 1

        for asu1, asu2, asu3, truck in output_collection.set_distribution_double:
            asu1 = output_collection.pd_parameters.asu_decoder(asu1)
            asu2 = output_collection.pd_parameters.asu_decoder(asu2)
            asu3 = output_collection.pd_parameters.asu_decoder(asu3)
            for asu in (asu1, asu2, asu3):
                if asu in diff_dict:
                    diff_dict[asu] -= 1

        diff_dict = {asu: count for asu, count in diff_dict.items()
                     if count and output_collection.data.asu_work_shift[asu][shift % 2 + 1]}

        return diff_dict

    def general_start(self, read_integral=False, package=False):
        """Сборщик состояний баков с течением времени"""
        output_states_collection = OutputCreatorStations(data=self.data,
                                                         parameters=self.parameters,
                                                         init_states=self.initial_state,
                                                         time_zero=self.planning_start - 1)

        day_shift = self.day_shift_connection()
        print(day_shift)

        """Сборщик загрузок секций в БВ"""
        output_section_load_collection = []

        schedule = Schedule(self.data, self.parameters, start_time=self.planning_start, duration=self.planning_duration)
        """Used trucks at init time"""
        used_truck_set = []
        """Truck is loaded"""
        truck_loaded = {}

        integral_model = None

        for day in day_shift:
            if not read_integral:
                percents.set_integral_time_limit(self.parameters.time_limit)
            if not read_integral:
                print("<FOR_USER>\nНачало расчета интегральной модели.\n</FOR_USER>")
                flow_data, departures_data, departures_dict = self.integral_model_run(min(day_shift[day]),
                                                                                      output_states_collection,
                                                                                      read_integral)
                print("<FOR_USER>\nЗавершение расчета интегральной модели.\n</FOR_USER>")
            else:
                if package:
                    "Если пакетная оптимизация, то НБ нужно определить."
                    flow_data, departures_data, departures_dict = self.integral_model_run(min(day_shift[day]),
                                                                                          output_states_collection,
                                                                                          read_integral)
                else:
                    integral_model = IntegralRead(self.path + '/integral_model.xlsx', self.data, min(day_shift[day]))
                    flow_data = integral_model.pd_flows
                    departures_dict = integral_model.departures

            fuel_to_load_corrections = {}
            departure_corrections = {}

            for shift in day_shift[day]:
                if integral_model:
                    integral_model.allocation_update(shift)

                '''Run detailed planning'''
                solve_flag = shift != self.planning_start + self.planning_duration

                # set_direct, set_distribution, set_direct_double, set_distribution_double, set_double_distribution_double, depot_queue, pd_parameters = \
                #     self.detailed_model_run(shift, flow_data, departures_dict, fuel_to_load_corrections, departure_corrections,
                #                             used_truck_set, truck_loaded, output_states_collection, solve_flag)

                set_direct, set_distribution, set_direct_double, set_distribution_double, set_double_distribution_double, depot_queue, pd_parameters = \
                    self.detailed_model_iterative_run(shift, flow_data, departures_dict, fuel_to_load_corrections,
                                                      departure_corrections,
                                                      used_truck_set, truck_loaded, output_states_collection,
                                                      solve_flag)

                '''Update the init states with results from previous shift results'''
                self.update_initial_state_by_consumption(shift)
                '''Update the init states with planed load'''
                self.update_initial_state_by_planned_load(shift)

                '''Collect results'''
                output_collection = OutputCreatorTrips(set_direct=set_direct,
                                                       set_distribution=set_distribution,
                                                       set_direct_double=set_direct_double,
                                                       set_distribution_double=set_distribution_double,
                                                       set_double_distribution_double=set_double_distribution_double,
                                                       depot_queue=depot_queue,
                                                       pd_parameters=pd_parameters,
                                                       data=self.data)

                used_truck_set = output_collection.truck_used_set()
                '''Collect result into dict'''
                loads_results = output_collection.trip_load_info_to_dict()
                output_section_load_collection.extend(output_collection.trip_load_info)

                loads_results_pandas = output_collection.collect_into_pandas(write_results=True)
                '''Loaded fuel to be corrected for next shift'''
                fuel_to_load_corrections = self.calculate_integral_models_result_correction(loads_results,
                                                                                            pd_parameters)
                '''Canceled departures to be added to next shift'''
                departure_corrections = self.calculate_departure_correction(output_collection, departures_dict,
                                                                            departure_corrections, shift)
                '''Update initial volumes - detailed planning loads'''
                self.update_initial_state_by_loads(loads_results)
                '''Update asu_states_pandas period load volumes'''
                self.update_previous_period_loaded_sku(loads_results)
                '''Add states'''
                output_states_collection.add_all_new_states(truck_loads=loads_results, shift=shift)
                '''Write states'''
                asu_states_pandas = output_states_collection.collect_into_pandas(True)
                '''Time table creating'''
                print("<FOR_USER>\nНачало оптимизации расписания.\n</FOR_USER>")
                shift_timetable = TimetableCreator(pd_parameters.time, loads_results_pandas, truck_loaded, depot_queue,
                                                   self.parameters, self.data, pd_parameters)

                percents.display_percent()
                shift_timetable.calculate_timetable(last_shift=not solve_flag, percents=percents)
                print("<FOR_USER>\nЗавершение оптимизации расписания.\n</FOR_USER>")
                '''Schedule writing'''
                schedule.update_data(shift_timetable.collect_into_pandas(write_results=True), asu_states_pandas,
                                     write_file=True, file_name='car_schedule_%d.xlsx' % shift)
                percents.display_percent()

        """Это жизненная необходимость"""
        tripLoadDataFrame = pd.DataFrame(output_section_load_collection,
                                         columns=['asu', 'n', 'sku', 'shift', 'truck', 'section_number',
                                                  'section_volume', 'is_empty',
                                                  'should_be_empty', 'trip_number', 'is_critical', 'days_to_death'])

        writer = pd.ExcelWriter('./output/truck_loads.xlsx')
        tripLoadDataFrame.to_excel(writer, 'truck_loads')
        writer.save()

        schedule.write_schedule_file()
        TimetableCreator.collect_full_timetable_into_pandas(self.data, self.planning_start + self.planning_duration,
                                                            write_results=True)
