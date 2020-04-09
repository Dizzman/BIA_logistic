from data_reader.input_data import Parameters, StaticData
from time import *
import pandas as pd
from integral_planning.functions import *
from docplex.mp.model import Model

from output_writer.output_stations_state import OutputCreatorStations

'''Constraint control panel'''


class ConstraintSwitcher:
    def __init__(self, directory: str):
        self.basic_constraints = True  # Основные ограничения
        self.period_balance_constraint = False  # Балансирование потоков в периоде
        self.truck_amount_constraint = True  # Определение количества машин
        self.absolute_period_balance = False  # Потребление за неделю < доставки
        self.absolute_period_balance_by_asu_n = True  # Потребление за неделю < доставки
        self.truck_amount_restriction_constraint = False  # Ограничение по количеству выездов в смену
        self.truck_day_balance_constraint = False  # Баланс выездов в течении дня в разных сменах
        self.depot_fuel_restrictions = True  # Открытия на НБ
        self.truck_limit = True  # Ограничение по количеству машин
        self.self_car_min_dep_limits = False  # Ограничение на использование всего собственного парка
        self.obj_drive_time = False  # Добавить взвешенное время работы БВ в целевую функцию
        self.obj_death_penalty = True  # Добавить штраф за просушку АЗС в целевую функцию
        self.obj_balance_penalty = True  # Добавить штраф за нарушение баланса на период в целевую функцию
        self.obj_trip_max_penalty = True  # Добавить штраф на максимальное количестов выездов в периоде
        self.directory = directory

        self.file_name = "model_parameters"
        self.file_path = "/" + self.file_name + ".xlsx"
        self.sheet_name = 'integral'

        self.read_parameters()

    def read_parameters(self):
        pd_parameters = pd.ExcelFile(self.directory + self.file_path)
        if self.sheet_name in pd_parameters.sheet_names:
            pd_parameters = pd_parameters.parse(self.sheet_name)
            for index, row in pd_parameters.iterrows():
                setattr(self, row['Parameter'], self.convert_type(row['Value']))

    @staticmethod
    def convert_type(value: float):
        return bool(value)


'''Model generation and optimization'''


