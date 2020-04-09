from data_reader.input_data import StaticData, Parameters
from timetable_calculator.functions import *
from timetable_calculator.classes import TruckRoute
from docplex.mp.model import Model
from docplex.mp.solution import SolveSolution
from detailed_planning.trip_optimization import define_asu_windows

"""Create optimal shift timetable"""


class TimetableModel:
    def __init__(self, time: int, parameters: Parameters, data: StaticData, solve=True):
        self.parameters = parameters
        self.data = data
        self.time = time
        self.shift = 2 - self.time % 2
        self.model = Model('Timetable')

        self.double_route_var_dict = {}
        self.double_route_expr = {}
        self.depot_waiting_var_dict = {}
        self.asu_waiting_var_dict = {}
        self.int_depot_waiting_var_dict = {}
        self.load_after_var_dict = {}
        self.duration_excess_var_dict = {}
        self.asu_window_excess_var_dict = {}
        self.depot_load_window_excess_var_dict = {}
        self.asu_queue_var_dict = {}
        self.asu_queue_cross_var_dict = {}
        self.depot_queue_var_dict = {}
        self.depot_begin_queue_var_dict = {}
        self.depot_end_queue_var_dict = {}
        self.depot_decrease_begin_queue_var_dict = {}
        self.depot_decrease_end_queue_var_dict = {}
        self.depot_decrease_queue_var_dict = {}
        self.depot_decrease2_begin_queue_var_dict = {}
        self.depot_decrease2_end_queue_var_dict = {}
        self.depot_decrease2_queue_var_dict = {}
        self.depot_block_queue_var_dict = {}
        self.depot_block_begin_queue_var_dict = {}
        self.depot_block_end_queue_var_dict = {}
        self.route_asu_window_var_dict = {}
        self.common_duration_penalty_var = 0
        self.objective_functions = []

        self.solve = solve
        self.start_solution = SolveSolution(self.model)

    big_positive_value = 1000
    big_negative_value = -1000

    common_duration_penalty_weight = 0.1
    load_after_weight = -1
    window_end_weight = 1000
    asu_cross_weight = 10000
    duration_weight = 2
    double_route_duration_weight = duration_weight / 2
    long_route_duration_weight = 0
    duration_cut_off_factor = 100
    asu_waiting_weight = 1
    depot_waiting_weight = 1
    critical_waiting_coef = [100, 10000, 1000000]
    not_load_after_waiting_coef = 0

    """Optimize timetable model"""

    def optimize(self, p):

        # self.model.export_as_lp('Timetable_%d_%d.lp' % (self.time, p))

        self.model.log_output = True
        self.model.parameters.timelimit = 100 / p
        self.model.parameters.mip.tolerances.mipgap = 0.1

        if p > 2:
            self.model.log_output = False

        solution = self.model.solve_lexicographic(goals=self.objective_functions)

        # if solution:
        #     with open("solution_%d_%d.txt" % (self.time, p), 'w') as f:
        #        f.write('\n'.join(s.to_string() for s in solution))

        if not solution:
            self.model.parameters.timelimit = 200 / p
            self.model.parameters.mip.tolerances.mipgap = 0.2
            solution = self.model.solve()
            if not solution:
                self.model.parameters.timelimit = 100
                self.set_start_ugly_solution()
                self.model.solve()
                print("The timetable solver did not find an acceptable solution due to the time limit!")
                print("<FOR_USER>\nНЕ НАЙДЕНО решение модели Оптимизации рассписания.\n</FOR_USER>")
        # else:
        #     solution_details = solution.solve_details
        #     mip_relative_gap = solution_details.mip_relative_gap
        #     timelimit = 100
        #     while mip_relative_gap > 0.1 and timelimit < 600:
        #         self.model.parameters.timelimit = 50
        #         timelimit += 50
        #         solution = self.model.solve()
        #         solution_details = solution.solve_details
        #         mip_relative_gap = solution_details.mip_relative_gap

    """Start values of binary vars:
        - no load after
        - no reverse double route
        - asu and depot queues by truck number"""

    def set_start_binary_var_values(self):
        var_value_dict = {}
        for key, var in self.double_route_var_dict.items():
            var_value_dict[var] = 0
        for key, var in self.load_after_var_dict.items():
            var_value_dict[var] = 0
        for key, var in self.asu_queue_var_dict.items():
            depot, truck, trip_number, next_truck, next_trip_number = key
            if truck < next_truck:
                var_value_dict[var] = 0
            else:
                var_value_dict[var] = 1
        for key, var in self.depot_begin_queue_var_dict.items():
            depot, truck, trip_number, next_truck, next_trip_number = key
            if truck < next_truck:
                var_value_dict[var] = 1
            else:
                var_value_dict[var] = 0
        for key, var in self.depot_end_queue_var_dict.items():
            depot, truck, trip_number, next_truck, next_trip_number = key
            if truck < next_truck:
                var_value_dict[var] = 1
            else:
                var_value_dict[var] = 0
        for key, var in self.depot_queue_var_dict.items():
            var_value_dict[var] = 0
        return var_value_dict

    """Start values of waiting vars:
        - no load after
        - direct double route
        - depot queues by trip optimization solution
        - excess vars and asu queue are not considered"""

    def set_start_solution(self, depot_queue: dict = None, depot_waitings: dict = None, asu_waitings: dict = None):
        var_value_dict = {}
        # for key, var in self.load_after_var_dict.items():
        #     var_value_dict[var] = 0
        for truck in depot_queue:
            truck_version = truck // 1000
            if truck_version != 0:
                var_value_dict[self.double_route_var_dict[truck % 1000]] = truck_version - 1
        for key, var in self.depot_begin_queue_var_dict.items():
            depot, truck, trip_number, next_truck, next_trip_number = key
            if trip_number == 2 or next_trip_number == 2 or truck not in depot_queue or next_truck not in depot_queue:
                continue
            if depot_queue[next_truck][next_trip_number] <= depot_queue[truck][trip_number]:
                var_value_dict[var] = 1
            else:
                var_value_dict[var] = 0
        for key, var in self.depot_end_queue_var_dict.items():
            depot, truck, trip_number, next_truck, next_trip_number = key
            if trip_number == 2 or next_trip_number == 2 or truck not in depot_queue or next_truck not in depot_queue:
                continue
            if depot_queue[next_truck][next_trip_number] + self.data.depot_load_time[depot] <= \
                    depot_queue[truck][trip_number]:
                var_value_dict[var] = 1
            else:
                var_value_dict[var] = 0
        for key, var in self.depot_queue_var_dict.items():
            depot, truck, trip_number, next_truck, next_trip_number = key
            if trip_number == 2 or next_trip_number == 2 or truck not in depot_queue or next_truck not in depot_queue:
                continue
            if depot_queue[next_truck][next_trip_number] <= depot_queue[truck][trip_number] < \
                    depot_queue[next_truck][next_trip_number] + self.data.depot_load_time[depot]:
                var_value_dict[var] = 1
            else:
                var_value_dict[var] = 0
        if depot_waitings:
            for key, var in self.depot_waiting_var_dict.items():
                var_value_dict[var] = depot_waitings.get(key, 0)
            for key, var in self.asu_waiting_var_dict.items():
                var_value_dict[var] = asu_waitings.get(key, 0)

        if var_value_dict:
            solution = SolveSolution(self.model, var_value_map=var_value_dict)
            self.start_solution = solution
            self.model.add_mip_start(solution)

        # for var, val in var_value_dict.items():
        #     self.model.add_constraint(var == val)

    """Start values of waiting vars:
        - no load after
        - direct double route
        - asu and depot queues by truck number
        - excess vars are not considered"""

    def set_start_ugly_solution(self):
        var_value_dict = self.set_start_binary_var_values()
        solution = SolveSolution(self.model, var_value_map=var_value_dict)
        self.model.add_mip_start(solution)

    """Update model to resolve for load_after"""

    def update(self, truck_routes: dict):
        """Double route vars"""
        for key, var in self.double_route_var_dict.items():
            self.model.add_constraint(var == var.solution_value)

        """Load after vars"""
        for key, var in self.load_after_var_dict.items():
            if var.solution_value:
                self.model.add_constraint(var == var.solution_value)

        """Asu queue"""
        for key, var in self.asu_queue_var_dict.items():
            self.model.add_constraint(var == var.solution_value)

        """Route duration excess"""
        for key, var in self.duration_excess_var_dict.items():
            self.model.add_constraint(var <= var.solution_value)

        """Route waitings"""
        for key, var in self.asu_waiting_var_dict.items():
            if (not truck_routes[key[0]].is_empty_route and truck_routes[key[0]].trips[key[2]].is_critical) or \
                    truck_routes[key[0]].depots_for_load_after:
                truck, asu, trip, n = key
                depot = truck_routes[truck].trips[trip].depot
                depot_var = self.depot_waiting_var_dict.get((truck, depot, trip), 0) if key[3] == 0 else 0
                self.model.add_constraint(var + depot_var <= var.solution_value +
                                          (depot_var.solution_value if depot_var else 0))

        """Objective function:
        - waitings on depot and asu
        - route duration excess
        - asu window excess"""
        load_after = self.model.sum((self.load_after_weight * self.model.sum(self.load_after_var_dict.values()),
                                     - self.load_after_weight * len(self.load_after_var_dict)))

        self.objective_functions = [self.objective_functions[0], load_after]

    """Update model to resolve for decrease waitings"""

    def strong_update(self, truck_routes: dict):
        """Double route vars"""
        for key, var in self.double_route_var_dict.items():
            self.model.add_constraint(var == var.solution_value)

        """Load after vars"""
        for key, var in self.load_after_var_dict.items():
            if var.solution_value:
                self.model.add_constraint(var == var.solution_value)

        """Asu queue"""
        for key, var in self.asu_queue_var_dict.items():
            self.model.add_constraint(var == var.solution_value)

        """Route duration excess"""
        for key, var in self.duration_excess_var_dict.items():
            self.model.add_constraint(var <= var.solution_value)

        """Route waitings"""
        for key, var in self.asu_waiting_var_dict.items():
            if (not truck_routes[key[0]].is_empty_route and truck_routes[key[0]].trips[key[2]].is_critical) or \
                    truck_routes[key[0]].depots_for_load_after:
                truck, asu, trip, n = key
                depot = truck_routes[truck].trips[trip].depot
                depot_var = self.depot_waiting_var_dict.get((truck, depot, trip), 0) if key[3] == 0 else 0
                self.model.add_constraint(var + depot_var <= var.solution_value +
                                          (depot_var.solution_value if depot_var else 0))

        """Objective function:
        - waitings on depot and asu
        - route duration excess
        - asu window excess"""
        load_after = self.model.sum((self.load_after_weight * self.model.sum(self.load_after_var_dict.values()),
                                     - self.load_after_weight * len(self.load_after_var_dict)))

        waitings = self.depot_waiting_weight * self.model.sum(self.depot_waiting_var_dict.values()) + \
                   self.asu_waiting_weight * self.model.sum(self.asu_waiting_var_dict.values())

        self.objective_functions = [self.objective_functions[0], load_after + waitings]

    """Create timetable model"""

    def create_model(self, truck_routes: dict, double_routes: list):

        self.common_duration_penalty_var = self.model.continuous_var(lb=0, name='common_duration_excess')

        """Double route vars"""
        for truck in double_routes:
            self.double_route_var_dict[truck] = self.model.binary_var(name='double_route_var_%d' % truck)
            # if LinExpr == 1, then double route is chosen
            self.double_route_expr[truck + 1000] = 1 - self.double_route_var_dict[truck]
            self.double_route_expr[truck + 2000] = self.double_route_var_dict[truck]

        for truck, route in truck_routes.items():
            """Waiting vars on asus and depots"""
            self.add_waiting_vars(route)
            """Load after vars"""
            self.add_load_after_vars(route)
            """Load after constraints"""
            self.add_route_duration_with_load_after_constr(route)
            """Duration excess var"""
            self.add_route_duration_excess_var(route)
            """Common duration excess constraint"""
            self.add_common_duration_excess_constr(route)
            """Asu window constraint"""
            self.add_asu_windows_constr(route)
            """Double route constraint"""
            if route.is_two_trips:
                self.add_double_route_constr(route)
            """Depot load window constraints"""
            self.add_depot_load_windows_constr(route)

        """Asu queue"""
        self.add_asu_queue_constr(truck_routes)

        """Depot queue"""
        self.add_depot_queue_constr(truck_routes)

        """Depot block"""
        self.add_depot_block_constr(truck_routes)

        """Objective function:
        - duration excess penalties
        - common duration penalty
        - asu window end penalty
        - load after priority"""
        strong_constrains = self.model.sum((self.duration_weight *
                                            self.model.sum(var for key, var in self.duration_excess_var_dict.items()
                                                           if not (truck_routes[key].is_two_trips or truck_routes[key].is_long_route)),
                                            self.double_route_duration_weight *
                                            self.model.sum(var for key, var in self.duration_excess_var_dict.items()
                                                           if truck_routes[key].is_two_trips),
                                            self.long_route_duration_weight *
                                            self.model.sum(var for key, var in self.duration_excess_var_dict.items()
                                                           if truck_routes[key].is_long_route),
                                            self.common_duration_penalty_weight * self.common_duration_penalty_var,
                                            self.window_end_weight * self.model.sum(self.asu_window_excess_var_dict.values()),
                                            self.window_end_weight * self.model.sum(self.depot_load_window_excess_var_dict.values()),
                                            self.asu_cross_weight * self.model.sum(self.asu_queue_cross_var_dict.values())))

        waitings = self.model.sum((self.model.sum(var * self.get_waiting_penalty(truck_routes[key[0]], key[2])
                                                  for key, var in self.asu_waiting_var_dict.items()),
                                   self.model.sum(var * self.get_waiting_penalty(truck_routes[key[0]], key[2])
                                                  for key, var in self.int_depot_waiting_var_dict.items())))

        self.objective_functions = [strong_constrains, waitings]

    def get_waiting_penalty(self, route, trip):
        if not route.is_empty_route and trip != 2 and route.trips[trip].is_critical:
            if route.trips[trip].days_to_death > 0.3:
                return self.asu_waiting_weight * self.critical_waiting_coef[0]
            elif route.trips[trip].days_to_death > 0.1:
                return self.asu_waiting_weight * self.critical_waiting_coef[1]
            else:
                return self.asu_waiting_weight * self.critical_waiting_coef[2]
        elif route.depots_for_load_after:
            return self.asu_waiting_weight
        else:
            return self.asu_waiting_weight * self.not_load_after_waiting_coef

    """Waiting vars on asus and depots"""

    def add_waiting_vars(self, route: TruckRoute):
        for trip_number, trip in enumerate(route.trips):
            if not (route.is_load_before and trip_number == 0):
                depot_var = self.model.continuous_var(lb=0, name='depot_waiting_var_%d_%d_%d' % (route.truck, trip.depot, trip_number))
                int_depot_var = self.model.integer_var(lb=0, name='int_depot_waiting_var_%d_%d_%d' % (route.truck, trip.depot, trip_number))
                self.depot_waiting_var_dict[route.truck, trip.depot, trip_number] = depot_var
                self.int_depot_waiting_var_dict[route.truck, trip.depot, trip_number] = int_depot_var
                self.model.add_constraint_(int_depot_var * self.data.depot_load_time[trip.depot] >= depot_var)
            for asu_number, asu in enumerate(trip.route):
                asu_var = self.model.continuous_var(lb=0, name='asu_waiting_var_%d_%d_%d_%d' % (route.truck, asu, trip_number, asu_number))
                self.asu_waiting_var_dict[route.truck, asu, trip_number, asu_number] = asu_var
        for depot in route.depots_for_load_after:
            depot_var = self.model.continuous_var(lb=0, name='depot_waiting_var_%d_%d_%d' % (route.truck, depot, 2))
            int_depot_var = self.model.integer_var(lb=0, name='int_depot_waiting_var_%d_%d_%d' % (route.truck, depot, 2))
            self.depot_waiting_var_dict[route.truck, depot, 2] = depot_var
            self.int_depot_waiting_var_dict[route.truck, depot, 2] = int_depot_var
            self.model.add_constraint_(int_depot_var * self.data.depot_load_time[depot] >= depot_var)

    """Load after vars"""

    def add_load_after_vars(self, route: TruckRoute):
        for depot in route.depots_for_load_after:
            load_after_var = self.model.binary_var(name='load_after_var_%d_%d' % (route.truck, depot))
            self.load_after_var_dict[route.truck, depot] = load_after_var
            # if load after is not, then depot waiting can't be
            self.model.add_constraint_(self.big_positive_value * load_after_var >=
                                       self.depot_waiting_var_dict[route.truck, depot, 2],
                                       ctname='load_after_constr_%d_%d' % (route.truck, depot))
            # if double_route is not chosen, then load after can't be
            if route.is_two_trips:
                self.model.add_constraint_(load_after_var <= self.double_route_expr.get(route.truck, 1),
                                           ctname='load_after_double_route_constr_%d_%d' % (route.truck, depot))

    """Load after constraints:
        route duration with load after should be not greater than shift size"""

    def add_route_duration_with_load_after_constr(self, route: TruckRoute):
        for depot in route.depots_for_load_after:
            # if double_route is not chosen, then load after can't be
            cut_off_shift = self.data.vehicles_cut_off_shift.get((route.truck % 1000, self.time), 0)
            self.model.add_constraint_(
                self.get_arrival_time_expr(route, 'uet2', depot3=depot) <=
                self.data.vehicles[route.truck % 1000].shift_size - cut_off_shift +
                self.big_positive_value * (1 - self.double_route_expr.get(route.truck, 1)) +
                self.big_positive_value * (1 - self.load_after_var_dict[route.truck, depot]),
                ctname='route_duration_load_after_constr_%d_%d' % (route.truck, depot))

    """Arrival time expression"""

    def get_arrival_time_expr(self, route: TruckRoute, point: str, depot3=0):
        duration = 0
        if point in route.route_structure:
            double_route_correction = self.double_route_expr.get(route.truck, 1)
            constant_duration = route.get_arrival_time(point, depot3)
            # if double_route is not chosen, then constant duration can't be
            duration += constant_duration * double_route_correction
            for cur_point in route.route_structure:
                if 'depot' in cur_point:
                    depot = route.route_structure[cur_point]
                    trip_number = route.get_trip_number_from_point_name(cur_point)
                    if trip_number == 2:
                        depot = depot3
                    duration += self.depot_waiting_var_dict.get((route.truck, depot, trip_number), 0)
                if 'asu' in cur_point:
                    asu = route.route_structure[cur_point]
                    trip_number = route.get_trip_number_from_point_name(cur_point)
                    asu_number = int(cur_point[-1]) - 1
                    duration += self.asu_waiting_var_dict.get((route.truck, asu, trip_number, asu_number), 0)
                if cur_point == point:
                    break
        return duration

    """Duration excess var"""

    def add_route_duration_excess_var(self, route: TruckRoute):
        if not route.is_empty_route:
            duration_excess = self.model.continuous_var(lb=0, name='duration_excess_var_%d' % route.truck)
            self.duration_excess_var_dict[route.truck] = duration_excess
            cut_off_shift = self.data.vehicles_cut_off_shift.get((route.truck % 1000, self.time), 0)
            # if double_route is not chosen, then duration excess can't be
            self.model.add_constraint_(self.get_arrival_time_expr(route, 'uet2') <=
                                       self.data.vehicles[route.truck % 1000].shift_size - cut_off_shift +
                                       duration_excess / (self.duration_cut_off_factor if cut_off_shift else 1) +
                                       self.big_positive_value * (1 - self.double_route_expr.get(route.truck, 1)),
                                       ctname='duration_excess_constr_%d' % route.truck)

    """Common duration excess constraint"""

    def add_common_duration_excess_constr(self, route: TruckRoute):
        if not route.is_long_route and not route.is_empty_route:
            # if double_route is not chosen, then duration excess can't be
            cut_off_shift = self.data.vehicles_cut_off_shift.get((route.truck % 1000, self.time), 0)
            self.model.add_constraint_(self.get_arrival_time_expr(route, 'uet2') -
                                       (self.data.vehicles[route.truck % 1000].shift_size - cut_off_shift) <=
                                       self.common_duration_penalty_var +
                                       self.big_positive_value * (1 - self.double_route_expr.get(route.truck, 1)),
                                       ctname='common_duration_excess_constr_%d' % route.truck)

    """Asu window constraints"""

    def add_asu_windows_constr(self, route: TruckRoute):
        for trip_number, trip in enumerate(route.trips):
            for asu_number, asu in enumerate(trip.route):
                unload = route.get_working_time('asu%d%d' % (trip_number + 1, asu_number + 1))
                arrival = route.get_arrival_time('asu%d%d' % (trip_number + 1, asu_number + 1))
                max_duration = self.parameters.shift_size * 2 if route.is_long_route \
                    else self.data.vehicles[route.truck % 1000].shift_size
                asu_windows = define_asu_windows(arrival, asu, self.time, unload, max_duration, self.data)

                asu_window_vars = {}
                for window in asu_windows:
                    asu_window_vars[route.truck, asu, trip_number, asu_number, window] = \
                        self.model.binary_var(name='long_route_%d_%d_%d_%d_%s' %
                                                   (route.truck, asu, trip_number, asu_number, str(window).replace('-', '_')))
                self.route_asu_window_var_dict.update(asu_window_vars)
                self.model.add_constraint_(self.model.sum(asu_window_vars.values()) + (1 - self.double_route_expr.get(route.truck, 1)) == 1,
                                           ctname='asu_windows_constr_%d_%d_%d' % (route.truck, asu, trip_number))

                arrival_time = self.get_arrival_time_expr(route, 'asu%d%d' % (trip_number + 1, asu_number + 1))
                self.model.add_constraint_(arrival_time + self.big_positive_value * (1 - self.double_route_expr.get(route.truck, 1)) >=
                                           sum(window[0] * var for window, (key, var) in zip(asu_windows, asu_window_vars.items())),
                                           ctname='asu_window_begin_constr_%d_%d_%d' % (route.truck, asu, trip_number))
                window_end_excess = self.model.continuous_var(lb=0,
                                                              name='asu_window_end_excess_var_%d_%d_%d' % (route.truck, asu, trip_number))
                self.model.add_constraint_(
                    arrival_time <= sum(window[1] * var for window, (key, var) in zip(asu_windows, asu_window_vars.items())) +
                    self.big_positive_value * (1 - self.double_route_expr.get(route.truck, 1))
                    + window_end_excess, ctname='asu_window_end_excess_constr_%d_%d_%d' % (route.truck, asu, trip_number))
                self.asu_window_excess_var_dict[route.truck, asu, trip_number] = window_end_excess

    """Depot load window constraints"""

    def add_depot_load_windows_constr(self, route: TruckRoute):
        for trip_number, trip in enumerate(route.trips):
            if trip_number == 0 and route.is_load_before:
                continue
            depot_window = self.data.depot_work_time[trip.depot][2 - self.time % 2]
            arrival_time = self.get_arrival_time_expr(route, 'depot%d' % (trip_number + 1), trip.depot)
            window_end_excess = self.model.continuous_var(lb=0, name='depot_load_window_excess_var_%d_%d_%d' %
                                                                     (route.truck, trip.depot, trip_number))
            self.model.add_constraint_(arrival_time + 0.01 <=
                                       min(self.parameters.shift_size, depot_window[1]) + window_end_excess +
                                       self.big_positive_value * (1 - self.double_route_expr.get(route.truck, 1)),
                                       ctname='depot_load_window_end_constr_%d_%d_%d' % (route.truck, trip.depot, trip_number))
            self.depot_load_window_excess_var_dict[route.truck, trip.depot, trip_number] = window_end_excess
        for depot in route.depots_for_load_after:
            depot_window = self.data.depot_work_time[depot][2 - self.time % 2]
            arrival_time = self.get_arrival_time_expr(route, 'depot3', depot3=depot)
            window_end_excess = self.model.continuous_var(lb=0, name='depot_load_window_excess_var_%d_%d_%d' %
                                                                     (route.truck, depot, 2))
            self.model.add_constraint_(arrival_time + 0.01 <=
                                       min(self.parameters.shift_size, depot_window[1]) + window_end_excess +
                                       self.big_positive_value * (1 - self.double_route_expr.get(route.truck, 1)) +
                                       self.big_positive_value * (1 - self.load_after_var_dict[route.truck, depot]),
                                       ctname='depot_load_window_constr_%d_%d_%d' % (route.truck, depot, 2))
            self.depot_load_window_excess_var_dict[route.truck, depot, 2] = window_end_excess

    """Double route constraint"""

    def add_double_route_constr(self, route: TruckRoute):
        for asu in self.asu_waiting_var_dict:
            if extract_truck_from_asu_var_key(asu) == route.truck:
                self.model.add_constraint_((self.asu_waiting_var_dict[asu] <= self.double_route_expr.get(route.truck, 1) *
                                            self.big_positive_value), ctname='double_route_asu_constr_' + '_'.join(map(str, asu)))

        for depot in self.depot_waiting_var_dict:
            if extract_truck_from_nb_var_key(depot) == route.truck:
                self.model.add_constraint_((self.depot_waiting_var_dict[depot] <= self.double_route_expr.get(route.truck, 1) *
                                            self.big_positive_value), ctname='double_route_nb_constr_' + '_'.join(map(str, depot)))

    """Asu queue"""

    def add_asu_queue_constr(self, truck_routes: dict):
        asu_set = set(asu for truck, asu, trip_number, asu_number in self.asu_waiting_var_dict)
        for asu in asu_set:
            var_set = set(key for key in self.asu_waiting_var_dict if extract_asu_from_asu_var_key(key) == asu)
            while var_set:
                truck, asu, trip_number, asu_number = var_set.pop()
                double_route_correction = self.big_positive_value * (1 - self.double_route_expr.get(truck, 1))
                for var in var_set:
                    next_truck, asu, next_trip_number, next_asu_number = var
                    if truck % 1000 == next_truck % 1000:
                        continue
                    # asu_queue: either truck or next truck is on asu, not at the same time
                    asu_queue = self.model.binary_var(
                        name='asu_queue_%d_%d_%d_%d_%d' % (asu, truck, trip_number, next_truck, next_trip_number))
                    self.asu_queue_var_dict[asu, truck, trip_number, next_truck, next_trip_number] = asu_queue
                    asu_cross = self.model.continuous_var(
                        name='asu_cross_%d_%d_%d_%d_%d' % (asu, truck, trip_number, next_truck, next_trip_number))
                    self.asu_queue_cross_var_dict[asu, truck, trip_number, next_truck, next_trip_number] = asu_cross

                    truck_arrival = self.get_arrival_time_expr(truck_routes[truck], 'asu%d%d' % (trip_number + 1, asu_number + 1))
                    next_truck_arrival = self.get_arrival_time_expr(truck_routes[next_truck],
                                                                    'asu%d%d' % (next_trip_number + 1, next_asu_number + 1))
                    truck_work = truck_routes[truck].get_working_time('asu%d%d' % (trip_number + 1, asu_number + 1))
                    next_truck_work = truck_routes[next_truck].get_working_time('asu%d%d' % (next_trip_number + 1, next_asu_number + 1))

                    self.model.add_constraint_((next_truck_arrival + asu_cross) - truck_arrival + double_route_correction >=
                                               truck_work * asu_queue + (1 - asu_queue) * self.big_negative_value,
                                               ctname='asu_queue_constr_le_%d_%d_%d_%d_%d' %
                                                      (asu, truck, trip_number, next_truck, next_trip_number))
                    self.model.add_constraint_((truck_arrival + asu_cross) - next_truck_arrival + double_route_correction >=
                                               next_truck_work * (1 - asu_queue) + asu_queue * self.big_negative_value,
                                               ctname='asu_queue_constr_ge_%d_%d_%d_%d_%d' %
                                                      (asu, truck, trip_number, next_truck, next_trip_number))

    def point_in_interval_var(self, point, interval, correction, begin_dict, end_dict, compare_dict, name, indexes):
        indexes_str = '(' + ',_'.join(str(tuple(('_' if y < 0 else '') + str(abs(y)) for y in x))
                                      if isinstance(x, tuple) else str(x) for x in indexes) + ')'

        # begin_compare: point after interval starts
        begin_compare = self.model.binary_var(name=name + '_begin_compare_' + indexes_str)
        begin_dict[indexes] = begin_compare

        self.model.add_constraint_(point - interval[0] + self.big_positive_value * correction >=
                                   (1 - begin_compare) * self.big_negative_value,
                                   ctname=name + '_begin_compare_constr_le_' + indexes_str)
        self.model.add_constraint_(interval[0] - point + self.big_positive_value * correction >=
                                   begin_compare * self.big_negative_value,
                                   ctname=name + '_begin_compare_constr_ge_' + indexes_str)

        # end_compare: point after interval ends
        end_compare = self.model.binary_var(name=name + '_end_compare_' + indexes_str)
        end_dict[indexes] = end_compare

        self.model.add_constraint_(point - interval[1] + self.big_positive_value * correction >=
                                   (1 - end_compare) * self.big_negative_value,
                                   ctname=name + '_end_compare_constr_le_' + indexes_str)

        self.model.add_constraint_(interval[1] - point + self.big_positive_value * correction >=
                                   end_compare * self.big_negative_value,
                                   ctname=name + '_end_compare_constr_ge_' + indexes_str)

        # cross_compare: point when interval
        cross_compare = self.model.binary_var(name=name + '_compare_' + indexes_str)
        compare_dict[indexes] = cross_compare

        self.model.add_constraint_(cross_compare == begin_compare - end_compare,
                                   ctname=name + '_compare_constr_' + indexes_str)

        return cross_compare

    """Depot queue"""

    def add_depot_queue_constr(self, truck_routes: dict):
        depot_set = set(depot for truck, depot, trip_number in self.depot_waiting_var_dict)
        for depot in depot_set:
            var_set = set(key for key in self.depot_waiting_var_dict if extract_depot_from_nb_var_key(key) == depot)
            for var in var_set:
                truck, depot, trip_number = var
                two_trips_correction = (1 - self.double_route_expr.get(truck, 1))
                depot3_correction = self.load_after_var_dict[truck, depot] if trip_number == 2 else 1
                depot_queue = []
                # truck with truck
                for next_var in var_set:
                    next_truck, depot, next_trip_number = next_var
                    if truck % 1000 == next_truck % 1000:
                        continue
                    next_two_trips_correction = (1 - self.double_route_expr.get(next_truck, 1))
                    next_depot3_correction = self.load_after_var_dict[next_truck, depot] if next_trip_number == 2 else 1

                    correction = two_trips_correction + next_two_trips_correction + 2 - (depot3_correction + next_depot3_correction)

                    truck_arrival = self.get_arrival_time_expr(truck_routes[truck], 'depot%d' % (trip_number + 1), depot)
                    next_truck_arrival = self.get_arrival_time_expr(truck_routes[next_truck], 'depot%d' % (next_trip_number + 1), depot)
                    next_truck_interval = (next_truck_arrival - 0.01, next_truck_arrival + self.data.depot_load_time[depot])

                    compare_var = self.point_in_interval_var(truck_arrival, next_truck_interval, correction,
                                                             self.depot_begin_queue_var_dict,
                                                             self.depot_end_queue_var_dict,
                                                             self.depot_queue_var_dict,
                                                             'depot_truck_truck',
                                                             (depot, truck, trip_number, next_truck, next_trip_number))

                    self.model.add_constraint_(compare_var <= 1 - two_trips_correction,
                                               ctname='two_trips_depot_compare_constr_%d_%d_%d_%d_%d' %
                                                      (depot, truck, trip_number, next_truck, next_trip_number))
                    self.model.add_constraint_(compare_var <= 1 - next_two_trips_correction,
                                               ctname='next_two_trips_depot_compare_constr_%d_%d_%d_%d_%d' %
                                                      (depot, truck, trip_number, next_truck, next_trip_number))
                    self.model.add_constraint_(compare_var <= depot3_correction,
                                               ctname='load_after_depot_compare_constr_%d_%d_%d_%d_%d' %
                                                      (depot, truck, trip_number, next_truck, next_trip_number))
                    self.model.add_constraint_(compare_var <= next_depot3_correction,
                                               ctname='next_load_after_depot_compare_constr_%d_%d_%d_%d_%d' %
                                                      (depot, truck, trip_number, next_truck, next_trip_number))
                    depot_queue.append(compare_var)

                # truck with decrease
                for idx, decrease in enumerate(self.data.get_depot_decrease_for_extended_shift(depot, self.time, 12,
                                                                                               self.data.depot_load_time[depot] - 0.01)):

                    correction = two_trips_correction + 1 - depot3_correction

                    truck_arrival = self.get_arrival_time_expr(truck_routes[truck], 'depot%d' % (trip_number + 1), depot)
                    decrease_interval = (round(decrease[0], 2) - 0.01, round(decrease[1], 2))

                    compare_var = self.point_in_interval_var(truck_arrival, decrease_interval, correction,
                                                             self.depot_decrease_begin_queue_var_dict,
                                                             self.depot_decrease_end_queue_var_dict,
                                                             self.depot_decrease_queue_var_dict,
                                                             'depot_truck_decrease',
                                                             (depot, truck, trip_number, idx, decrease))

                    decrease_str = str(tuple(('_' if y < 0 else '') + str(abs(y)) for y in decrease))
                    self.model.add_constraint_(compare_var <= 1 - two_trips_correction,
                                               ctname='two_trips_depot_decrease_compare_constr_%d_%d_%d_%d_%s' %
                                                      (depot, truck, trip_number, idx, decrease_str))
                    self.model.add_constraint_(compare_var <= depot3_correction,
                                               ctname='load_after_depot_decrease_compare_constr_%d_%d_%d_%d_%s' %
                                                      (depot, truck, trip_number, idx, decrease_str))
                    depot_queue.append(compare_var)

                # truck count on depot at the same time is not greater than depot capacity
                self.model.add_constraint_(sum(depot_queue) <= self.data.depot_capacity[depot] - 1,
                                           ctname='depot_queue_%d_%d_%d' % (depot, truck, trip_number))

            for idx, decrease in enumerate(self.data.get_depot_decrease_for_extended_shift(depot, self.time, 12,
                                                                                           self.data.depot_load_time[depot] - 0.01)):
                decrease = tuple(round(t, 2) for t in decrease)
                depot_queue = []
                # decrease with truck
                for var in var_set:
                    truck, depot, trip_number = var
                    two_trips_correction = (1 - self.double_route_expr.get(truck, 1))
                    depot3_correction = self.load_after_var_dict[truck, depot] if trip_number == 2 else 1

                    correction = two_trips_correction + 1 - depot3_correction

                    truck_arrival = self.get_arrival_time_expr(truck_routes[truck], 'depot%d' % (trip_number + 1), depot)
                    truck_interval = (truck_arrival - 0.01, truck_arrival + self.data.depot_load_time[depot])

                    compare_var = self.point_in_interval_var(decrease[0], truck_interval, correction,
                                                             self.depot_decrease2_begin_queue_var_dict,
                                                             self.depot_decrease2_end_queue_var_dict,
                                                             self.depot_decrease2_queue_var_dict,
                                                             'depot_decrease_truck',
                                                             (depot, idx, decrease, truck, trip_number))

                    decrease_str = str(tuple(('_' if y < 0 else '') + str(abs(y)) for y in decrease))
                    self.model.add_constraint_(compare_var <= 1 - two_trips_correction,
                                               ctname='two_trips_depot_decrease2_compare_constr_%d_%d_%s_%d_%d' %
                                                      (depot, idx, decrease_str, truck, trip_number))
                    self.model.add_constraint_(compare_var <= depot3_correction,
                                               ctname='load_after_depot_decrease2_compare_constr_%d_%d_%s_%d_%d' %
                                                      (depot, idx, decrease_str, truck, trip_number))
                    depot_queue.append(compare_var)

                # decrease with decrease
                for jdx, next_decrease \
                        in enumerate(self.data.get_depot_decrease_for_extended_shift(depot, self.time, 12,
                                                                                     self.data.depot_load_time[depot] - 0.01)):
                    if idx == jdx:
                        continue
                    next_decrease = tuple(round(t, 2) for t in next_decrease)

                    # cross_compare: decrease starts when next_decrease
                    if next_decrease[0] <= decrease[0] < next_decrease[1]:
                        depot_queue.append(1)

                # truck count on depot at the same time is not greater than depot capacity
                decrease_str = str(tuple(('_' if y < 0 else '') + str(abs(y)) for y in decrease))
                self.model.add_constraint_(sum(depot_queue) <= self.data.depot_capacity[depot] - 1,
                                           ctname='depot_decrease_queue_%d_%d_%s' % (depot, idx, decrease_str))

    """Depot block"""

    def add_depot_block_constr(self, truck_routes: dict):
        depot_set = set(depot for truck, depot, trip_number in self.depot_waiting_var_dict)
        for depot in depot_set:
            var_set = set(key for key in self.depot_waiting_var_dict if extract_depot_from_nb_var_key(key) == depot)
            for block_index, block \
                    in enumerate(self.data.get_depot_blocks_for_extended_shift(depot, self.time, 12,
                                                                               self.data.depot_load_time[depot] - 0.01)):
                depot_queue = []
                for var in var_set:
                    truck, depot, trip_number = var
                    two_trips_correction = (1 - self.double_route_expr.get(truck, 1))
                    depot3_correction = self.load_after_var_dict[truck, depot] if trip_number == 2 else 1

                    correction = two_trips_correction + 1 - depot3_correction

                    truck_arrival = self.get_arrival_time_expr(truck_routes[truck], 'depot%d' % (trip_number + 1), depot)
                    block_interval = (block[0] - self.data.depot_load_time[depot] - 0.01, block[1])

                    compare_var = self.point_in_interval_var(truck_arrival, block_interval, correction,
                                                             self.depot_block_begin_queue_var_dict,
                                                             self.depot_block_end_queue_var_dict,
                                                             self.depot_block_queue_var_dict,
                                                             'depot_block',
                                                             (depot, block_index, truck, trip_number))

                    self.model.add_constraint_(compare_var <= 1 - two_trips_correction,
                                               ctname='two_trips_depot_block_compare_constr_%d_%d_%d_%d' %
                                                      (depot, block_index, truck, trip_number))
                    self.model.add_constraint_(compare_var <= depot3_correction,
                                               ctname='load_after_depot_block_compare_constr_%d_%d_%d_%d' %
                                                      (depot, block_index, truck, trip_number))
                    depot_queue.append(compare_var)

                # truck count on depot at block time equals 0
                self.model.add_constraint_(sum(depot_queue) == 0, ctname='depot_block_queue_%d_%d' % (depot, block_index))

    """Get result"""

    def get_double_route_var_result(self):
        if self.solve and self.model.get_solve_status():
            return {key: var.solution_value for key, var in self.double_route_var_dict.items()}
        if not self.solve:
            return {key: self.start_solution[var] for key, var in self.double_route_var_dict.items()}

    def get_load_after_var_result(self):
        if self.solve and self.model.get_solve_status():
            return {key: var.solution_value for key, var in self.load_after_var_dict.items()
                    if key[0] not in self.double_route_expr or round(self.double_route_expr[key[0]].solution_value, 0)}
        if not self.solve:
            return {}

    def get_asu_waiting_var_result(self):
        if self.solve and self.model.get_solve_status():
            return {key: var.solution_value for key, var in self.asu_waiting_var_dict.items()
                    if key[0] not in self.double_route_expr or round(self.double_route_expr[key[0]].solution_value, 0)}
        if not self.solve:
            return {key: self.start_solution[var] for key, var in self.asu_waiting_var_dict.items()}

    def get_depot_waiting_var_result(self):
        if self.solve and self.model.get_solve_status():
            return {key: var.solution_value for key, var in self.depot_waiting_var_dict.items()
                    if key[0] not in self.double_route_expr or round(self.double_route_expr[key[0]].solution_value, 0)}
        if not self.solve:
            return {key: self.start_solution[var] for key, var in self.depot_waiting_var_dict.items()}

    def check_result(self):
        f = True
        for key, var in self.duration_excess_var_dict.items():
            if round(var.solution_value, 2):
                if f:
                    print('Нарушение длины смены:')
                    f = False
                truck = key % 1000
                cut_off_shift = self.data.vehicles_cut_off_shift.get((truck, self.time), 0)
                value = round(var.solution_value / (self.duration_cut_off_factor if cut_off_shift else 1), 3)
                print('\tМашина %d: %f' % (truck, value))

        f = True
        for key, var in self.asu_window_excess_var_dict.items():
            if round(var.solution_value, 2):
                if f:
                    print('Нарушение окна азс:')
                    f = False
                truck, asu, trip_number = key
                truck = truck % 1000
                print('\tМашина %d, азс %d: %f' % (truck, asu, round(var.solution_value, 3)))

        f = True
        for key, var in self.depot_load_window_excess_var_dict.items():
            if round(var.solution_value, 2):
                if f:
                    print('Нарушение окна нб:')
                    f = False
                truck, depot, trip_number = key
                truck = truck % 1000
                print('\tМашина %d, нб %d: %f' % (truck, depot, round(var.solution_value, 3)))

        f = True
        for key, var in self.asu_queue_cross_var_dict.items():
            if round(var.solution_value, 2):
                if f:
                    print('Нарушение очереди на азс:')
                    f = False
                asu, truck, trip_number, next_truck, next_trip_number = key
                truck = truck % 1000
                next_truck = next_truck % 1000
                print('\tМашины %d и %d, азс %d: %f' % (truck, next_truck, asu, round(var.solution_value, 3)))

        f = True
        for key, var in self.load_after_var_dict.items():
            if round(var.solution_value, 2):
                if f:
                    print('Предлагаемая загрузка под сменщика:')
                    f = False
                truck, depot = key
                truck = truck % 1000
                print('\tМашина %d - нб %d' % (truck, depot))
