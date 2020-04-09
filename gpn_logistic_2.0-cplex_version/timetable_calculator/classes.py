from data_reader.input_data import StaticData, Parameters, get_distance

"""TruckRoute - uet -> (depot1 -> asu11 -> asu12) trip1 -> (depot2 -> asu21 -> asu22) trip2 -> depot3 -> uet:
    - not own truck starts on depot1
    - in route can be one or two trips
    - if truck is loaded before it ignores depot1
    - not own truck truck can't be loaded before
    - depot3 is depot fot load after
    """


class TruckRoute:
    def __init__(self, time: int, truck: int, trips: list, parameters: Parameters, data: StaticData):
        self.time = time
        self.shift = 2 - self.time % 2  # shift number: 1 or 2
        self.truck = truck  # truck number
        self.trips = trips  # trip order: (trip1, trip2)
        self.parameters = parameters
        self.data = data
        self.depots_for_load_after = []
        self.waiting_times = {}  # fill after model calc
        self.is_two_trips = len(self.trips) == 2  # route is double
        self.is_empty_route = len(self.trips) == 0  # route is double
        self.is_load_before = False  # truck is already loaded, ignore depot1
        self.is_own_truck = self.data.vehicles[truck].is_own
        self.is_busy_at_start = False
        self.start_time = 0
        self.route_structure = {
            'uet1': self.data.vehicles[self.truck % 1000].uet if self.is_own_truck or self.is_empty_route else self.trips[0].depot,
            'depot1': self.trips[0].depot if not self.is_empty_route else 0,
            'asu11': self.trips[0].route[0] if not self.is_empty_route else 0,
            'asu12': self.trips[0].route[1] if not self.is_empty_route and self.trips[0].is_double_trip else 0,
            'depot2': self.trips[1].depot if self.is_two_trips else 0,
            'asu21': self.trips[1].route[0] if self.is_two_trips else 0,
            'asu22': self.trips[1].route[1] if self.is_two_trips and self.trips[1].is_double_trip else 0,
            'depot3': 0,
            'uet2': self.data.vehicles[self.truck % 1000].uet
        }
        self.check_is_truck_busy()
        self.is_far = not self.is_empty_route and not self.is_two_trips and not self.trips[0].is_double_trip and \
                      self.trips[0].route[0] in data.far_asu
        self.is_long_route = not self.is_empty_route and (self.define_is_long_route() or self.is_far)
        self.is_cut_route = False
        self.delete_moving_to_uet = False

    route_structure = ['uet1', 'depot1', 'asu11', 'asu12', 'depot2', 'asu21', 'asu22', 'depot3', 'uet2']

    def total_duration(self, depot3=0):
        return self.get_arrival_time('uet2', depot3)

    """Get arrival time to route point"""
    def get_arrival_time(self, point: str, depot3=0):
        last_point = self.get_last_point(point)
        if last_point:
            return self.get_arrival_time(last_point, depot3) + self.get_working_time(last_point, depot3) + \
                   self.get_waiting_time(point, depot3) + self.get_moving_time(point, depot3)
        return self.start_time

    """Get waiting time on route point"""
    def get_waiting_time(self, point: str, depot3=0):
        key = (depot3 if point == 'depot3' else self.route_structure[point],
               self.get_trip_number_from_point_name(point))
        return self.waiting_times.get(key, 0)

    """Get moving time to route point"""
    def get_moving_time(self, point: str, depot3=0):
        switch = {
            'uet1': lambda: 0,
            'depot1': lambda: self.get_start_position_nb1_dist() if not self.is_load_before and not self.is_empty_route else 0,
            'asu11': lambda: (self.trips[0].get_nb_asu1_dist(self.data.distances_asu_depot) if not self.is_load_before else self.get_uet_asu1_dist()) if not self.is_empty_route else 0,
            'asu12': lambda: self.trips[0].get_asu1_asu2_dist(self.data.distances_asu_depot) if not self.is_empty_route else 0,
            'depot2': lambda: self.get_trip1_nb2_dist() if not self.is_empty_route else 0,
            'asu21': lambda: self.trips[1].get_nb_asu1_dist(self.data.distances_asu_depot) if self.is_two_trips and not self.is_empty_route else 0,
            'asu22': lambda: self.trips[1].get_asu1_asu2_dist(self.data.distances_asu_depot) if self.is_two_trips and not self.is_empty_route else 0,
            'depot3': lambda: 0 if depot3 == 0 else (self.get_trip2_nb3_dist(depot3) if not self.is_empty_route else self.get_start_position_nb3_dist(depot3)),
            'uet2': lambda: (self.get_trip2_uet_dist() if not self.is_empty_route else 0) if depot3 == 0 else self.get_nb3_uet_dist(depot3)
        }
        result = switch.get(point, 0)()
        return result

    """Get working time on route point"""
    def get_working_time(self, point: str, depot3=0):
        switch = {
            'uet1': lambda: 0,
            'depot1': lambda: self.data.depot_load_time[self.route_structure[point]] if not self.is_load_before and not self.is_empty_route else 0,
            'asu11': lambda: self.trips[0].get_asu_unload_time(self.route_structure[point], self.parameters, self.data) if not self.is_empty_route else 0,
            'asu12': lambda: self.trips[0].get_asu_unload_time(self.route_structure[point], self.parameters, self.data) if not self.is_empty_route else 0,
            'depot2': lambda: self.data.depot_load_time[self.route_structure[point]] if self.is_two_trips and not self.is_empty_route else 0,
            'asu21': lambda: self.trips[1].get_asu_unload_time(self.route_structure[point], self.parameters, self.data) if self.is_two_trips and not self.is_empty_route else 0,
            'asu22': lambda: self.trips[1].get_asu_unload_time(self.route_structure[point], self.parameters, self.data) if self.is_two_trips and not self.is_empty_route else 0,
            'depot3': lambda: 0 if depot3 == 0 else self.data.depot_load_time[depot3],
            'uet2': lambda: 0
        }
        result = switch.get(point, 0)()
        return result

    """Get distance from route point to route point"""
    def get_start_position_nb1_dist(self):
        dist = 0
        if (not self.is_own_truck and not self.is_busy_at_start) or self.is_empty_route:
            return dist
        depot = self.trips[0].depot
        start_point = self.route_structure['uet1']
        if isinstance(start_point, str):
            dist = self.get_uet_dist(start_point, depot)
        elif start_point != depot:
            dist = self.get_asu_depot_dist(start_point, depot)
        return dist

    def get_start_position_nb3_dist(self, depot3):
        dist = 0
        start_point = self.route_structure['uet1']
        if isinstance(start_point, str):
            dist = self.get_uet_dist(start_point, depot3)
        elif start_point != depot3:
            dist = self.get_asu_depot_dist(start_point, depot3)
        return dist

    def get_uet_asu1_dist(self):
        asu = self.route_structure['asu11']
        return self.get_uet_dist(self.data.vehicles[self.truck % 1000].uet, asu) if self.is_own_truck else \
            self.trips[0].get_nb_asu1_dist(self.data.distances_asu_depot)

    def get_trip1_nb2_dist(self):
        dist = 0
        if self.is_two_trips:
            asu = self.trips[0].route[-1]
            depot = self.trips[1].depot
            dist = self.get_asu_depot_dist(asu, depot)
        return dist

    def get_trip2_nb3_dist(self, depot):
        asu = self.trips[-1].route[-1]
        dist = self.get_asu_depot_dist(asu, depot)
        return dist

    def get_trip2_uet_dist(self):
        asu = self.trips[-1].route[-1]
        return self.get_uet_dist(asu, self.data.vehicles[self.truck % 1000].uet) \
            if self.is_own_truck and not self.delete_moving_to_uet else 0

    def get_nb3_uet_dist(self, depot):
        return self.get_uet_dist(depot, self.data.vehicles[self.truck % 1000].uet) \
            if self.is_own_truck and not self.delete_moving_to_uet else 0

    def get_uet_dist(self, point1, point2):
        return self.data.distances_asu_uet[point1, point2]

    def get_asu_depot_dist(self, point1, point2):
        return self.data.distances_asu_depot[point1, point2]

    """Define long route: if default arrival time on first asu is not less than asu window end time"""
    def define_is_long_route(self):
        asu_window_end = self.data.asu_work_time[self.route_structure['asu11']][self.shift][1]
        return self.get_arrival_time('asu11') >= asu_window_end

    def check_is_truck_busy(self):
        real_truck = self.truck % 1000
        if (real_truck, self.time) in self.data.vehicles_busy_hours:
            hour, location = self.data.vehicles_busy_hours[real_truck, self.time]
            if location is None and (self.is_own_truck or self.is_empty_route):
                location = self.data.vehicles[self.truck % 1000].uet
            elif location is None:
                location = self.route_structure['depot1']
            self.route_structure['uet1'] = location
            self.start_time = hour
            self.is_busy_at_start = True

    def copy(self):
        copied_route = TruckRoute(self.time, self.truck, self.trips.copy(), self.parameters, self.data)
        return copied_route

    def reversed_copy(self):
        trips = self.trips.copy()
        trips.reverse()
        copied_route = TruckRoute(self.time, self.truck, trips, self.parameters, self.data)
        return copied_route

    @staticmethod
    def get_last_point(point: str):
        if point not in TruckRoute.route_structure:
            return
        point_index = TruckRoute.route_structure.index(point)
        if point_index == 0:
            return
        return TruckRoute.route_structure[point_index - 1]

    @staticmethod
    def get_trip_number_from_point_name(point: str):
        if 'depot' in point:
            return int(point[-1]) - 1
        if 'asu' in point:
            return int(point[-2]) - 1