class IntegralModel:
    def __init__(self, parameters: Parameters,
                 data: StaticData,
                 initial_state,
                 period_start,
                 period_duration,
                 constraint_switcher: ConstraintSwitcher,
                 previous_period_loaded_sku: dict,
                 output_states_collection: OutputCreatorStations):

        self.parameters = parameters  # Параметры расчета
        self.constraint_switcher = constraint_switcher  # Управление ограничениями модели
        self.data = data
        self.period_start = period_start  # Время начала расчета
        self.period_duration = period_duration  # Длительность периода расчета
        self.initial_state = initial_state  # Остатки на АЗС
        self.previous_period_loaded_sku = previous_period_loaded_sku  # Объем по sku уже загруженный на предыдущих днях
        self.vars_station_state = {}  # a(ijkst): i - asu_id, j - depot_id, k - n, s - sku, t - time
        #  Variable packaging by time
        self.vars_flow = {t: {} for t in range(self.period_start - 1,
                                               self.period_start + self.period_duration)}  # v(ijkst): i - asu_id, j - depot_id, k - n, s - sku, t - time
        self.vars_sections = {}  # y(ijkst): i - asu_id, j - depot_id, k - n, s - sku, t - time
        self.vars_truck = {}  # z(ijt): i - asu_id, j - depot_id, t - time
        self.vars_death = {}  # x(ijkst): i - asu_id, j - depot_id, k - n, s - sku, t - time
        self.vars_period_balance_penalty = {}  # p(s): s - sku
        self.vars_balance_vols_penalty = {}
        self.vars_truck_empty_space = {}
        self.model = Model('Integral Model')
        self.output_states_collection = output_states_collection
        self.dep_per_shift_max = self.model.integer_var(lb=0, name='z_max')

        '''Models init'''
        self.start_volume_corrections = {}
        self.local_initial_states = self.all_initial_states_correction()
        self.local_consumption = self.consumption_correction()

    def initial_state_correction(self, residue, asu_id, n, capacity):
        if capacity - residue < 0:
            self.start_volume_corrections[asu_id, n] = residue - capacity
            return capacity
        else:
            return residue

    """Tanks capacity is corrected for risk of overloading"""

    def all_initial_states_correction(self):
        previous_init_states = self.initial_state.copy()
        initial_fuel_state = {}

        for idx, vol in self.data.tanks.iterrows():
            capacity_correction = float(vol['capacity']) - overload_risk(asu_id=int(vol['asu_id']),
                                                                         depot=self.data.asu_depot_reallocation[
                                                                             int(vol['asu_id']), int(vol['n']), self.period_start],
                                                                         parameters=self.parameters,
                                                                         data=self.data) * \
                                  consumption_filter(self.data.consumption, int(vol['asu_id']), int(vol['n']), self.period_start)
            initial_fuel_state[int(vol['asu_id']), int(vol['n'])] = self.initial_state_correction(
                residue=previous_init_states[int(vol['asu_id']), int(vol['n'])],
                asu_id=int(vol['asu_id']),
                n=int(vol['n']),
                capacity=capacity_correction)

        return initial_fuel_state

    """Modify the consumption because of overloading"""

    def consumption_correction(self):
        local_consumption = self.data.consumption.copy()

        for asu_id, n in self.start_volume_corrections:
            current_penalty = self.start_volume_corrections[asu_id, n]
            time_inner = self.period_start
            while current_penalty > 0:
                if current_penalty - consumption_filter(local_consumption, asu_id, n, time_inner) < 0:
                    break
                else:
                    current_penalty -= consumption_filter(local_consumption, asu_id, n, time_inner)
                    local_consumption[asu_id, n, time_inner] = 0
                    time_inner += 1
                if time_inner >= self.period_start + self.period_duration:
                    break

        return local_consumption

    '''Basic constraints:
        - Flow balance equations in time
        - Min section departure
        - Death volume penalty constraint
        - Max volume of single np type in the trailer'''

    def constraint_basic(self):

        for t in range(self.period_start - 1, self.period_start + self.period_duration):
            for idx, tank in self.data.tanks.iterrows():
                drive_duration = self.data.trip_durations[extract_asu_id(tank)]
                shift_shifting = drive_duration // self.parameters.shift_size

                '''Инициализация остатков на начало периода планирования'''
                if t == self.period_start - 1:
                    self.vars_station_state[extract_basic_const(tank, t)] = \
                        self.model.continuous_var(lb=self.local_initial_states[extract_asu_id(tank), extract_tank_id(tank)],
                                                  ub=self.local_initial_states[extract_asu_id(tank), extract_tank_id(tank)],
                                                  name='a_%d_%d_%d_%d_%d' % extract_basic_const(tank, t))
                else:

                    shift_value = 1 if t % 2 == 1 else 2
                    depot_val = self.data.asu_depot_reallocation[extract_asu_id(tank), extract_tank_id(tank), t]

                    '''Variable creating'''
                    a = self.model.continuous_var(lb=-10 ** 10,
                                                  ub=extract_capacity(tank) - overload_risk(asu_id=extract_asu_id(tank),
                                                                                            depot=extract_depot_id(tank),
                                                                                            parameters=self.parameters,
                                                                                            data=self.data) *
                                                     consumption_filter(self.local_consumption,
                                                                        extract_asu_id(tank),
                                                                        extract_tank_id(tank),
                                                                        t),
                                                  name='a_%d_%d_%d_%d_%d' % extract_basic_const(tank, t))

                    # Add variable to storage
                    self.vars_station_state[extract_basic_const(tank, t)] = a

                    # Груз выйдет сегодня, но дойдет только завтра
                    if t + shift_shifting < self.period_start + self.period_duration:
                        depot_allocated = self.data.asu_depot_reallocation[extract_asu_id(tank), extract_tank_id(tank), t]
                        v = self.model.continuous_var(
                            lb=0,
                            ub=(dep_shift_available(self.data.asu_work_shift[extract_asu_id(tank)],
                                                    t,
                                                    self.parameters.max_truck_to_asu *
                                                    self.data.asu_vehicle_avg_volume[extract_asu_id(tank)])
                                if self.data.depot_work_shift[depot_val][shift_value] == 1 and (
                                depot_allocated, extract_sku(tank)) in self.data.fuel_in_depot_inverse else 0),
                            name='v_%d_%d_%d_%d_%d' % extract_basic_const(tank, t))
                    else:
                        v = self.model.continuous_var(
                            lb=0,
                            ub=0,
                            name='v_%d_%d_%d_%d_%d' % extract_basic_const(tank, t))
                    # Add variable to storage
                    self.vars_flow[t][extract_basic_const(tank, t)] = v

                    x = self.model.continuous_var(
                        lb=0,
                        name='x_%d_%d_%d_%d_%d' % extract_basic_const(tank, t))
                    # Add variable to storage
                    self.vars_death[extract_basic_const(tank, t)] = x

                    y = self.model.binary_var(
                        name='y_%d_%d_%d_%d_%d' % extract_basic_const(tank, t))
                    # Add variable to storage
                    self.vars_sections[extract_basic_const(tank, t)] = y

                    '''Constraints construction'''
                    self.model.add_constraint_(a == self.vars_station_state[extract_basic_const(tank, t - 1)] +
                                               (self.vars_flow[t - shift_shifting][extract_basic_const(tank, t - shift_shifting)]
                                                if (t - shift_shifting) > self.period_start - 1 else 0) -
                                               consumption_filter(self.local_consumption,
                                                                  extract_asu_id(tank),
                                                                  extract_tank_id(tank), t) +
                                               self.data.volumes_to_add.get((extract_asu_id(tank), extract_tank_id(tank), t), 0),
                                               ctname='Petroleum_Station_States_%d_%d_%d_%d_%d' % extract_basic_const(tank, t))
                    self.model.add_constraint_(v >= self.data.asu_vehicle_avg_section[extract_asu_id(tank)] * y,
                                               ctname='Min_dep_volume_%d_%d_%d_%d_%d' % extract_basic_const(tank, t))
                    self.model.add_constraint(v <= self.parameters.max_truck_to_asu *
                                              self.data.asu_vehicle_avg_volume[extract_asu_id(tank)] *
                                              y,
                                              ctname='Max_dep_volume_%d_%d_%d_%d_%d' % extract_basic_const(tank, t))
                    # self.model.addConstr(a >= extract_capacity_min(tank) + self.parameters.risk_death_volume *
                    #                      consumption_filter(self.local_consumption,
                    #                                         extract_asu_id(tank),
                    #                                         extract_tank_id(tank),
                    #                                         t + 1) - x,
                    #                      'Min_fuel_volume_%d_%d_%d_%d_%d' % extract_basic_const(tank, t))
                    self.model.add_constraint_(a >= death_volume_with_risk(asu_id=extract_asu_id(tank),
                                                                           n=extract_tank_id(tank),
                                                                           depot=extract_depot_id(tank),
                                                                           shift_current=t,
                                                                           consumption=self.local_consumption,
                                                                           capacity_min=extract_capacity_min(tank),
                                                                           parameters=self.parameters,
                                                                           data=self.data) - x,
                                               ctname='Min_fuel_volume_%d_%d_%d_%d_%d' % extract_basic_const(tank, t))

    '''Truck amount constraint
        - Upper restriction by truck amount variable
        - Lower restriction by truck amount variable'''

    def constraint_truck_amount(self):
        for t in range(self.period_start, self.period_start + self.period_duration):
            for idx, tank in self.data.tanks[['asu_id', 'depot_id']].drop_duplicates().iterrows():
                z = self.model.integer_var(lb=0,
                                           ub=self.parameters.max_truck_to_asu,
                                           name='z_%d_%d_%d' % (extract_asu_id(tank), extract_depot_id(tank), t))
                self.vars_truck[extract_asu_id(tank), extract_depot_id(tank), t] = z

                set_tanks_in_asu = list(filter(lambda x: extract_tank_from_vars(x) == (extract_asu_id(tank),
                                                                                       extract_depot_id(tank), t),
                                               self.vars_flow[t].keys()))

                self.model.add_constraint_(self.model.sum(self.vars_flow[t][v] for v in set_tanks_in_asu) <=
                                           self.data.asu_vehicle_avg_volume[extract_asu_id(tank)] * z,
                                           ctname='Truck_dep_volume_%d_%d_%d' % (extract_asu_id(tank), extract_depot_id(tank), t))

                self.model.add_constraint_(self.model.sum(self.vars_flow[t][v] for v in set_tanks_in_asu) >=
                                           self.data.asu_vehicle_avg_volume[extract_asu_id(tank)] * (z - 1) + 0.01,
                                           ctname='Truck_dep_volume_max_%d_%d_%d' % (
                                               extract_asu_id(tank), extract_depot_id(tank), t))

    '''Period balance constraint:
        - End period volumes by sku is greater then start volumes by sku * balance coefficient
        - Violation of constraint is allowed for parameters.ub_week_flow_balance value'''

    def constraint_period_balance(self):
        for sku in self.data.sku_vs_sku_name:
            p = self.model.continuous_var(lb=0, ub=self.parameters.ub_period_flow_balance,
                                          name='p_%d' % sku)

            self.vars_period_balance_penalty[sku] = p

            # Объем топлива в баках с типом НП = sku на конец периода
            set_end = list(
                filter(lambda x: extract_sku_from_vars(x) == sku and extract_time_from_vars(
                    x) == self.period_start + self.period_duration - 1,
                       self.vars_station_state.keys()))
            # Объем топлива в баках с типом НП = sku на начало периода
            set_start = list(
                filter(
                    lambda x: extract_sku_from_vars(x) == sku and extract_time_from_vars(x) == (self.period_start - 1),
                    self.vars_station_state.keys()))

            self.model.add_constraint_(sum(self.vars_station_state[a] for a in set_end) -
                                       sum(self.vars_station_state[a] for a in set_start) *
                                       self.parameters.period_flow_balance_coef + p >= 0,
                                       ctname='period_balancing_fuel_volume_%d' % sku)

    '''Absolute period balance constraints:
        - The sum of consumption * balance coefficient is less than delivered volumes by sku
        - Calculation period is absolute, this means, that delivered volumes from previous iterations is included
        - Constraint violation is not allowed'''

    # def constraint_consumption_vs_delivery(self):
    #     for sku in self.data.sku_vs_sku_name:
    #         if sku != 7:
    #             vars_flow_in_period = {}
    #             # Если окончание абсолютного периода планирования больше чем, начало текущего, то добавляем ограничения
    #             if self.parameters.absolute_period_start + self.parameters.absolute_period_duration >= self.period_start:
    #
    #                 for t in range(self.period_start, self.parameters.absolute_period_start + self.parameters.absolute_period_duration):
    #                     vars_flow_in_period[t] = list(filter(
    #                         lambda x: extract_sku_from_vars(x) == sku, self.vars_flow[t].keys()))
    #
    #                 self.model.addConstr(sum(sum(self.vars_flow[t][asu] for asu in vars_flow_in_period[t]) for t in vars_flow_in_period) +
    #                                      self.previous_period_loaded_sku[sku] - self.parameters.period_flow_balance_coef *
    #                                      self.data.absolute_period_consumption[self.data.absolute_period_consumption['sku'] ==
    #                                                                            sku]['consumption'] >= 0,
    #                                      'absolute_period_balancing_fuel_volume_%d' % sku)

    def constraint_consumption_vs_delivery(self):
        for sku in self.data.sku_vs_sku_name:
            self.vars_balance_vols_penalty[sku] = self.model.continuous_var(lb=0, name='sku_pen_%d' % sku)
            vars_flow_in_period = {}
            # Если окончание абсолютного периода планирования больше чем, начало текущего, то добавляем ограничения
            if self.parameters.absolute_period_start + self.parameters.absolute_period_duration >= self.period_start:

                for t in range(self.period_start, self.parameters.absolute_period_start + self.parameters.absolute_period_duration):
                    vars_flow_in_period[t] = list(filter(
                        lambda x: extract_sku_from_vars(x) == sku, self.vars_flow[t].keys()))

                # Comment by Vasiliy / 02.03.2019:
                # Переменная _temp_consumption введена в связи с тем, что объекты
                # класса pandas.core.series.Series не обрабатываются в методе
                # add_constraint_() библиотеки docplex.

                _temp_consumption = self.data.absolute_period_consumption[
                    self.data.absolute_period_consumption['sku'] == sku
                    ]['consumption']

                _temp_consumption = float(_temp_consumption)

                self.model.add_constraint_(
                    self.model.sum(self.model.sum(self.vars_flow[t][asu] for asu in vars_flow_in_period[t]) for t in vars_flow_in_period) +
                    self.previous_period_loaded_sku[sku] - self.parameters.period_flow_balance_coef *
                    _temp_consumption + self.vars_balance_vols_penalty[sku] >= 0,
                    ctname='absolute_period_balancing_fuel_volume_%d' % sku)

    def constraint_consumption_vs_delivery_by_asu_n(self):
        for idx, row in self.data.absolute_period_consumption_by_asu_n.iterrows():
            asu_id = int(row['asu_id'])
            n = int(row['n'])
            # TODO if != G100
            if self.parameters.absolute_period_start + self.parameters.absolute_period_duration >= self.period_start and self.data.tank_sku[
                asu_id, n] != 4:
                sum_asu_n = 0
                self.vars_balance_vols_penalty[asu_id, n] = self.model.continuous_var(lb=0, name='sku_pen_%d_%d' % (asu_id, n))
                find_first_key = None
                for t in range(self.period_start,
                               self.parameters.absolute_period_start + self.parameters.absolute_period_duration):
                    if t in self.vars_flow:
                        if not find_first_key:
                            set_of_vars = [key for key in self.vars_flow[t] if key[0] == asu_id and key[2] == n]
                            if set_of_vars:
                                find_first_key = set_of_vars[0][0:-1]
                                sum_asu_n += self.vars_flow[t][find_first_key + (t,)] if find_first_key + (t,) in self.vars_flow[
                                    t] else 0
                        else:
                            sum_asu_n += self.vars_flow[t][find_first_key + (t,)] if find_first_key + (t,) in self.vars_flow[t] else 0

                self.model.add_constraint_(sum_asu_n - self.parameters.period_flow_balance_coef *
                                           int(row['consumption']) + self.vars_balance_vols_penalty[asu_id, n] >= 0,
                                           ctname='absolute_period_balancing_fuel_volume_%d_%d' % (asu_id, n))

    '''Truck departures restriction constraint:
        - Add the restriction for number of average departures to asu per shift
        - Restriction for different shifts can differs, depends on parameter truck_time_restrictions'''

    def constraint_truck_departures_restriction(self):
        for t in range(self.period_start, self.period_start + self.period_duration):
            if t in self.parameters.truck_time_restrictions:
                departures_of_trucks = list(
                    filter(lambda x: extract_time_from_truck_vars(x) == t, self.vars_truck.keys()))
                self.model.add_constraint_(
                    self.model.sum(self.vars_truck[z] for z in departures_of_trucks) <= self.parameters.truck_time_restrictions[t],
                    ctname='Constraint_truck_amount_%d' % t)

    '''Truck departures balance into the day shifts constraint:
        - Difference between departures in first shift and second in not greater than truck_day_balance
        - ABS variable is not added to storage, because is not needed in future'''

    def constraint_into_day_truck_balance(self):
        for t in range(self.period_start, self.period_start + self.period_duration):
            if t % 2 == 1:
                truck_dep_first_shift = list(
                    filter(lambda x: extract_time_from_truck_vars(x) == t, self.vars_truck.keys()))
                truck_dep_second_shift = list(
                    filter(lambda x: extract_time_from_truck_vars(x) == t + 1, self.vars_truck.keys()))
                # Create abs variable
                # abs_variable = self.model.addVar(lb=-self.parameters.truck_day_balance,
                #                                  ub=self.parameters.truck_day_balance,
                #                                  vtype=GRB.CONTINUOUS,
                #                                  name='abs_truck_day_%d' % t)

                self.model.add_constraint_(self.model.sum(self.vars_truck[z] for z in truck_dep_first_shift) -
                                           self.model.sum(
                                               self.vars_truck[z] for z in truck_dep_second_shift) >= -self.parameters.truck_day_balance,
                                           ctname='Balancing_truck_during_day_1_%d' % t)

                self.model.add_constraint_(self.model.sum(self.vars_truck[z] for z in truck_dep_first_shift) -
                                           self.model.sum(
                                               self.vars_truck[z] for z in truck_dep_second_shift) <= self.parameters.truck_day_balance,
                                           ctname='Balancing_truck_during_day_2_%d' % t)
                # self.model.addConstr(abs_variable == sum(self.vars_truck[z] for z in truck_dep_first_shift) -
                #                      sum(self.vars_truck[z] for z in truck_dep_second_shift),
                #                      'Balancing_truck_during_day_%d' % t)

    '''Depots have a restrictions for possible fuel to load
        - For each sku each depot has a limit
        - If fuel equals to 0 => asu is allocated to nearest depot which has such kind of fuel'''

    def constraint_depot_fuels(self):
        flows_by_day = convert_flows_shifts_to_days(self.period_start, self.period_start + self.period_duration, self.vars_flow)

        restriction_filtered = {(depot, depot_sku, day): volume for (depot, depot_sku, day), volume in self.data.restricts.items()
                                if day_calculation_by_shift(self.period_start) <= day
                                < day_calculation_by_shift(self.period_start + self.period_duration)}

        for depot, depot_sku, day in restriction_filtered:  # self.data.restricts:
            vars_in_day = flows_by_day[day]  # i - asu_id, j - depot_id, k - n, s - sku, t - time
            vars_to_restriction = [vars_in_day[asu_id, depot_id, n, sku, t] for asu_id, depot_id, n, sku, t in vars_in_day if
                                   self.data.asu_depot_reallocation[asu_id, n, t] == depot and sku in self.data.fuel_in_depot[
                                       depot, depot_sku]]

            if len(vars_to_restriction) > 0:
                self.model.add_constraint_(self.model.sum(vars_to_restriction) <= self.data.restricts[depot, depot_sku, day],
                                           ctname='depot_flow_restrictions_%d_%d_%d' % (depot, depot_sku, day))

                '''There is a special case of flow restrictions for the night shift
                        - Volume of nights' restriction is the limit fot the night and next days' shift'''

                if self.parameters.absolute_period_start == 2 and day == 1:
                    vars_to_restriction = []
                    for shift in [2, 3]:
                        vars_to_restriction.extend([var for (asu_id, depot_id, n, sku, t), var in self.vars_flow.get(shift, {}).items() if
                                                    self.data.asu_depot_reallocation[asu_id, n, t] == depot and sku in
                                                    self.data.fuel_in_depot[depot, depot_sku]])

                    self.model.add_constraint_(self.model.sum(vars_to_restriction) <= self.data.restricts[depot, depot_sku, day],
                                               ctname='depot_flow_restrictions_night_shift_%d_%d_%d' % (depot, depot_sku, day))

    '''Limit of departures depending on truck amount
        - Minimal turnover influence
        - Truck amount for planning'''

    def constraint_truck_possible_drive_time(self):
        for shift in range(self.period_start, self.period_start + 1):
            free_vehicles = truck_available(self.data.vehicles_busy, self.data.vehicles, shift)

            def truck_coef(busy_hours):
                shift_part = busy_hours / self.parameters.shift_size
                return shift_part if shift_part < 0.75 else 1

            trucks_from_previous_shift = [
                self.vars_truck[z] * truck_coef(self.data.trip_durations[z[0]] + 3 - self.parameters.shift_size * (shift - z[2]))
                for z in self.vars_truck if (shift - (self.data.trip_durations[z[0]] + 3) // self.parameters.shift_size) <= z[2] < shift]
            # TODO необходимо скорректировать под разную длительность работы БВ (размер смены)
            busy_truck_hours_from_previous_shift = [truck_coef(hour) for (truck, busy_shift), (hour, location)
                                                    in self.data.vehicles_busy_hours.items() if
                                                    busy_shift == shift and truck in free_vehicles and self.data.vehicles[
                                                        truck].shift_size <= self.parameters.shift_size]
            # busy_truck_hours_from_previous_shift = []

            self.model.add_constraint_(self.model.sum(self.vars_truck[z] for z in self.vars_truck if z[2] == shift) <= (
                    len(free_vehicles) - sum(trucks_from_previous_shift) - sum(busy_truck_hours_from_previous_shift)) *
                                       self.parameters.min_turnover * self.parameters.truck_capacity_part,
                                       ctname='truck_possible_drive_time_%d' % shift)

    def constraint_truck_possible_drive_time_min(self):

        for shift in range(self.period_start + 1, self.period_start + self.period_duration):
            self.model.add_constraint_(
                self.model.sum(self.vars_truck[z] for z in self.vars_truck if z[2] == shift) <= self.dep_per_shift_max,
                ctname='truck_possible_drive_time_%d' % shift)

    '''Self car usage
        - All self cars should be used'''

    def constraint_self_car_usage(self):

        set_self_cars = [1 for truck in self.data.vehicles if self.data.vehicles[truck].is_own == 1]

        for shift in range(self.period_start, self.period_start + self.period_duration):
            self.model.add_constraint_(self.model.sum(self.vars_truck[z] for z in self.vars_truck if z[2] == shift) >= sum(set_self_cars),
                                       ctname='self_car_usage_%d' % shift)

    '''Drive time calculation:
        - Distance from uet to asu and back
        - Distance from asu to nb and back
        - Fuel fill and drain into truck'''

    def objective_function_add_drive_costs(self):
        # TODO не сделана поправка с нескольми uet!
        return sum(self.parameters.truck_work_cost * self.vars_truck[z] *
                   (2 * self.data.distances_asu_depot[extract_from_to_truck_vars(z)] +
                    2 * self.data.distances_asu_uet[self.parameters.uet_name, extract_from_to_truck_vars(z)[0]] +
                    2 * self.parameters.petrol_load_time) for z in self.vars_truck)

    '''Weighted balance penalty'''

    def objective_function_add_period_balance_penalty(self):
        return self.parameters.balance_penalty * \
               self.model.sum(self.vars_period_balance_penalty[p] for p in self.vars_period_balance_penalty)

    '''Weighted penalty for death'''

    def objective_function_add_death_penalty(self):
        return self.parameters.death_penalty * self.model.sum(self.vars_death[d] for d in self.vars_death)
        # return self.parameters.death_penalty * sum((1 if d[-1] - self.period_start < 4 else 0) * self.vars_death[d] for d in self.vars_death)

    """Added by Vasiliy, 27.03.2019
    Функция objective_total_time_to_death_penalties
    """

    def objective_total_time_to_death_penalties(self):
        """Функция, которая формирует выражения для штрафа за откладывание по-
        полнения резервуаров на следующую смену в целевой функции интегральной
        модели.
        :return: Выражение для целевой функции.
        """

        objective_expression = 0

        def weight_calc(time_to_death_var):
            return 4 - time_to_death_var // 0.5

        for idx, tank in self.data.tanks.iterrows():
            asu_id = extract_asu_id(tank)
            tank_id = extract_tank_id(tank)
            time_to_death = self.output_states_collection.get_time_to_death(self.period_start - 1, asu_id, tank_id)
            next_shift = 1 if (self.period_start + 1) % 2 == 1 else 2

            # print("shift = {}, asu = {}, tank = {}, time_to_death = {}".format(self.period_start, asu_id, tank_id, time_to_death))

            """Modified by Alex, 28.03.2019"""
            # objective_expression += (1 - self.vars_sections[extract_basic_const(tank, self.period_start)]) / (0.001 * time_to_death)
            objective_expression -= self.vars_sections[extract_basic_const(tank, self.period_start)] * 1.5 * weight_calc(
                time_to_death) if time_to_death <= 1.5 else 0
            objective_expression -= self.vars_sections[extract_basic_const(tank, self.period_start)] * 3 if \
                (time_to_death <= 2 and self.data.asu_work_shift[asu_id][next_shift] == 0) else 0

        return objective_expression

    '''Collect optimal flows for output'''

    def output_collect_flow_results(self):
        flow_vars_values_matrix = []

        """Extract the flow and state"""
        for t in self.vars_flow:
            for key in self.vars_flow[t]:
                if round(self.vars_flow[t][key].solution_value) > 0:
                    key_list = [extractor_asu_output(key),
                                extractor_depot_output(key),
                                extractor_n_output(key),
                                extractor_sku_output(key),
                                t,
                                round(self.vars_flow[t][key].solution_value, 2),
                                round(self.vars_station_state[key].solution_value, 2),
                                self.vars_station_state[key].lb,
                                self.vars_station_state[key].ub]
                    flow_vars_values_matrix.append(key_list)

        flow_data = pd.DataFrame(flow_vars_values_matrix, columns=['id_asu', 'depot', 'n', 'sku', 'time', 'volume',
                                                                   'asu_state', 'capacity_min', 'capacity'])

        return flow_data

    '''Collect optimal departures'''

    def output_collect_departures_amount(self):

        departures_dict = {}
        departure_vars_values_matrix = []

        """Extract the departures"""
        for key in self.vars_truck:
            if self.vars_truck[key].solution_value > 0:
                departures_dict[extract_from_to_truck_vars(key)[0], extract_time_from_truck_vars(key)] = \
                    round(self.vars_truck[key].solution_value)
                key_list = [extract_from_to_truck_vars(key)[0],
                            extract_from_to_truck_vars(key)[1],
                            extract_time_from_truck_vars(key),
                            round(self.vars_truck[key].solution_value)]
                departure_vars_values_matrix.append(key_list)

        departures_data = pd.DataFrame(departure_vars_values_matrix, columns=['id_asu', 'depots', 'time', 'departures'])

        return departures_data, departures_dict

    '''Model output'''

    def output_data(self, write_results):
        flow_data = self.output_collect_flow_results()
        departures_data, departures_dict = self.output_collect_departures_amount()

        # Запись результатов интегральной модели
        if write_results:
            package = ('_' + str(self.parameters.package_num)) if isinstance(self.parameters.package_num, int) else ''
            writer = pd.ExcelWriter('./output/integral_model_from_%d_to_%d%s.xlsx' %
                                    (self.period_start, self.period_start + self.period_duration - 1, package))
            flow_data.to_excel(writer, 'volumes')
            departures_data.to_excel(writer, 'departures')
            writer.save()

        return flow_data, departures_data, departures_dict

    '''Construct the integral planning model'''

    def model_construction(self):
        """Basic Constraint"""
        if self.constraint_switcher.basic_constraints:
            self.constraint_basic()
        """Truck amount constraint"""
        if self.constraint_switcher.truck_amount_constraint:
            self.constraint_truck_amount()
        """Period balance constraint"""
        if self.constraint_switcher.period_balance_constraint:
            self.constraint_period_balance()
        """Absolute period balance constraint"""
        if self.constraint_switcher.absolute_period_balance:
            self.constraint_consumption_vs_delivery()
        """Absolute period balance constraint by asu_n"""
        if self.constraint_switcher.absolute_period_balance_by_asu_n:
            self.constraint_consumption_vs_delivery_by_asu_n()
        """Truck amount restriction constraint"""
        if self.constraint_switcher.truck_amount_restriction_constraint:
            self.constraint_truck_departures_restriction()
        """Truck day balance constraint"""
        if self.constraint_switcher.truck_day_balance_constraint:
            self.constraint_into_day_truck_balance()
        """Depot flow restriction (opens)"""
        if self.constraint_switcher.depot_fuel_restrictions:
            self.constraint_depot_fuels()
        """Truck limit"""
        if self.constraint_switcher.truck_limit:
            self.constraint_truck_possible_drive_time()
            self.constraint_truck_possible_drive_time_min()
        """Self truck usage at minimum"""
        if self.constraint_switcher.self_car_min_dep_limits:
            self.constraint_self_car_usage()
        """Objective function sample"""
        objective_function = 0
        """Add to objective function weighted drive time"""
        if self.constraint_switcher.obj_drive_time:
            objective_function += self.objective_function_add_drive_costs()
        """Add to objective function weighted death penalties"""
        if self.constraint_switcher.obj_death_penalty:
            objective_function += self.objective_function_add_death_penalty()
        """Add to objective function weighted balance constraint penalties"""
        if self.constraint_switcher.obj_balance_penalty:
            #     objective_function += self.objective_function_add_period_balance_penalty()
            objective_function += self.parameters.balance_per_tank * sum(
                self.vars_balance_vols_penalty[sku] for sku in self.vars_balance_vols_penalty)
        """Add max trip per shift penalty"""
        if self.constraint_switcher.obj_trip_max_penalty:
            objective_function += self.parameters.trip_costs * self.dep_per_shift_max

        objective_function += self.objective_total_time_to_death_penalties()
        # TODO Modified
        objective_function += sum(
            (1 if t == self.period_start else 2 + 0.05 * t) * self.vars_truck[i, j, t] for i, j, t in self.vars_truck.keys())

        """Set objective function"""
        self.model.minimize(objective_function)

    '''Set optimization parameters'''

    def set_model_parameters(self):
        self.model.parameters.timelimit = self.parameters.time_limit  # Ограничение по времени на итерацию
        self.model.parameters.mip.tolerances.mipgap = self.parameters.gap_level  # Точность расчета
        self.model.parameters.threads = self.parameters.threads  # Количество потоков
        self.model.log_output = True

    '''Model optimization'''

    def optimize(self):
        self.model_construction()  # Построение модели
        print('Stage: Optimize integral model. Period from %d to %d' %
              (self.period_start, self.period_start + self.period_duration - 1))

        start_time = time()  # Фиксирование времени начала расчета
        self.set_model_parameters()  # Настройка модели
        result = self.model.solve()  # Запуск процесса оптимизации модели

        # """Change the strategy of optimization"""
        # if time() - start_time + 50 <= self.parameters.time_limit:
        #
        #     self.model.parameters.timelimit = self.parameters.time_limit - time() + start_time
        #     self.model.parameters.mip.tolerances.mipgap = 0.0
        #     self.model.parameters.mip.strategy.branch = -1
        #     # self.model.parameters.mip.limits.cutpasses = 20
        #     self.model.parameters.mip.cuts.disjunctive = 1
        #     self.model.parameters.mip.cuts.gomory = 2
        #     result = self.model.solve()  # Запуск процесса оптимизации модели

        self.model.export_as_lp(
            './output/integral_model_%d_%d.lp' % (self.period_start, self.period_start + self.period_duration - 1))  # Запись модели

        if not result:
            self.model.export_as_lp(
                './output/integral_model_%d_%d.lp' % (self.period_start, self.period_start + self.period_duration - 1))  # Запись модели
            print("<FOR_USER>\nНЕ НАЙДЕНО решение Интегральной модели. Проверьте входные данные.\n</FOR_USER>")
        #    self.model.computeIIS()
        #    self.model.write('Integral_models_inconsistencies.ilp')

        mip_gap_result = self.model.solve_details.mip_relative_gap * 100
        print('<FOR USER>\nТочность расчета Интегральной модели составляет {0:.2f}% \n</FOR_USER>'.format(mip_gap_result))
        print('<INTEGRAL_GAP>\n%f\n</INTEGRAL_GAP>' % self.model.solve_details.mip_relative_gap)

        print('Stage: Integral model optimized. Period from %d to %d' %
              (self.period_start, self.period_start + self.period_duration - 1))
        print('Solution duration: %d' % (time() - start_time))
        if self.constraint_switcher.absolute_period_balance_by_asu_n:
            for asu_id_n, var in self.vars_balance_vols_penalty.items():
                if type(asu_id_n) == tuple:
                    print('Balance penalty for asu %d, n %d = %d' % (asu_id_n[0], asu_id_n[1], var.solution_value))
        elif self.constraint_switcher.absolute_period_balance:
            for sku, var in self.vars_balance_vols_penalty.items():
                if type(sku) == int:
                    print('Balance penalty for sku %d = %d' % (sku, var.solution_value))
