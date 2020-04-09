from data_reader.input_data import StaticData, Parameters
from integral_planning.functions import consumption_filter, converter_day_to_shift
from output_writer.extract_function import extract_asu_n
import pandas as pd


class OutputCreatorStations:
    def __init__(self, data: StaticData, parameters: Parameters, init_states: dict, time_zero):
        self.data = data
        self.parameters = parameters
        self.output_column_keys = {'asu_id': 0,
                                   'n': 1,
                                   'sku': 2,
                                   'shift': 3,
                                   'volume': 4,
                                   'death_vol': 5,
                                   'capacity': 6,
                                   'is_death': 7,
                                   'days_to_death': 8,
                                   'consumption': 9,
                                   'delivery': 10,
                                   'added_load': 11,
                                   'days_to_death_drive': 12}
        self.init_states = init_states
        """[asu_id, n, sku, shift, volume, death_vol, capacity, is_death, days_to_death, consumption, delivery, days_to_death_drive]"""
        self.asu_tank_states = {}  # states by shift

        """Initialize init states at time_zero"""
        self.initialize_states(time_zero)

    """Calculate time to death"""

    def calculate_time_to_death(self, shift, current_state, asu_id, n, death_vol):
        # TODO Добавлен учет поставок в ближайшую смену, скорректированно при вызове
        volume_in_iteration = current_state
        time_to_death = 0

        for shift_iter in range(shift + 1, self.parameters.absolute_period_start + converter_day_to_shift(self.parameters.hidden_period)):
            consumption = consumption_filter(self.data.consumption, asu_id, n, shift_iter)

            if volume_in_iteration - consumption >= death_vol:
                time_to_death += self.parameters.shift_size
                volume_in_iteration -= consumption
            else:
                for hour in range(1, self.parameters.shift_size + 1):
                    if volume_in_iteration - consumption / self.parameters.shift_size >= death_vol:
                        time_to_death += 1
                        volume_in_iteration -= consumption / self.parameters.shift_size
                    else:
                        break
                break

        return float(time_to_death) / self.parameters.day_size

    # TODO существует метод, возвращающий значение по ключу или, если нет, по умолчанию: values_dict.get((asu_id, tank), 0)
    @staticmethod
    def get_value_or_zero(asu_id, tank, values_dict):
        if (asu_id, tank) in values_dict:
            return values_dict[asu_id, tank]
        else:
            return 0

    def get_time_to_death(self, shift, asu, n):
        shift_asu_tank_states = self.asu_tank_states.get(shift, [])
        asu_tank_days_to_death = [row[self.output_column_keys['days_to_death']] for row in shift_asu_tank_states
                                  if row[self.output_column_keys['asu_id']] == asu and
                                  row[self.output_column_keys['n']] == n]
        if asu_tank_days_to_death:
            return asu_tank_days_to_death[0]
        else:
            print('No asu %d tank %d shift %d in states.' % (asu, n, shift - 1))
            return 0

    """Add one row in state table"""

    def add_asu_tank_state(self, consumption, load, added_load, shift, row: list):
        """row = [asu_id, n, sku, shift, volume, death_vol, capacity, is_death, days_to_death, consumption, delivery,
        added_load, days_to_death_drive]"""
        row_copy = row.copy()
        next_shift = shift % 2 + 1
        row_copy[self.output_column_keys['shift']] = shift
        row_copy[self.output_column_keys['volume']] += load - consumption + added_load
        row_copy[self.output_column_keys['is_death']] = 0 if row_copy[self.output_column_keys['volume']] >= row_copy[
            self.output_column_keys['death_vol']] else 1
        time_to_death = self.calculate_time_to_death(shift,
                                                     row_copy[self.output_column_keys['volume']],
                                                     row_copy[self.output_column_keys['asu_id']],
                                                     row_copy[self.output_column_keys['n']],
                                                     row_copy[self.output_column_keys['death_vol']])
        row_copy[self.output_column_keys['days_to_death']] = time_to_death
        row_copy[self.output_column_keys['consumption']] = consumption
        row_copy[self.output_column_keys['delivery']] = load
        row_copy[self.output_column_keys['added_load']] = added_load
        next_shift_closed = .5 if self.data.asu_work_shift[row_copy[self.output_column_keys['asu_id']]][next_shift] == 0 else 0
        row_copy[self.output_column_keys['days_to_death_drive']] = time_to_death - .5 * self.data.trip_duration(
            row_copy[self.output_column_keys['asu_id']]) / self.data.parameters.day_size - next_shift_closed

        return row_copy

    """Add set of states of whole iteration"""

    def add_all_new_states(self, truck_loads, shift):
        """[asu_id, n, sku, shift, volume, death_vol, capacity, is_death, days_to_death, consumption, delivery,
        added_load, days_to_death_drive]"""
        if shift - 1 not in self.asu_tank_states:
            print('No shift %d in states.' % (shift - 1))
        else:
            self.asu_tank_states[shift] = []

            for state in self.asu_tank_states[shift - 1]:
                asu_n = extract_asu_n(state)
                consumption = consumption_filter(self.data.consumption, asu_n[0], asu_n[1], shift)
                added_load = self.data.volumes_to_add.get((asu_n[0], asu_n[1], shift), 0)
                load = truck_loads.get(asu_n, 0)  # self.get_value_or_zero(asu_n[0], asu_n[1], truck_loads)
                self.asu_tank_states[shift].append(self.add_asu_tank_state(consumption, load, added_load, shift, state))

    """Prepare output in pandas DataFrame."""

    def collect_into_pandas(self, write_results=False):
        result_union = []
        shift_last = 0
        for shift in self.asu_tank_states:
            result_union.extend(self.asu_tank_states[shift])
            shift_last = shift

        asuStatesDataFrame = pd.DataFrame(result_union,
                                          columns=['asu_id', 'n', 'sku', 'shift', 'asu_state', 'death_vol', 'capacity', 'is_death',
                                                   'days_to_death', 'consumption', 'delivery', 'added_load', 'days_to_death_drive'])

        if write_results:
            writer = pd.ExcelWriter('./output/asu_states_until_shift_%d.xlsx' % shift_last)
            asuStatesDataFrame.to_excel(writer, 'asu_states')
            writer.save()

        return asuStatesDataFrame

    def initialize_states(self, time_zero):
        """[asu_id, n, sku, shift, volume, death_vol, capacity, is_death, days_to_death, consumption, delivery,
        added_load, days_to_death_drive]"""
        self.asu_tank_states[time_zero] = []
        for idx, row in self.data.tanks.iterrows():
            state_row = []
            asu_id = int(row[['asu_id']])
            n = int(row[['n']])
            current_shift = 2 - time_zero % 2

            state_row.append(asu_id)
            state_row.append(n)
            state_row.append(self.data.tank_sku[asu_id, n])  # sku
            state_row.append(time_zero)  # shift
            state_row.append(self.init_states[asu_id, n])  # volume
            state_row.append(float(row[['capacity_min']]))
            state_row.append(float(row[['capacity']]))
            state_row.append(0 if state_row[self.output_column_keys['volume']] >= state_row[self.output_column_keys['death_vol']] else 1)
            day_to_death = self.calculate_time_to_death(time_zero,
                                                          state_row[self.output_column_keys['volume']] + self.data.volumes_to_add.get(
                                                              (asu_id, n, time_zero + 1), 0),
                                                          state_row[self.output_column_keys['asu_id']],
                                                          state_row[self.output_column_keys['n']],
                                                          state_row[self.output_column_keys['death_vol']])
            state_row.append(day_to_death)  # days_to_death
            state_row.append(0)  # consumption
            state_row.append(0)  # delivery
            state_row.append(0)  # added_load
            next_shift_closed = .5 if self.data.asu_work_shift[asu_id][current_shift] == 0 else 0
            state_row.append(day_to_death - .5 * (self.data.trip_duration(asu_id) // self.data.parameters.shift_size) - next_shift_closed -
                             0.25 * ((self.data.trip_duration(asu_id) % self.data.parameters.shift_size) / self.data.parameters.shift_size))  # days_to_death_drive

            self.asu_tank_states[time_zero].append(state_row)