"""TruckTrip - depot -> asu1 -> asu2:    
    - in trip route can be one or two asus
    """


class TruckTrip:
    def __init__(self, truck: int, depot: int, route: tuple, volumes: dict, sections: dict,
                 tanks: dict, is_critical: bool, days_to_death: float):
        self.truck = truck  # truck number
        self.depot = depot  # depot number
        self.route = route  # asu order: (asu1, asu2)
        self.volumes = volumes  # asu volume map: {asu1: {sku: volume}, asu2: {sku: volume}}
        self.sections = sections  # asu volume map: {asu1: volume, asu2: volume}
        self.tanks = tanks  # asu volume map: {asu1: [tanks], asu2: [tanks]}
        self.is_double_trip = len(self.route) == 2  # is double trip
        self.is_critical = is_critical
        self.days_to_death = days_to_death

    """Distance between depot and first asu in trip"""

    def get_nb_asu1_dist(self, distances_asu_depot: dict):
        return get_distance(self.depot, self.route[0], distances_asu_depot)

    """Distance between first asu and second asu in trip
        If only one asu in trip: return 0"""

    def get_asu1_asu2_dist(self, distances_asu_depot: dict):
        dist = 0
        if len(self.route) > 1:
            dist = get_distance(self.route[0], self.route[1], distances_asu_depot)
        return dist

    """Truck unload time calculation:
        - First 1000 unload
        - Document filling 
        - Unload speed for truck volume"""

    def get_asu_unload_time(self, asu: int, parameters: Parameters, data: StaticData):

        time = 0
        if asu in self.volumes:
            time += sum(volume / 1000 * parameters.thousand_pour * data.sku_reference[sku]['density']
                        for sku, volume in self.volumes[asu].items()) + parameters.docs_fill + \
                    (parameters.automatic_load if data.asu_automatic_status[asu] else 0) - \
                    (parameters.pump_load * self.sections[asu] if data.asu_pump[asu] else 0)
        else:
            if asu != 0:
                print("Asu: %d isn't loaded" % asu)

        return time
