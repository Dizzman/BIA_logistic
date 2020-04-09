import time
import pandas as pd
from data_reader.input_data import StaticData, Parameters
from detailed_planning.dp_parameters import DParameters
from timetable_calculator.timetable_model import TimetableModel
from timetable_calculator.classes import TruckRoute, TruckTrip
from ploter.vehicle_graph import plot_vehicle_graph
from detailed_planning.trip_optimization import define_asu_windows
from detailed_planning.best_truck_load_linear import define_depot

"""Create optimal shift timetable"""


class TimetableCreator:
    def __init__(self, shift: int, loads_result_pandas: pd.DataFrame, truck_loaded: dict, depot_queue_dict: list,
                 parameters: Parameters, data: StaticData, pd_parameters: DParameters):
        self.loads_result_pandas = loads_result_pandas
        self.parameters = parameters
        self.data = data
        self.pd_parameters = pd_parameters
        self.time = shift
        self.shift = 2 - self.time % 2
        self.truck_routes = self.get_truck_routes_from_pandas()
        self.add_useless_trucks()
        self.load_before = truck_loaded  # {Truck: [Depot]}
        self.load_after = {truck: [depot for depot, capacity in data.depot_capacity.items()
                                   if capacity and data.depot_vehicles_compatibility(truck, depot)]
                           for truck in self.truck_routes if self.data.vehicles[truck].load_after}  # {Truck: [Depot]}
        self.depot_queue_dict = depot_queue_dict
        self.initial_depot_queue = {}
        self.initial_waitings = []
        self.solve = True
        self.last_shift = False

    timetable_solution_list = []

    """Create and solve timetable model"""
    def calculate_timetable(self, solve=True, last_shift=False, percents=None):

        self.solve = solve
        self.last_shift = last_shift
        start_time = time.time()
        print('=== Start solve timetable problem shift = %d' % self.time)

        double_routes, reverse_routes = [], []  # self.copy_two_trips_routes()

        self.set_load_before_to_routes()
        if not last_shift:
            self.set_load_after_to_routes()

        self.initial_depot_queue, *self.initial_waitings = self.get_initial_depot_queue()
        initial_full_table = self.get_initial_full_timetable_in_pandas()
        plot_vehicle_graph(initial_full_table, self.pd_parameters.shift_size, self.pd_parameters.shift_start_time,
                           self.data.vehicles_busy_hours, self.data.vehicles_cut_off_shift, self.data.vehicles_busy,
                           self.data.vehicles, 'output/vehicle_graph_initial_%d.xlsx' % self.time)

        timetable_model = TimetableModel(self.time, self.parameters, self.data, solve)
        timetable_model.create_model(self.truck_routes, double_routes)

        if solve:
            timetable_model.set_start_solution(self.initial_depot_queue)
            timetable_model.optimize(1)
            percents.display_percent()
            timetable_model.update(self.truck_routes)
            timetable_model.optimize(2)
            timetable_model.strong_update(self.truck_routes)
            timetable_model.optimize(10)
            timetable_model.check_result()
            percents.display_percent()
        else:
            timetable_model.set_start_solution(self.initial_depot_queue, *self.initial_waitings)

        self.clear_two_trips_routes(timetable_model.get_double_route_var_result(), reverse_routes)

        self.fill_route_waitings(timetable_model.get_asu_waiting_var_result(),
                                     timetable_model.get_depot_waiting_var_result())

        # last_shift and self.cut_double_routes()
        self.update_load_after(timetable_model.get_load_after_var_result())
        self.update_depot_queue_decrease()
        self.update_asu_blocks()

        self.clear_last_shifts()

        if not last_shift:
            self.fill_busy_status()
        else:
            self.return_uet()

        TimetableCreator.timetable_solution_list.append(self)

        print('=== End solve timetable problem shift = %d (%d sec)' % (self.time, time.time() - start_time))

    """Divide double route on direct and reverse"""
    def copy_two_trips_routes(self):
        double_routes = []
        reverse_routes = []
        for truck in self.truck_routes.copy():
            route = self.truck_routes[truck]
            if route.is_two_trips:
                first_trip_number = self.define_critical_trip_number(route)
                if first_trip_number == 1:
                    pass
                elif first_trip_number == 2:
                    reverse_route = route.reversed_copy()
                    self.truck_routes[truck] = reverse_route
                    reverse_routes.append(truck)
                else:
                    direct_route = route.copy()
                    reverse_route = route.reversed_copy()
                    direct_route.truck = truck + 1000
                    reverse_route.truck = truck + 2000
                    self.truck_routes[direct_route.truck] = direct_route
                    self.truck_routes[reverse_route.truck] = reverse_route
                    double_routes.append(truck)
                    self.truck_routes.pop(truck)
        return double_routes, reverse_routes

    """Define is double route fix for asu death, return first trip number or 0"""
    def define_first_trip_number(self, route):
        min_time = 999
        closed_asu = []
        first_trip = 0
        for trip_number, trip in enumerate(route.trips):
            trip_min_time_to_death = min(self.pd_parameters.asu_tank_death[asu, tank]
                                     for asu in trip.tanks for tank in trip.tanks[asu])
            if trip_min_time_to_death < min_time:
                min_time = trip_min_time_to_death
                first_trip = trip_number + 1
            elif trip_min_time_to_death == min_time:
                first_trip = 0
            next_shift = self.time % 2 + 1
            asu_work = 0
            asu_work += sum(1 for asu in trip.route if self.data.asu_work_shift[asu][next_shift] == 0)
            if asu_work:
                closed_asu.append(trip_number + 1)
        if min_time <= 0.5 * 1 and first_trip:  # просушка меньше 1 смен в приоритете
            return first_trip
        if len(closed_asu) == 1:  # не работающая азс в следующую смену в приоритете
            return closed_asu[0]
        if min_time <= 1.25 and len(closed_asu) == 2:  # если обе азс не работают, то на просыхающую
            return first_trip
        return 0

    """Define is double route fix for asu critical, return first trip number or 0"""
    def define_critical_trip_number(self, route):
        criticals = []
        for trip_number, trip in enumerate(route.trips):
            if trip.is_critical:
                criticals.append(trip_number + 1)
        if len(criticals) == 1:
            return criticals[0]
        return 0

    """Delete not chosen double route"""
    def clear_two_trips_routes(self, double_route_result: dict, reverse_routes: list):
        for truck, result in double_route_result.items():
            used_truck_number = (round(result, 0) + 1) * 1000 + truck
            unused_truck_number = (2 - round(result, 0)) * 1000 + truck
            self.truck_routes[truck] = self.truck_routes[used_truck_number]
            self.truck_routes.pop(used_truck_number)
            self.truck_routes.pop(unused_truck_number)
        for truck in reverse_routes:
            self.truck_routes[truck].truck = 2000 + truck

    """Fill route waitings according to calc"""
    def fill_route_waitings(self, asu_waiting_var_result: dict, depot_waiting_var_result: dict):
        for (truck, asu, trip_number, asu_number), value in asu_waiting_var_result.items():
            truck = truck % 1000
            if round(value, 3) == 0:
                continue
            self.truck_routes[truck].waiting_times[asu, trip_number] = value
        for (truck, depot, trip_number), value in depot_waiting_var_result.items():
            truck = truck % 1000
            if round(value, 3) == 0:
                continue
            self.truck_routes[truck].waiting_times[depot, trip_number] = value

    """Clear last load in last shifts"""
    def clear_last_shifts(self):
        if not TimetableCreator.timetable_solution_list:
            return
        truck_set = set(truck for truck, route in self.truck_routes.items())
        while truck_set:
            truck = truck_set.pop()
            route = self.truck_routes[truck]
            for last_timetable in reversed(TimetableCreator.timetable_solution_list):
                if truck in last_timetable.truck_routes:
                    last_route = last_timetable.truck_routes[truck]
                    if route.is_load_before:
                        last_route.route_structure['depot3'] = route.route_structure['depot1']
                    else:
                        if truck in last_timetable.load_after:
                            last_timetable.load_after.pop(truck)
                    break

    def collect_routes(self):
        new_depot_queue_dict = []
        queue_trucks = {}

        for key in self.depot_queue_dict:
            depot, time_interval, truck, trip_route, trip_number = key

            route = []
            for tr in trip_route:
                trip = []
                for asu in tr:
                    decoded_asu = self.pd_parameters.asu_decoder(asu)
                    if decoded_asu not in trip:
                        trip.append(decoded_asu)
                trip = tuple(trip)
                route.append(trip)
            key = depot, time_interval, truck, tuple(route), trip_number

            queue_trucks.setdefault(truck, []).append(key)

        for truck, queue_list in queue_trucks.items():
            if len(queue_list) == 1 and \
                    any(map(lambda x: x in self.truck_routes and len(self.truck_routes[x].trips) == 1,
                            (truck + version * 1000 for version in (0, 1, 2)))):
                new_depot_queue_dict.extend(queue_list)
                continue
            if len(queue_list) == 2 and len(queue_list[0][3]) == 2:
                new_depot_queue_dict.extend(queue_list)
                continue
            if len(queue_list) == 2:
                queue_list.sort(key=lambda x: x[1])
                full_route = (queue_list[0][3][0], queue_list[1][3][0])
                for version in (0, 1, 2):
                    changed_truck = truck + version * 1000
                    if changed_truck not in self.truck_routes:
                        continue
                    route = self.truck_routes[changed_truck]
                    truck_route = tuple(trip.route for trip in route.trips)
                    if truck_route == full_route:
                        queue_list[0] = (*queue_list[0][:3], truck_route, 0)
                        queue_list[1] = (*queue_list[1][:3], truck_route, 1)
                        new_depot_queue_dict.extend(queue_list)
                        break
            if len(queue_list) == 1:
                for version in (0, 1, 2):
                    changed_truck = truck + version * 1000
                    if changed_truck not in self.truck_routes:
                        continue
                    route = self.truck_routes[changed_truck]
                    truck_route = tuple(trip.route for trip in route.trips)
                    if truck_route[1] == queue_list[0][3][-1]:
                        queue_list[0] = (*queue_list[0][:3], truck_route, 1)
                        new_depot_queue_dict.extend(queue_list)
                        break
        self.depot_queue_dict = new_depot_queue_dict

    def get_initial_depot_queue(self):
        initial_depot_queue = {}
        initial_waitings = {}
        initial_depot_waitings = {}
        initial_asu_waitings = {}

        depot_queue_intervals = {depot: [tuple(round(t, 2) for t in i) for i
                                         in self.data.get_depot_decrease_for_extended_shift(depot, self.pd_parameters.time, 12, 12)]
                                 for depot in self.data.depot_capacity}
        used_trucks = []

        def get_free_depot_queue_time(depot, time, load):
            load_time = self.data.depot_load_time[depot]
            for block in self.data.get_depot_blocks_for_extended_shift(depot, self.pd_parameters.time, 12, 12):
                if block[0] - load_time < time < block[1]:
                    return get_free_depot_queue_time(depot, block[1], load)
            intervals = depot_queue_intervals[depot]
            filtered_intervals = [i for i in intervals if time <= i[0] < time + load]
            for interval in [(time, time + load), *filtered_intervals]:
                count = 0
                closest_end = 10**10
                for another_interval in [(time, time + load), *intervals]:
                    if another_interval[0] <= interval[0] < another_interval[1]:
                        count += 1
                        closest_end = min(closest_end, another_interval[1])
                capacity = self.data.depot_capacity[depot]
                if count > capacity:
                    return get_free_depot_queue_time(depot, closest_end + 0.01, load)
            depot_queue_intervals[depot].append((time, time + load))
            depot_queue_intervals[depot].sort()
            return round(time, 2)

        print(self.depot_queue_dict)
        print({truck: tuple(trip.route for trip in route.trips) for truck, route in self.truck_routes.items()})
        self.collect_routes()
        self.depot_queue_dict.sort(key=lambda x: x[1])
        print(self.depot_queue_dict)
        for key in self.depot_queue_dict:
            depot, time_interval, truck, trip_route, trip_number = key

            for version in (0, 1, 2):
                changed_truck = truck + version * 1000
                if changed_truck not in self.truck_routes:
                    continue
                initial_waitings.setdefault(changed_truck, [])
                route = self.truck_routes[changed_truck]
                truck_route = tuple(trip.route for trip in route.trips)
                if truck_route == trip_route:
                    if trip_number == 1 and initial_depot_queue.setdefault(changed_truck, {}).get(0, None) is None:
                        for index, asu in enumerate(route.trips[0].route):
                            asu_arrival_time = route.get_arrival_time('asu1%d' % (index + 1)) + \
                                               sum(initial_waitings[changed_truck])
                            unload = route.get_working_time('asu%d%d' % (trip_number + 1, index + 1))
                            max_duration = self.parameters.shift_size * 2 if route.is_long_route \
                                else self.data.vehicles[route.truck % 1000].shift_size
                            asu_windows = define_asu_windows(asu_arrival_time, asu, self.time,
                                                             unload, max_duration, self.data)
                            if asu_windows:
                                start_asu_window = asu_windows[0][0]
                                asu_waiting_time = max(start_asu_window - asu_arrival_time, 0)
                            else:
                                asu_waiting_time = 0
                            initial_waitings[changed_truck].append(round(asu_waiting_time, 2))
                            initial_asu_waitings.update({(changed_truck, asu, 0, index): round(asu_waiting_time, 2)})
                    arrival_time = route.get_arrival_time('depot%d' % (trip_number + 1)) + \
                                           sum(initial_waitings[changed_truck])
                    load_time = self.data.depot_load_time[depot]
                    load = load_time + 0.01
                    time_interval = get_free_depot_queue_time(depot, round(arrival_time, 2), load)
                    initial_depot_queue.setdefault(changed_truck, {}).update({trip_number: time_interval})
                    used_trucks.append(truck)
                    depot_waiting_time = max(time_interval - arrival_time, 0)
                    initial_waitings[changed_truck].append(round(depot_waiting_time, 2))
                    initial_depot_waitings.update({(changed_truck, route.trips[trip_number].depot, trip_number):
                                                       round(depot_waiting_time, 2)})
                    for index, asu in enumerate(route.trips[trip_number].route):
                        asu_arrival_time = route.get_arrival_time('asu%d%d' % (trip_number + 1, index + 1)) + \
                                           sum(initial_waitings[changed_truck])
                        unload = route.get_working_time('asu%d%d' % (trip_number + 1, index + 1))
                        max_duration = self.parameters.shift_size * 2 if route.is_long_route \
                            else self.data.vehicles[route.truck % 1000].shift_size
                        asu_windows = define_asu_windows(asu_arrival_time, asu, self.time,
                                                         unload, max_duration, self.data)
                        if asu_windows:
                            start_asu_window = asu_windows[0][0]
                            asu_waiting_time = max(start_asu_window - asu_arrival_time, 0)
                        else:
                            asu_waiting_time = 0
                        initial_waitings[changed_truck].append(round(asu_waiting_time, 2))
                        initial_asu_waitings.update({(changed_truck, asu, trip_number, index):
                                                     round(asu_waiting_time, 2)})
                    break

        for truck, route in self.truck_routes.items():
            if truck % 1000 not in used_trucks and not route.is_empty_route:
                if route.is_long_route or (route.is_load_before and not route.is_two_trips):
                    initial_waitings.setdefault(truck, [])
                    if not route.is_load_before:
                        arrival_time = route.get_arrival_time('depot1')
                        load_time = self.data.depot_load_time[route.route_structure['depot1']]
                        load = load_time + 0.01
                        time_interval = get_free_depot_queue_time(route.route_structure['depot1'],
                                                                  round(arrival_time, 2), load)
                        initial_depot_queue[truck] = {0: time_interval}
                        depot_waiting_time = max(time_interval - arrival_time, 0)
                        initial_waitings[truck].append(round(depot_waiting_time, 2))
                        initial_depot_waitings.update({(truck, route.trips[0].depot, 0): round(depot_waiting_time, 2)})
                    for index, asu in enumerate(route.trips[0].route):
                        asu_arrival_time = route.get_arrival_time('asu1%d' % (index + 1)) + \
                                           sum(initial_waitings[truck])
                        unload = route.get_working_time('asu%d%d' % (1, index + 1))
                        max_duration = self.parameters.shift_size * 2 if route.is_long_route \
                            else self.data.vehicles[route.truck % 1000].shift_size
                        asu_windows = define_asu_windows(asu_arrival_time, asu, self.time,
                                                         unload, max_duration, self.data)
                        if asu_windows:
                            start_asu_window = asu_windows[0][0]
                            asu_waiting_time = max(start_asu_window - asu_arrival_time, 0)
                        else:
                            asu_waiting_time = 0
                        initial_waitings[truck].append(round(asu_waiting_time, 2))
                        initial_asu_waitings.update({(truck, asu, 0, index): round(asu_waiting_time, 2)})
                elif self.solve:
                    print('No depot queue from trip optimization for %d' % (truck % 1000))
        print(initial_depot_queue)
        return initial_depot_queue, initial_depot_waitings, initial_asu_waitings

    def collect_into_pandas(self, write_results=False):
        if self.time == 0:
            return pd.DataFrame()

        timetable = self.get_timetable_in_pandas()
        full_timetable = self.get_full_timetable_in_pandas()
        utility = self.get_utility_in_pandas()

        if write_results:
            writer = pd.ExcelWriter('./output/timetable_shift_%d.xlsx' % self.time)
            timetable.to_excel(writer, 'timetable')
            full_timetable.to_excel(writer, 'full_timetable')
            utility.to_excel(writer, 'utility')
            writer.save()

            plot_vehicle_graph(full_timetable, self.pd_parameters.shift_size, self.pd_parameters.shift_start_time,
                               self.data.vehicles_busy_hours, self.data.vehicles_cut_off_shift, self.data.vehicles_busy,
                               self.data.vehicles, 'output/vehicle_graph_%d.xlsx' % self.time)

        return timetable

    @staticmethod
    def collect_full_timetable_into_pandas(data, last_shift, write_results=False, clear_after_saving=True):
        if not TimetableCreator.timetable_solution_list:
            return pd.DataFrame()

        timetable = pd.DataFrame()
        full_timetable = pd.DataFrame()
        utility = pd.DataFrame()

        for timetable_solution in TimetableCreator.timetable_solution_list:
            timetable = timetable.append(timetable_solution.get_timetable_in_pandas())
            full_timetable = full_timetable.append(timetable_solution.get_full_timetable_in_pandas())
            utility = utility.append(timetable_solution.get_utility_in_pandas())

        if write_results:
            writer = pd.ExcelWriter('./output/timetable.xlsx')
            timetable.to_excel(writer, 'timetable')
            full_timetable.to_excel(writer, 'full_timetable')
            utility.to_excel(writer, 'utility')
            writer.save()

            # cutted_full_timetable = full_timetable.loc[full_timetable['shift'] != last_shift]
            cutted_full_timetable = full_timetable

            plot_vehicle_graph(cutted_full_timetable, data.parameters.shift_size, data.parameters.shift_start_time,
                               data.vehicles_busy_hours, data.vehicles_cut_off_shift, data.vehicles_busy,
                               data.vehicles, 'output/vehicle_graph')

            if clear_after_saving:
                timetable.drop(timetable.index, inplace=True)
                full_timetable.drop(full_timetable.index, inplace=True)
                utility.drop(utility.index, inplace=True)
                TimetableCreator.timetable_solution_list = []

        return full_timetable

    def get_full_timetable_in_pandas(self):
        columns = ['shift', 'truck', 'location', 'operation', 'start_time', 'duration', 'end_time']
        data = []
        for truck, route in self.truck_routes.items():
            current_time = route.get_arrival_time('uet1')
            last_point = TruckRoute.route_structure[0]
            for point in TruckRoute.route_structure:
                moving_time = route.get_moving_time(point, depot3=route.route_structure['depot3'])
                waiting_time = route.get_waiting_time(point, depot3=route.route_structure['depot3'])
                working_time = route.get_working_time(point, depot3=route.route_structure['depot3'])
                if waiting_time != 0 and point.startswith('asu'):
                    data.append((self.time, truck, route.route_structure[last_point], 'ожидание', current_time, waiting_time, current_time + waiting_time))
                    current_time = current_time + waiting_time
                if moving_time != 0:
                    data.append((self.time, truck, route.route_structure[point], 'перемещение', current_time, moving_time, current_time + moving_time))
                    current_time = current_time + moving_time
                    last_point = point
                if waiting_time != 0 and not point.startswith('asu'):
                    data.append((self.time, truck, route.route_structure[point], 'ожидание', current_time, waiting_time, current_time + waiting_time))
                    current_time = current_time + waiting_time
                if working_time != 0:
                    data.append((self.time, truck, route.route_structure[point], 'слив' if point.startswith('asu') else 'налив', current_time, working_time, current_time + working_time))
                    current_time = current_time + working_time
        full_timetable = pd.DataFrame(data=data, columns=columns)
        return full_timetable

    def get_initial_full_timetable_in_pandas(self):
        columns = ['shift', 'truck', 'location', 'operation', 'start_time', 'duration', 'end_time']
        data = []
        depot_waitings, asu_waitings = self.initial_waitings
        for truck, route in self.truck_routes.items():
            if truck not in self.initial_depot_queue:
                continue
            original_truck = truck % 1000
            current_time = route.get_arrival_time('uet1')
            last_point = TruckRoute.route_structure[0]
            for point in TruckRoute.route_structure:
                moving_time = route.get_moving_time(point)

                if point.startswith('asu'):
                    waiting_time = asu_waitings.get((truck, route.route_structure[point], int(point[-2]) - 1, int(point[-1]) - 1), 0)
                elif point.startswith('depot'):
                    waiting_time = depot_waitings.get((truck, route.route_structure[point], int(point[-1]) - 1), 0)
                else:
                    waiting_time = 0

                working_time = route.get_working_time(point)
                if waiting_time != 0 and point.startswith('asu'):
                    data.append((self.time, original_truck, route.route_structure[last_point], 'ожидание', current_time, waiting_time, current_time + waiting_time))
                    current_time = current_time + waiting_time
                if moving_time != 0:
                    data.append((self.time, original_truck, route.route_structure[point], 'перемещение', current_time, moving_time, current_time + moving_time))
                    current_time = current_time + moving_time
                    last_point = point
                if waiting_time != 0 and not point.startswith('asu'):
                    data.append((self.time, original_truck, route.route_structure[point], 'ожидание', current_time, waiting_time, current_time + waiting_time))
                    current_time = current_time + waiting_time
                if working_time != 0:
                    data.append((self.time, original_truck, route.route_structure[point], 'слив' if point.startswith('asu') else 'налив', current_time, working_time, current_time + working_time))
                    current_time = current_time + working_time
        full_timetable = pd.DataFrame(data=data, columns=columns)
        return full_timetable

    def get_timetable_in_pandas(self):
        columns = ['shift', 'truck', 'section_number', 'section_volume', 'is_empty', 'should_be_empty', 'asu', 'n', 'depot', 'trip_number', 'time', 'load_before', 'load_after']
        data = []
        for i, row in self.loads_result_pandas.iterrows():
            row_data = [row['shift'], row['truck'], row['section_number'], row['section_volume'], row['is_empty'], row['should_be_empty'], row['asu'], row['n']]
            truck = int(row['truck'])
            trip_number = int(row['trip_number'])
            asu = int(row['asu'])
            if truck not in self.truck_routes or self.truck_routes[truck].is_empty_route:
                continue
            truck_route = self.truck_routes[truck]
            if truck_route.is_two_trips or truck_route.is_cut_route:
                two_trips_version = truck_route.truck // 1000
                if two_trips_version == 2:
                    trip_number = 3 - trip_number
            truck_trip = truck_route.trips[trip_number - 1]
            asu_number_in_trip = truck_trip.route.index(asu) + 1 if asu != 0 else 0
            asu_point_str = 'asu%d%d' % (trip_number, asu_number_in_trip) if asu != 0 else 0
            time = truck_route.get_arrival_time(asu_point_str) if asu != 0 else 0
            load_before = 1 if truck_route.is_load_before and trip_number == 1 else 0
            load_after = 1 if truck in self.load_after else 0
            row_data.append(truck_trip.depot)
            row_data.append(trip_number)
            row_data.append(time)
            row_data.append(load_before)
            row_data.append(load_after)
            data.append(row_data)
        timetable = pd.DataFrame(data=data, columns=columns)
        return timetable

    def get_utility_in_pandas(self):
        columns = ['shift', 'truck', 'work_time', 'utility']
        data = []
        for truck, route in self.truck_routes.items():
            work_time = route.total_duration(depot3=route.route_structure['depot3'])
            data.append((self.time, truck, work_time, work_time / self.data.vehicles[route.truck % 1000].shift_size))

        utility = pd.DataFrame(data=data, columns=columns)
        return utility

    def fill_busy_status(self):
        for truck, route in self.truck_routes.items():
            cut_off_shift = self.data.vehicles_cut_off_shift.get((truck, self.time), 0)
            shift_end = self.data.vehicles[truck].shift_size - cut_off_shift
            work_end = route.total_duration(depot3=route.route_structure['depot3'])

            delta = shift_end - work_end

            # Превышение длины смены
            if 0 < -delta:
                if self.truck_routes[truck].is_empty_route:
                    last_point = self.truck_routes[truck].route_structure['uet1']
                elif self.truck_routes[truck].is_own_truck:
                    last_point = self.truck_routes[truck].route_structure['uet2']
                else:
                    last_point = self.truck_routes[truck].trips[-1].route[-1]

                shift = self.time
                while True:
                    cut_off_shift = self.data.vehicles_cut_off_shift.get((truck, shift), 0)
                    shift_end = self.data.vehicles[truck].shift_size - cut_off_shift
                    excess = work_end - shift_end
                    if excess > 0:
                        self.data.vehicles_busy.append((truck, shift))
                        work_end -= self.parameters.shift_size
                        shift += 1
                    else:
                        busy, location = self.data.vehicles_busy_hours.get((truck, shift), (None, None))
                        if not busy or busy < work_end:
                            self.data.vehicles_busy_hours[truck, shift] = (work_end, last_point)
                        break
                continue

            # Ограничение минуса для следующей смены
            route.delete_moving_to_uet = True
            work_end = route.total_duration(depot3=route.route_structure['depot3'])
            if self.parameters.shift_size - work_end > 3:
                work_end = self.parameters.shift_size - 3

            delta = shift_end - work_end

            # Если осталось не менее 5 часов,
            # машина не работает в следующую смену, либо у неё нет возможности загрузки под сменщика,
            # то заполнить текущую, иначе рассматривается следующая
            if delta >= 5 and ((truck, self.time + 1) in self.data.vehicles_busy or self.load_after.get(truck, [])):
                if self.truck_routes[truck].is_empty_route:
                    last_point = self.truck_routes[truck].route_structure['uet1']
                else:
                    last_point = self.truck_routes[truck].trips[-1].route[-1]

                hours = work_end - self.parameters.shift_size
                self.data.vehicles_busy_hours[truck, self.time + 1] = (hours, last_point)
                self.data.vehicles_cut_off_shift[truck, self.time + 1] = \
                    self.data.vehicles_cut_off_shift.get((truck, self.time), 0) + self.parameters.shift_size
                if (truck, self.time + 1) in self.data.vehicles_busy:
                    self.data.vehicles_busy.remove((truck, self.time + 1))
            else:
                route.delete_moving_to_uet = False

    def return_uet(self):
        for truck, route in self.truck_routes.items():
            if truck not in TimetableCreator.timetable_solution_list[-1].truck_routes:
                continue
            previous_route = TimetableCreator.timetable_solution_list[-1].truck_routes[truck]
            if route.is_empty_route and previous_route.delete_moving_to_uet:
                previous_route.delete_moving_to_uet = False

    """Add load before to routes"""
    def set_load_before_to_routes(self):
        for truck, truck_route in self.truck_routes.items():
            truck_number = truck % 1000
            if truck_number in self.load_before and truck_route.route_structure['depot1'] in self.load_before[truck_number]:
                truck_route.is_load_before = True

    """Add load after to routes"""
    def set_load_after_to_routes(self):
        for truck, truck_route in self.truck_routes.items():
            truck_number = truck % 1000
            if truck_number in self.load_after and \
                    not (truck_route.is_empty_route and
                         self.data.vehicles_busy_hours.get((truck_number, self.time), (0,))[0] < 2):
                truck_route.depots_for_load_after = self.load_after[truck_number]

    """Read detailed plan data to local structure"""
    def get_truck_routes_from_pandas(self):
        truck_routes = {}
        truck_routes_dict = {}
        trip_asu_n_dict = {}
        loads = self.loads_result_pandas
        truck_trip_asu_set = loads.iloc[::-1].filter(['truck', 'trip_number', 'asu']).drop_duplicates()

        for i, row in truck_trip_asu_set.iterrows():
            truck = row['truck']
            trip_number = row['trip_number']
            asu = row['asu']
            if asu != 0:
                truck_trip_asu_loads = loads[(loads['truck'] == truck) &
                                             (loads['trip_number'] == trip_number) &
                                             (loads['asu'] == asu)]
                is_critical = any(truck_trip_asu_loads['is_critical'].tolist())
                days_to_death = min(truck_trip_asu_loads['days_to_death'].tolist())
                if truck not in truck_routes_dict:
                    truck_routes_dict[truck] = {}
                if trip_number not in truck_routes_dict[truck]:
                    truck_routes_dict[truck][trip_number] = []
                sku_volumes = {int(sku): truck_trip_asu_loads[truck_trip_asu_loads['sku'] == int(sku)]['section_volume'].sum()
                               for i, sku in truck_trip_asu_loads.filter(['sku']).drop_duplicates().iterrows()}
                truck_routes_dict[truck][trip_number].append((asu, sku_volumes, len(truck_trip_asu_loads['section_volume']),
                                                              truck_trip_asu_loads['n'].drop_duplicates().tolist(),
                                                              is_critical, days_to_death),)
                if (truck, trip_number) not in trip_asu_n_dict:
                    trip_asu_n_dict[truck, trip_number] = []
                tanks = truck_trip_asu_loads['n'].drop_duplicates()
                trip_asu_n_dict[truck, trip_number].extend([(asu, tank) for tank in tanks])
        for truck in truck_routes_dict:
            trips = []
            for trip_number in truck_routes_dict[truck]:
                asu_volumes = {asu: volumes for asu, volumes, *_ in truck_routes_dict[truck][trip_number]}
                asu_sections = {asu: count for asu, volumes, count, *_ in truck_routes_dict[truck][trip_number]}
                asu_tanks = {asu: tanks for asu, volumes, count, tanks, *_ in truck_routes_dict[truck][trip_number]}
                asu_route = tuple(asu for asu, *_ in reversed(truck_routes_dict[truck][trip_number]))
                is_critical = any(is_critical for *_, is_critical, days_to_death in truck_routes_dict[truck][trip_number])
                days_to_death = min(days_to_death for *_, days_to_death in truck_routes_dict[truck][trip_number])
                depot = self.define_depot(truck, list(reversed(trip_asu_n_dict[truck, trip_number])), len(trips))
                trip = TruckTrip(truck, depot, asu_route, asu_volumes, asu_sections, asu_tanks, is_critical, days_to_death)
                trips.insert(trip_number - 1, trip)
            truck_routes[truck] = TruckRoute(self.time, truck, trips, self.parameters, self.data)
        return truck_routes

    """Add not used trucks for load after"""
    def add_useless_trucks(self):
        for truck in self.data.vehicles:
            if truck not in self.truck_routes and (truck, self.time) not in self.data.vehicles_busy:
                self.truck_routes[truck] = TruckRoute(self.time, truck, [], self.parameters, self.data)

    """Define depot: if depot was changed it will be chosen"""
    def define_depot(self, truck, asu_n_list: list, trip_number):
        trip = [asu for asu, n in asu_n_list]
        trip = [asu for idx, asu in enumerate(trip) if trip.index(asu) == idx]
        depots = []
        if len(trip) == 1:
            for version in (0, 1, 2, 3, 4, 5):
                version_trip = (trip[0] + version * 10000000,)
                if (truck, version_trip) in self.pd_parameters.route_depots:
                    depots.append(self.pd_parameters.route_depots[truck, version_trip])
            for asu1_version in (0, 1, 2, 3, 4, 5):
                for asu2_version in (0, 1, 2, 3, 4, 5):
                    version_trip = (trip[0] + asu1_version * 10000000, trip[0] + asu2_version * 10000000)
                    if (truck, version_trip) in self.pd_parameters.route_depots:
                        depots.append(self.pd_parameters.route_depots[truck, version_trip])
        elif len(trip) == 2:
            for asu1_version in (0, 1, 2, 3, 4, 5):
                for asu2_version in (0, 1, 2, 3, 4, 5):
                    version_trip = (trip[0] + asu1_version * 10000000, trip[1] + asu2_version * 10000000)
                    if (truck, version_trip) in self.pd_parameters.route_depots:
                        depots.append(self.pd_parameters.route_depots[truck, version_trip])
        if len(depots) == 1 or len(set(depots)) == 1:
            return depots[0]
        elif len(depots) > 1:
            print("Неоднозначно определяется депот %d, %s" % (truck, str(trip)))
            return depots[trip_number]
        else:
            print("Не определяется депот %d, %s" % (truck, str(trip)))
            return define_depot(asu_n_list, self.data, self.pd_parameters)

    """Delete second routes in case of last shift"""
    def cut_double_routes(self):
        for truck in list(self.truck_routes.keys()):
            route = self.truck_routes[truck]
            if not route.is_load_before and route.start_time >= 0:
                self.truck_routes[truck] = TruckRoute(self.time, truck, [], self.parameters, self.data)
                continue
            if route.is_two_trips:
                single_route = TruckRoute(route.time, truck, route.trips[:1], route.parameters, route.data)
                single_route.waiting_times = {(point, trip_number): value
                                              for (point, trip_number), value in route.waiting_times.items()
                                              if trip_number == 0}
                single_route.is_load_before = route.is_load_before
                single_route.is_cut_route = True
                single_route.truck = route.truck
                self.truck_routes[truck] = single_route

    """Update load after map according to calc"""
    def update_load_after(self, load_after_var_result):
        load_after_result = {}
        for (truck, depot), value in load_after_var_result.items():
            if round(value, 0) == 1:
                truck = truck % 1000
                if truck not in load_after_result:
                    load_after_result[truck] = []
                load_after_result[truck].append(depot)
        self.load_after = load_after_result
        # Убран перенос прошлых смен, т.е. загрузка под сменщика не на следующую смену, т.к. все машины,
        # даже не участвующие в рейсах смены, рассматриваются под сменщика и могут быть заполнены в предыдущую смену
        # trucks_from_last_shifts = {key: value for key, value in self.load_before.items() if key not in self.truck_routes}
        trucks_from_last_shifts = {}
        self.load_before.clear()
        self.load_before.update(trucks_from_last_shifts)
        self.load_before.update(load_after_result)

    """Update depot queue decrease"""
    def update_depot_queue_decrease(self):

        def divide_interval(work_start, work_finish):
            work_start = round(work_start, 6)
            work_finish = round(work_finish, 6)
            work_start_shift_correction = int(work_start // self.parameters.shift_size)
            work_finish_shift_correction = int(work_finish // self.parameters.shift_size)
            for shift_correction in range(work_start_shift_correction, work_finish_shift_correction + 1):
                interval = []
                if shift_correction == work_start_shift_correction:
                    interval.append(work_start % self.parameters.shift_size)
                else:
                    interval.append(0)
                if shift_correction == work_finish_shift_correction:
                    interval.append(work_finish % self.parameters.shift_size)
                else:
                    interval.append(self.parameters.shift_size)
                interval = tuple(interval)
                self.data.depot_work_decrease.setdefault((depot, self.time + shift_correction), []).append(interval)

        for truck, route in self.truck_routes.items():
            if not route.is_load_before:
                depot = route.route_structure['depot1']
                work_start = route.get_arrival_time('depot1')
                work_finish = work_start + route.get_working_time('depot1')
                divide_interval(work_start, work_finish)
            if route.is_two_trips:
                depot = route.route_structure['depot2']
                work_start = route.get_arrival_time('depot2')
                work_finish = work_start + route.get_working_time('depot2')
                divide_interval(work_start, work_finish)
            for depot in route.depots_for_load_after:
                if depot not in self.load_before.get(truck,  []):
                    continue
                work_start = route.get_arrival_time('depot3', depot)
                work_finish = work_start + route.get_working_time('depot3', depot)
                divide_interval(work_start, work_finish)

    """Update asu blocks"""
    def update_asu_blocks(self):
        for truck, route in self.truck_routes.items():
            for t, trip in enumerate(route.trips, start=1):
                for a, asu in enumerate(trip.route, start=1):
                    arrival = route.get_arrival_time('asu' + str(t) + str(a))
                    work = route.get_working_time('asu' + str(t) + str(a))
                    self.data.block_window_asu.setdefault((asu, self.time), []).append((arrival, arrival + work))
