import pandas as pd
from models_connector.asu_splitter import asu_splitter
from data_reader.input_data import StaticData
from detailed_planning.dp_parameters import DParameters
from integral_planning.functions import consumption_filter


def extract_asu_idx(row):
    return int(row['id_asu'])


def extract_n_idx(row):
    return int(row['n'])


def extract_asu_n_idx(row):
    return extract_asu_idx(row), extract_n_idx(row)


class ModelsConnector:
    def __init__(self,
                 initial_states: dict,
                 fuel_to_load: pd.DataFrame,
                 time,
                 departures_dict: dict,
                 data: StaticData,
                 dp_parameters: DParameters,
                 fuel_to_load_corrections: dict,
                 departure_corrections: dict):

        self.initial_states = initial_states  # Initial volumes at period start
        self.fuel_to_load = fuel_to_load  # Integral model planned volumes to load
        self.time = time  # Shift number
        self.departures = departures_dict  # Integral model asu visits with times
        self.data = data  # Input data, static information
        self.dp_parameters = dp_parameters  # Detailed data parameters
        self.fuel_to_load_corrections = fuel_to_load_corrections
        self.departure_corrections = departure_corrections

    def loads_corrections(self, asu_n):
        if asu_n in self.fuel_to_load_corrections:
            return self.fuel_to_load_corrections[asu_n]
        else:
            return 0

    """Filter by time:
        - Consumption data
        - Integral model flows
        - Convert data into dictionary"""

    def _filter_by_time(self):

        pandas_filter = self.fuel_to_load.loc[self.fuel_to_load['time'] == self.time]
        consumption_filtered = {(asu, n, time): self.data.consumption[asu, n, time] for asu, n, time in self.data.consumption if
                                time == self.time}

        integral_model_result = {}

        for idx, row in pandas_filter.iterrows():  # row = ['id_asu', 'depot', 'n', 'sku', 'time', 'volume', 'asu_state', 'capacity_min', 'capacity']
            """Including risks of overloading"""
            # TODO Некоторые рейсы длятся более одной смены, поэтому потребление может отличатся и как следствие --- capacity.
            # TODO Так же необходимо учитывать потребление за эти смены (корректировать initial_state)
            empty_space_asu_n = float(row['capacity']) - self.initial_states[extract_asu_n_idx(row)]  # TODO С Васей не будет интегрироваться
                                # - \
                                # self.dp_parameters.risk_tank_overload * \
                                # consumption_filter(self.data.consumption, extract_asu_idx(row), extract_n_idx(row), self.time + 1)
            # + \
            # consumption_filtered[extract_asu_idx(row), extract_n_idx(row), self.time]
            # Consumption is removed because update initial state
            asu = int(row['id_asu'])

            volume = float(row['volume']) + self.loads_corrections(extract_asu_n_idx(row))
            if volume >= self.data.asu_vehicle_avg_section[asu] / 2:
                integral_model_result.setdefault(asu, {})[extract_asu_n_idx(row)] = (volume, empty_space_asu_n)

        for (asu, n), volume in self.fuel_to_load_corrections.items():
            if volume < self.data.asu_vehicle_avg_section[asu] / 2 or \
                    (asu not in self.departure_corrections and asu not in integral_model_result):
                continue
            if asu not in integral_model_result:
                integral_model_result[asu] = {}
            if (asu, n) not in integral_model_result[asu]:
                asu_n_capacity = float(self.data.tanks[(self.data.tanks['asu_id'] == asu) & (self.data.tanks['n'] == n)]['capacity'])
                integral_model_result[asu][asu, n] = (volume, asu_n_capacity - self.initial_states[asu, n])

        unique_asu = set(asu for asu, shift in self.departures
                         if shift == self.dp_parameters.time).union(self.departure_corrections)
        for asu in unique_asu:
            if asu not in integral_model_result:
                (asu, self.dp_parameters.time) in self.departures and self.departures.pop((asu, self.dp_parameters.time))
                asu in self.departure_corrections and self.departure_corrections.pop(asu)

        return integral_model_result

    """Calculate the empty space for cloned asu using percentage of integral flow"""

    @staticmethod
    def calculate_empty_space(n_volumes, volumes_division, empty_spaces, n, trip_num):
        return float(empty_spaces[n]) / n_volumes[n] * volumes_division[n, trip_num]

    """Encoding the asu clones"""

    def encoding_asu_splitting(self, n_volumes, asu_id, trip_amount, empty_spaces):
        # Calculate time to death. Half of trip. TODO Parameter of death is here [0.75]
        distance_to_asu = 0.25 * (self.data.trip_durations[asu_id] / self.dp_parameters.shift_size)
        "Учет сменности работы АЗС"
        next_shift = self.dp_parameters.time % 2 + 1
        is_work = self.data.asu_work_shift[asu_id][next_shift]
        if not is_work:
            distance_to_asu += 0.5

        death_status = [n for n in n_volumes if (self.dp_parameters.asu_tank_death[asu_id, n] - distance_to_asu) <= 0.75]
        reallocated_status = [n for n in n_volumes
                              if (asu_id, n, self.time) in self.data.asu_depot_reallocation and
                              self.data.asu_depot_reallocation[asu_id, n, self.time] != self.data.asu_depot[asu_id]]

        volumes_division = asu_splitter(n_volumes, asu_id, self.data, trip_amount, self.dp_parameters, death_status, reallocated_status)  # split for n trucks
        result_volumes = {}

        for n, trip_num in volumes_division:
            asu_new = self.dp_parameters.asu_encoder(asu_id, trip_num + 1)
            if asu_new in result_volumes:
                result_volumes[asu_new][asu_new, n] = [volumes_division[n, trip_num],
                                                       self.calculate_empty_space(n_volumes, volumes_division, empty_spaces, n, trip_num)]
            else:
                result_volumes[asu_new] = {}
                result_volumes[asu_new][asu_new, n] = [volumes_division[n, trip_num],
                                                       self.calculate_empty_space(n_volumes, volumes_division, empty_spaces, n, trip_num)]

        return result_volumes

    """Split [volume, empty section] for two"""

    @staticmethod
    def split_volumes_and_empty_sections(n_set_to_divide):
        integral_load = {}
        empty_space = {}
        for n in n_set_to_divide:
            integral_load[n[1]] = n_set_to_divide[n][0]
            empty_space[n[1]] = n_set_to_divide[n][1]

        return integral_load, empty_space

    """Departures with departure_corrections"""

    @staticmethod
    def correct_departures(departures, departure_corrections, shift):
        result = departures.copy()
        for asu, count in departure_corrections.items():
            if (asu, shift) in departures:
                result[asu, shift] += count
            else:
                result[asu, shift] = count
        return result

    """Convert data for detailed planning algorithms"""

    def convert_data(self):

        integral_model_result = self._filter_by_time()  # Prepare data for detailed model
        departures = self.correct_departures(self.departures, self.departure_corrections, self.time)

        asu_to_visit = {asu: departures[asu, time] for asu, time in departures
                        if time == self.time and departures[asu, time] > 1}  # Asu to splitting

        for asu in asu_to_visit:
            n_set_to_divide = integral_model_result[asu]
            n_volumes, empty_spaces = self.split_volumes_and_empty_sections(n_set_to_divide)
            new_asu_set = self.encoding_asu_splitting(n_volumes, asu, asu_to_visit[asu], empty_spaces)
            integral_model_result.update(new_asu_set)
            integral_model_result.pop(asu)

        """Returns """
        return integral_model_result
