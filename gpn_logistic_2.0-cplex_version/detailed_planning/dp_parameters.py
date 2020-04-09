from data_reader.input_data import Parameters
import pandas as pd


# ====================== Classes=====================
class DParameters(Parameters):
    def __init__(self, time, path=''):
        super().__init__()
        self.path = path
        self.time = time  # shift number

        self.trucks_used = []  # Used trucks in previous shift
        self.truck_loaded = {}  # Is truck loaded?
        self.own_trucks = []  # Set of own trucks
        self.asu_tank_death = {}  # Dict of asu tank days to death
        self.asu_trip_number = {}  # Dict of encoding asu and number of trip

        """Asu splitter parameters:
            - write lp files of asu_splitter (true/false)
            - path to save files"""
        self.write_asu_splitter_model = True
        self.path_to_save_splitter = './asu_splitter.lp'

        """Objective function of minimize_penalties:
            - Load penalties (minimize)
            - Own trucks use priority (maximize)
            - Double trip increase (maximize)
            - turnaround increase (maximize)"""
        self.load_penalties_obj = True  # Add to objective load penalties
        self.load_penalties_weight = 0.1  # Weight of load penalties (should be minimized)
        self.own_truck_obj = True  # Add to objective own trucks bonus
        self.own_truck_weight = - 501  # Weight of own truck bonus (should be maximized)
        self.double_trips_obj = True  # Add to objective double trips bonus
        self.double_trips_weight = - 100   # Weight of double trip bonus (should be maximized)
        self.turnaround_obj = True  # Add to objective turnaround bonus
        self.turnaround_weight = - 90  # Weight of turnaround bonus (should be maximized)
        self.distance_penalties_obj = True  # Add to objective distance between asu
        self.distance_penalties_weight = 10  # Weight of distance between asu (should be minimized)
        self.idle_distance_penalties_obj = True  # Add to objective penalty for distance between depot and distribution asu
        self.idle_distance_penalties_weight = 1  # Penalty of longest distance between depot and distribution asu
        self.far_asu_third_party_vehicles = True  # Add to objective far asu load with non-own vehicles
        self.far_asu_third_party_vehicles_weight = self.own_truck_weight + self.double_trips_weight + self.turnaround_weight - 10  # Weight of far asu load with non-own vehicles
        self.asu_non_visiting_penalties_obj = True  # Add to objective asu non visiting
        self.asu_non_visiting_weight = (6000, 2000, 700, 500)  # Weight of asu non visiting (should be minimized) (death in shift, death in next shift, other)
        self.asu_closed_next_shift_penalties_obj = True  # Add to objective asu non visiting
        self.asu_closed_next_shift_weight = 500  # Weight of asu non visiting (should be minimized) (death in shift, death in next shift, other)
        self.double_death_route_penalties_obj = True  # Add to objective double route to death in shift asus
        self.double_death_route_weight = 500  # Weight of double route visiting death in shift asu in each half
        self.route_with_distribution = False  # Add to objective penalty for route with distribution
        self.route_with_distribution_weight = 500  # Weight of penalty for route with distribution
        self.route_with_distribution_both_asu_in_group = True  # Add to objective penalty for route with distribution
        self.route_with_distribution_one_asu_in_group = True  # Add to objective penalty for route with distribution
        self.loaded_truck_priority = True  # Add to objective the loaded truck priority
        self.loaded_truck_priority_weight = (-100, -30)  # Weights of loaded truck priority
        self.busy_truck_non_critical_asu = True  # Add to objective penalty for busy truck usage on critical asu  TODO нужно доработать
        self.double_trips_loaded_truck = True  # Add to objective loaded truck usage in double trips
        self.double_trips_loaded_truck_weight = - 50  # Weight bonus loaded truck usage in double trips
        self.loaded_truck_waiting = False  # Add to objective penalty for waiting while truck is loaded
        self.loaded_truck_waiting_weight = 1000  # Weight for penalty for waiting while truck is loaded
        self.asu_queue = False  # Add constraints for asu queue
        self.double_trip_probs = False  # Truck-asu double trip probabilities add to objective
        self.double_trips_probs_weight = - 200  # Truck-asu double trip probabilities weight
        self.depot_restrict_excess = True  # Add to objective penalty for restricts excess
        self.depot_restrict_excess_weight = 6000 / 0.01  # Penalty for excess of 1% of depot restricts
        self.deficit_depot_restrict_excess_weight = 6000 / 0.01  # Penalty for excess of 1% of depot deficit restricts
        self.free_not_deficit_restrict_excess_part = 0.05  # Non-penalty part for non-deficit restricts
        self.cut_off_truck_first = True  # If truck is cut off - first in queue
        self.critical_asu_on_second_long_route = True  # Add to objective 24-hours vehicle, second route, critical asu
        self.critical_asu_on_second_long_route_weight = 1000  # Penalty 24-hours vehicle, second route, critical asu (second type)

        """Objective of truck_load:
            - Lack of load penalty
            - Overloading penalty
            - Empty section penalty
            - Tank forgetting penalty
            - First three sections unload penalty
            - If asu is visited with one section penalty"""
        self.lack_load_penalty = True  # Add to objective lack of load penalty
        self.lack_loading_weight = 0.01  # Penalty size for lack of load (forecasting - loaded)
        self.overloading_penalty = True  # Add to objective overloading penalty
        self.overloading_weight = 0.1  # Penalty size for overloading (loaded - forecasting)  TODO test deficit and tune
        self.empty_section_penalty = True  # Add to objective empty section penalty
        self.empty_section_weight = 20100  # 15000  # penalty size for empty section
        self.tank_forgetting_penalty = True  # Add to objective tank forgetting penalty
        self.tank_not_loaded_weight = self.asu_non_visiting_weight  # Penalty size for removing tank from load
        self.first_empty_section_penalty = True  # Add to objective first three sections load penalty
        self.first_empty_section_weight = 1000000  # penalty size for empty sections in truck beginning
        self.empty_section_in_beginning_penalty = True  # Add to objective first three sections load penalty
        self.empty_section_in_beginning_weight = 3000  # penalty size for empty sections in truck beginning
        self.one_section_to_asu_penalty = False  # Add to objective asu visits with one section penalty
        self.one_section_to_asu_weight = 1000  # Penalty size for one section load to asu

        """Truck load constraint switcher"""
        self.asu_mixed_possibility = True  # Possibility to mix the load in route which contains more than one asu
        self.empty_in_the_middle_possibility = True  # Empty section between two loaded sections

        """Coded asu values"""
        self.encoder_decoder = {}  # Splitting asu keys
        self.get_asu_split = dict()  # Splitting asu

        """Loads info. Initialization after detailed planning optimization"""
        self.truck_load_volumes = {}  # Loads volumes  {truck, [asu1, asu2]: [vol1, vol2, ...]}
        self.truck_load_sequence = {}  # Loads sequences  {truck, [asu1, asu2]: (asu1, n1), ...}

        """Integral model info. Initialization after integral model optimization. Encoded"""
        self.load_info = 0  # Loads info in general  {asu_id: {(asu_id, n): [integral load, empty space)] ...} ... }

        """Trip optimization parameters"""
        self.fragmentation_size = 20  # number of asu to trip optimization iterations
        self.double_trip_probs_dict = {}  # double trip probability: {(truck, asu): prob, ...}

        """Depot queue decrease"""
        self.depot_queue_decrease = {}  # number of truck loading on depot {(depot, interval): count}

        """Depot load info"""
        self.route_depots = {}  # depot corresponds to route {(truck, (asu1, asu2): depot}

        """Route shifting"""
        self.clear_shifting_routes = True
        self.shifting_routes = {}  # {truck: [route1, route2]}
        self.shifting_volumes = {}  # Loads volumes  {truck, [asu1, asu2]: [vol1, vol2, ...]}
        self.shifting_sequence = {}  # Loads sequences  {truck, [asu1, asu2]: (asu1, n1), ...}
        self.shifting_depots = {}  # Loads depots  {truck, [asu1, asu2]: depot, ...}
        self.shifting_load_info = {}  # {asu: {asu_n: (, )})

        self.file_name = "model_parameters"
        self.file_path = "/" + self.file_name + ".xlsx"
        self.sheet_name = 'detailed'

        """Дробность смены пакетной оптимизации"""
        self.partial_package_iter = False

        self.read_parameters()

    def read_parameters(self):
        pd_parameters = pd.ExcelFile(self.path + self.file_path)
        if self.sheet_name in pd_parameters.sheet_names:
            pd_parameters = pd_parameters.parse(self.sheet_name)
            for index, row in pd_parameters.iterrows():
                setattr(self, row['Parameter'], self.convert_type(row['Value']))

    @staticmethod
    def convert_type(value: float):
        return int(value) + (value % 1 or 0)

    """Get asu original number"""
    def asu_decoder(self, asu):
        if asu in self.encoder_decoder:
            return self.encoder_decoder[asu]
        else:
            return asu

    """Get (asu, n) original number"""
    def asu_n_decoder(self, asu_n):
        if asu_n[0] in self.encoder_decoder:
            return self.encoder_decoder[asu_n[0]], asu_n[1]
        else:
            return asu_n

    """Generate new number for asu"""
    def asu_encoder(self, asu, trip_num):
        new_asu = asu + trip_num * 10000000
        self.encoder_decoder[new_asu] = asu
        self.asu_trip_number[new_asu] = trip_num
        self.get_asu_split.setdefault(asu, []).append(new_asu)
        return new_asu

    """Set partial package iteration flag"""
    def set_partial_package_flag(self, iteration: int):
        self.partial_package_iter = iteration % 1 != 0
