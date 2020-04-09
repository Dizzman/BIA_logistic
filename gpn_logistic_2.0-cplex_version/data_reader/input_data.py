import pandas as pd
import scipy.stats
from data_reader.objects_classes import Car
from data_reader.model_parameters import ModelParameters
from integral_planning.functions import consumption_filter, day_calculation_by_shift, extract_asu_id, extract_tank_id
import math
from data_reader.time_windows_converter import convert_time_windows
import os
import config


# ===================== Extractors===================
def extract_distance(dist):
    return dist[2]


# Отдельный файл, для каждой обработки
def extract_from_to(dist):
    return int(dist[0]), int(dist[1])


def extract_start_volumes_asu_n(vol):
    return int(vol[0]), int(vol[1])


def extract_residue(vol):
    return float(vol[2])


def max_empty_section(sections, empty_sections_idx):
    filter_sections = [val for val in empty_sections_idx if val != [0]]
    sections_filtered = [sum(sections[val - 1] for val in vals) for vals in filter_sections]
    sections_filtered.append(0)
    return max(sections_filtered)


# ====================== Classes=====================
class Parameters:
    def __init__(self):
        """Business Parameters:"""
        # Operations Parameters
        self.truck_speed = ModelParameters.truck_speed  # скорость БВ
        self.petrol_load_time = ModelParameters.petrol_load_time  # Время налива БВ на НБ; Attention!!!  корректируется в depots_to_dict()
        self.docs_fill = ModelParameters.docs_fill  # время заполнения документов на АЗС
        self.first_thousand_pour = ModelParameters.first_thousand_pour  # скорость слива первой 1000
        self.thousand_pour = ModelParameters.thousand_pour  # скорость слива топлива на 1000л
        self.pump_load = ModelParameters.pump_load  # уменьшение времени слива секции за счёт использования помпы
        self.automatic_load = ModelParameters.automatic_load  # дополнительное время на автоматической АЗС
        self.mok_docs_fill = ModelParameters.mok_docs_fill  # время заполнения документов на АЗС
        self.mok_thousand_pour = ModelParameters.mok_thousand_pour  # скорость слива топлива на 1000л
        self.mok_pump_load = ModelParameters.mok_pump_load  # уменьшение времени слива секции за счёт использования помпы

        self.shift_size = 12  # Длительность смены в часах
        self.shift_start_time = 8  # Начало смены
        self.day_size = 24  # Длительность дня в часах
        self.uet_name = 'uet1'  # Название УЭТ "по умолчанию" в матрице расстояний
        self.load_time_ub = self.shift_size  # Верхнее ограничение в часах от начала смены на окончание налива

        # Risk control parameters
        # self.risk_death_volume = 0.8  # Запас НП до поставки во избежание просушек. От смены
        self.risk_tank_overload = ModelParameters.risk_tank_overload  # Занижение бака на уровень потребления
        self.fuel_reserve = ModelParameters.fuel_reserve  # резерв до просыхания АЗС помимо времени движения

        self.min_turnover = ModelParameters.min_turnover  # 1.7  # Минимальная оборачиваемость для общего парка

        "Period parameters"
        self.hidden_period = ModelParameters.hidden_period  # Весь период планирования с учетом скрытой части в днях
        self.absolute_period_start = ModelParameters.absolute_period_start  # Время начала абсолютного периода
        self.absolute_period_duration = ModelParameters.absolute_period_duration  # Длительность абсолютного периода

        """Model parameters"""
        self.ub_period_flow_balance = 1000000  # Допустимый объем нарушения поставок Потребление vs Поставки НЕ актуально
        self.truck_time_restrictions = {1: 34, 2: 35, 3: 35, 4: 35}  # Ограничения на количество выездов в смену НЕ Актуально
        self.truck_day_balance = 5  # Балансирование количества выездов внутри суток между сменами
        self.max_truck_to_asu = config.configuration['max_truck_to_asu']  # Максимальное количество БВ на одну АЗС в смену
        self.death_penalty = ModelParameters.death_penalty  # 1.0  # Вес в целевой функции для просушки АЗС
        self.truck_work_cost = ModelParameters.truck_work_cost  # 1.6  # Вес в целевой функции для времени движения
        self.balance_penalty = ModelParameters.balance_penalty  # 1  # Вес в целевой функции для нарушение баланса
        self.period_flow_balance_coef = config.configuration['period_flow_balance_coef']  # Коэффициент пополнения АЗС в течении периода
        self.balance_per_tank = ModelParameters.balance_per_tank  # 0.005  # Вес в целевой функции балансирования потребления/поставок в разрезе резервуара. Штраф за единицу нарушения.
        self.trip_costs = ModelParameters.trip_costs  # 50  # Вес в целевой функции максимального количества выездов в смену в периоде

        self.core_count = 16  # Количество потоков
        self.pool = 0

        """Integral model CPLEX parameters"""
        self.time_limit = config.configuration['time_limit']

        self.threads = 8
        self.gap_level = 0.00
        # '''Detailed planning parameters'''
        #
        # self.empty_section_weight = 50000
        # self.overloading_weight = 0.001
        # self.lack_loading = 1

        self.group_size = 80
        self.truck_capacity_part = ModelParameters.truck_capacity_part
        self.package_num = ModelParameters.package_num

        """Validation parameters"""
        self.admissible_reservoir_overflow = 1/12  # Допустимая для переполнения доля от потребления в смену

    def __getstate__(self):
        self_dict = self.__dict__.copy()
        if 'pool' in self_dict:
            del self_dict['pool']
        return self_dict


class StaticData:
    def __init__(self, path, parameters: Parameters):  # , parameters: Parameters
        self.path = path
        self.parameters = parameters
        self.distances_asu_depot = {}  # distances asu_id and depot_id
        self.distances_asu_uet = {}  # distances asu_id, depot_id and uet
        self.distributions = {}  # allowed distributions asu - asu
        self.restricts = {}  # fuel restrictions in the depot  {depot_id, sku_depot, day: volume}
        self.initial_fuel_state = {}  # initial volumes in asu tanks {asu_id,n: volume}
        self.consumption = {}  # forecast of fuel consumption {(asu_id, n, time): vol}
        self.tanks = pd.DataFrame  # tanks parameters (Pandas DataFrame)  ['asu_id', 'n', 'sku', 'capacity', 'capacity_min', 'depot_id']
        self.tank_max_vol = {}  # Максимальный полезный объем бака
        self.tank_death_vol = {}  # Мертвый остаток
        self.densities = {}  # fuel densities
        self.asu_parameters = {}  # asu parameters
        self.asu_work_time = {}  # asu work time for delivery
        self.asu_work_shift = {}  # asu work shift
        self.block_window_asu = {}  # Словарь блокировки приема на АЗС: {(asu_id, shift): [(lb, ub), (lb2, ub2)]}
        self.depot_work_time = {}  # depot work time for delivery
        self.depot_work_shift = {}  # depot work shift
        self.depot_work_decrease = {}  # Словарь занятости ворот на НБ: {(depot_id, shift): [(lb, ub), (lb2, ub2)]}
        self.depot_load_time = {}  # Словарь времен налива БВ на НБ: {depot_id: load_time}
        self.block_window_depot = {}  # Словарь блокировки приема на НБ: {(depot_id, shift): [(lb, ub), (lb2, ub2)]}
        self.asu_automatic_status = {}  # is asu automatic
        self.asu_pump = {}  # asu needs pump
        self.vehicles = {}  # set of vehicles to plan
        self.asu_vehicle_avg_volume = {}
        self.asu_vehicle_avg_section = {}  # {asu: avg_section, ...}
        self.asu_vehicle_max_volume = {}
        self.sku_vs_sku_name = {}
        self.tank_sku = {}  # {asu, tank: sku}
        self.absolute_period_consumption = {}
        self.absolute_period_consumption_by_asu_n = {}
        self.asu_depot = {}  # {asu_id: depot_id}
        self.is_asu_depot_already_reallocated = {}
        self.start_volume_corrections = {}
        self.fuel_groups = {}  # Fuel classification
        self.fuel_in_depot = {}  # Grouping of fuel in depot {depot_id, depot_sku: [normal_sku]}
        self.fuel_in_depot_inverse = {}  # Grouping of fuel in depot {depot_id, normal_sku: depot_sku}
        self.depot_capacity = {}  # Depot max_truck load number in same time
        self.asu_depot_reallocation = {}  # Перепривязка АЗС к НБ по бакам {asu_id, n, shift: depot} (Все)
        self.asu_reallocated = {}  # Словарь АЗС с измененной привязкой {shift: [asu1, asu2, ...]}

        # Справочник типов топлива (sku) из файла sku_reference.xlsx
        # self.sku_reference[1] = {'density': 0.75, 'sku_name': 'АИ-95', 'fuel_group': 'petrol'}

        self.sku_reference = {}

        # Справочник связей sku и sku_depots для нефтебаз
        # self.sku_resource[(depot_id, sku_depot_id))] = [sku_1, sku_2, ...]

        self.sku_resource = {}

        # Множество дефицитных sku на НБ
        # self.sku_deficit = {depot_id_1: [sku_1, sku_2, ...]}
        self.sku_deficit = {}

        # Данные для группировки открытий согласно типам топлива

        self.groups_for_openings_sum = {}

        # Справочная информация
        self.depot_names_dict = {}  # Названия НБ
        self.asu_address_dict = {}  # Адреса АЗС

        # Занятость БВи топливо в пути
        self.vehicles_busy = []  # Занятость БВ в разрезе смены: [(truck, shift)]
        self.volumes_to_add = {}
        self.vehicles_busy_hours = {}  # Занятость БВ от начала смены в часах {(truck, shift): (hours, location)}
        self.vehicles_cut_off_shift = {}  # Сдвиг в часах конца смены БВ {(truck, shift): hours}
        self.truck_load_after_allowed = []  # БВ, которые можно грузить под сменщика

        # Длительность рейсов
        self.trip_durations = {}
        self.far_asu = []

        """Run data reader"""
        self.read_data()  # read all data
        print('*'*40 + 'Asu work time' + '*'*40)
        print(self.asu_work_time)
        print('*' * 40 + 'Asu block time' + '*' * 40)
        print(self.block_window_asu)
        print('*' * 40 + 'Depot work time' + '*' * 40)
        print(self.depot_work_time)
        print('*' * 40 + 'Depot block time' + '*' * 40)
        print(self.block_window_depot)

        # Добавление обрезков смен для депота в блоки TODO Катя, сделать нормально
        self.extend_depot_blocks_by_shift_scrap()

    @staticmethod
    def read_sku_reference(filename):
        """Функция для чтения справочника типов топлива (sku) из файла 
        sku_reference.xlsx"""

        result = {}
        fuel_group = {}

        if os.path.isfile(filename):
            input_file = pd.read_excel(filename, sheet_name='sku_reference')
        else:
            return result

        n_records = len(input_file)

        for line_id in range(0, n_records):
            sku_id = int(input_file.at[line_id, 'sku'])
            density = 1  # float(input_file.at[line_id, 'density']) # TODO Костыль для плотности
            sku_name = input_file.at[line_id, 'sku_name']
            fuel_group_temp = input_file.at[line_id, 'fuel_group']

            temp_dict = {'sku_id': sku_id, 'density': density,
                         'sku_name': sku_name, 'fuel_group': fuel_group_temp}

            result[sku_id] = temp_dict
            fuel_group[sku_id] = fuel_group_temp

        return result, fuel_group

    @staticmethod
    def read_sku_resource(filename):
        """Функция для чтения связей sku-sku_depot из файла
        sku_reference.xlsx"""

        def get_merged_groups(lst):
            """Функция для выделения групп с общим типом топлива (sku)
            """
            res = []
            number_of_elements = len(lst)

            for el in lst:
                prel_result = el
                for itr in range(0, number_of_elements):
                    for innr in lst:
                        if (set(prel_result) & set(innr)):
                            prel_result = sorted(list(set(prel_result) | set(innr)))
                if prel_result not in res:
                    res.append(prel_result)

            return res

        def get_actual_openings(sku_num):
            """Функция для получения списка нефтебаз и привязок к группам для
            определенного sku
            """
            result = []

            n_records = len(input_file)

            for line_id in range(0, n_records):
                depot_id = int(input_file.at[line_id, 'depot_id'])
                sku = int(input_file.at[line_id, 'sku'])
                sku_depot = int(input_file.at[line_id, 'sku_depot'])

                if sku == sku_num:
                    result.append((depot_id, sku_depot))

            return result
            
        result = {}
        result_reverse = {}
        deficit_dict = {}

        if os.path.isfile(filename):
            input_file = pd.ExcelFile(filename).parse("sku_resource")  # TODO check the read
            #input_file = pd.read_excel(filename, sheet_name='sku_resource')
        else:
            return result

        for idx, line_id in input_file.iterrows():
            depot_id = int(line_id['depot_id'])
            sku = int(line_id['sku'])
            sku_depot = int(line_id['sku_depot'])
            deficit = int(line_id['deficit']) if ('deficit' in line_id and line_id['deficit']) and not math.isnan(line_id['deficit']) else 0
            # deficit = int(input_file.at[line_id, 'deficit'])

            result.setdefault((depot_id, sku_depot), []).append(sku)
            result_reverse[depot_id, sku] = sku_depot

            if deficit:
                deficit_dict.setdefault(depot_id, []).append(sku)

        fuel_pseudo_groups = []
        unique_connections = []

        number_of_groups = 0

        for key, value in result.items():
            if value not in unique_connections:
                unique_connections.append(value)

        unique_connections

        fuel_pseudo_groups = get_merged_groups(unique_connections)

        number_of_groups = len(fuel_pseudo_groups)

        fuel_pseudo_groups_dict = {}

        for num, el in enumerate(fuel_pseudo_groups):
            group_description = {}
            group_description['sku_merged'] = el
            group_description['connected_openings'] = []
            fuel_pseudo_groups_dict[num] = group_description

            for key, val in result.items():
                if len(set(el) & set(val)):
                    group_description['connected_openings'].append(key)

        # Разбиение merged групп при наличии двух и более элементов

        number_of_groups_actual = number_of_groups
        
        for i in range(0, number_of_groups):
            if len(fuel_pseudo_groups_dict[i]['sku_merged']) > 1:
                for sku_number in fuel_pseudo_groups_dict[i]['sku_merged']:
                    actual_openings = get_actual_openings(sku_number)
                    if len(actual_openings) != len(fuel_pseudo_groups_dict[i]['connected_openings']):
                        fuel_pseudo_groups_dict[number_of_groups_actual] = {}
                        fuel_pseudo_groups_dict[number_of_groups_actual]['sku_merged'] = [sku_number]
                        fuel_pseudo_groups_dict[number_of_groups_actual]['connected_openings'] = actual_openings
                        number_of_groups_actual += 1

        return result, result_reverse, fuel_pseudo_groups_dict, deficit_dict

    # Совместимость данных Consumption и Tanks
    @staticmethod
    def validation_tanks(data1, data2, data_description, keys):
        data1_upd = data1[keys].drop_duplicates()
        data2_upd = data2[keys].drop_duplicates()
        intersection = pd.merge(data1_upd, data2_upd, how='inner', on=keys)

        # print status ov validation
        print('==== Validation ' + data_description + ' ===')
        print('Set of tanks in first set = %d' % data1_upd.shape[0])
        print('Set of tanks in second set = %d' % data2_upd.shape[0])
        print('Intersection size = %d' % intersection.shape[0])

        return intersection.reset_index()

    def convert_distances_to_dict(self, pd_distances):
        distances = {}
        for idx, dist in pd_distances.iterrows():
            distances[dist['from'], dist['to']] = float(dist['distance']) / self.parameters.truck_speed
        return distances

    @staticmethod
    def convert_distributions_to_dict(pd_distances):
        distributions = {}
        for idx, dist in pd_distances.iterrows():
            # если расстояние между азс и азс
            if dist['from'] > 10000 and dist['to'] > 10000 and dist['from'] != dist['to']:
                # if 'allowed' not in dist or dist['allowed'] == 1:
                distributions.setdefault(dist['from'], []).append(dist['to'])
        return distributions

    """Convert pandas dataFrame of depot fuel restrictions into the dictionary"""

    @staticmethod
    def convert_restrictions_to_dict(pd_restrictions):
        restricts = {}
        for idx, val in pd_restrictions.iterrows():
            restricts[int(val['depot_id']), int(val['sku']), int(val['day'])] = float(
                val['volume'])  # [depot, sku, day] -> volume
        return restricts

    """The tank is overloaded at the start"""

    def initial_state_correction(self, residue, asu_id, n, capacity):
        if capacity - residue < 0:
            self.start_volume_corrections[asu_id, n] = residue - capacity
            return capacity
        else:
            return residue

    def convert_initial_state_to_dict(self, pd_start_volume, intersection_cons_start):
        initial_fuel_state = {}
        tank_sku = {}
        # for idx, vol in pd.merge(pd_start_volume[['asu_id', 'n', 'residue', 'capacity']],
        #                          intersection_cons_start[['asu_id', 'n']],
        #                          how='inner',
        #                          on=['asu_id', 'n']).iterrows():
        for idx, vol in pd_start_volume.iterrows():
            initial_fuel_state[int(vol['asu_id']), int(vol['n'])] = self.initial_state_correction(residue=float(vol['residue']),
                                                                                                  asu_id=int(vol['asu_id']),
                                                                                                  n=int(vol['n']),
                                                                                                  capacity=float(vol['capacity']))
            tank_sku[int(vol['asu_id']), int(vol['n'])] = int(vol['sku'])

        return initial_fuel_state, tank_sku

    """Modify the consumption because of overloading"""

    def consumption_correction(self):
        for asu_id, n in self.start_volume_corrections:
            current_penalty = self.start_volume_corrections[asu_id, n]
            time_inner = self.parameters.absolute_period_start
            while current_penalty > 0:
                if current_penalty - consumption_filter(self.consumption, asu_id, n, time_inner) < 0:
                    break
                else:
                    current_penalty -= consumption_filter(self.consumption, asu_id, n, time_inner)
                    self.consumption[asu_id, n, time_inner] = 0
                    time_inner += 1
                if time_inner >= self.parameters.absolute_period_start + self.parameters.absolute_period_duration:
                    break

    def convert_consumption_to_dict(self, pd_consumption, intersection_cons_start):
        consumption = {}
        merge = pd.merge(pd_consumption[['asu_id', 'n', 'day', 'time', 'consumption']],
                         intersection_cons_start[['asu_id', 'n']],
                         how='inner',
                         on=['asu_id', 'n'])
        merge_selected = merge[merge['day'].isin([i for i in range(1, self.parameters.hidden_period + 1)])]
        for idx, vol in merge_selected[['asu_id', 'n', 'time', 'consumption']].iterrows():
            consumption[int(vol['asu_id']), int(vol['n']), int(vol['time'])] = float(vol['consumption'])

        return consumption

    def treat_tanks(self, pd_asu, pd_start_volumes):
        # tanks_asu = pd.merge(pd_tanks[['asu_id', 'capacity', 'capacity_min', 'n']], pd_asu[['asu_id', 'depot_id']],
        #                      how='left', on=['asu_id'])
        tanks_asu_consumption = pd.merge(pd_start_volumes[['asu_id', 'n', 'sku', 'capacity', 'capacity_min']],
                                         pd_asu[['asu_id', 'depot_id']],
                                         how='left', on=['asu_id'])

        tank_max_vol = {}
        tank_death_vol = {}
        for idx, row in tanks_asu_consumption.iterrows():
            tank_max_vol[int(row['asu_id']), int(row['n'])] = float(row['capacity'])
            if self.sku_vs_sku_name[int(row['sku'])] != 'G100':  # КОСТЫЛЬ!!!
                tank_death_vol[int(row['asu_id']), int(row['n'])] = float(row['capacity_min'])
            else:
                tank_death_vol[int(row['asu_id']), int(row['n'])] = float(row['capacity_min'])
        return tanks_asu_consumption, tank_max_vol, tank_death_vol

    @staticmethod
    def convert_densities_to_dict(pd_densities):
        densities = {}
        for idx, val in pd_densities.iterrows():
            densities[int(val['sku'])] = float(val['density'])  # sku -> density

        return densities

    def time_normalization(self, time):
        if time >= self.parameters.shift_start_time:
            return time - self.parameters.shift_start_time
        else:
            return 24 + time - self.parameters.shift_start_time

    def depot_work_shift_calc(self, pd_depot):
        """Предполагается, если даны 2 временных интервала, то АЗС принимает в 1 и 2 смену"""
        works_shifts = {}
        for idx, depot in pd_depot[['depot_id', 'depot_time_window']].iterrows():
            # Разделение на 2 интервала
            time_int = list(map(str, depot['depot_time_window'].split(';')))
            # Если количество интервалов больше 2
            if len(time_int) == 2:
                # Первый интервал
                works_shifts[int(depot['depot_id'])] = {1: 1, 2: 1}  # АЗС работает в обе смены
            else:
                interval = list(map(str, time_int[0].split('-')))

                lint = self.time_normalization(list(map(int, interval[0].split(':')))[0])
                rint = self.time_normalization(list(map(int, interval[1].split(':')))[0])
                if lint < rint <= 12:
                    works_shifts[int(depot['depot_id'])] = {1: 1, 2: 0}
                elif 12 <= lint < rint:
                    works_shifts[int(depot['depot_id'])] = {1: 0, 2: 1}
                elif (rint < lint <= 12 or 12 <= rint < lint) and not (rint == 23 - self.parameters.shift_start_time and
                                                                       lint == 24 - self.parameters.shift_start_time):
                    # Невозможный вариант, так как образует рванный интервал в одной из смен
                    works_shifts[int(depot['depot_id'])] = {1: 0, 2: 0}
                else:
                    works_shifts[int(depot['depot_id'])] = {1: 1, 2: 1}

        return works_shifts

    def convert_work_time_to_dict(self, pd_asu):
        """Предполагается, если даны 2 временных интервала, то АЗС принимает в 1 и 2 смену"""
        # TODO Обработка смен, разрыв смены на три интервала
        works_shifts = {}
        work_windows = {}
        for idx, asu in pd_asu[['asu_id', 'asu_time_windows']].iterrows():
            # Разделение на 2 интервала
            time_int = list(map(str, asu['asu_time_windows'].split(';')))
            # Если количество интервалов больше 2
            if len(time_int) == 2:
                # Первый интервал
                interval = list(map(str, time_int[0].split('-')))
                lint = self.time_normalization(list(map(int, interval[0].split(':')))[0]) + list(map(int, interval[0].split(':')))[
                    1] / 60  # Left side
                rint = self.time_normalization(list(map(int, interval[1].split(':')))[0]) + list(map(int, interval[1].split(':')))[
                    1] / 60  # Right side
                res = {1: (lint, rint)}
                interval2 = list(map(str, time_int[1].split('-')))
                lint2 = self.time_normalization(list(map(int, interval2[0].split(':')))[0]) + list(map(int, interval2[0].split(':')))[
                    1] / 60
                rint2 = self.time_normalization(list(map(int, interval2[1].split(':')))[0]) + list(map(int, interval2[1].split(':')))[
                    1] / 60
                res[2] = (lint2 - self.parameters.shift_size, rint2 - self.parameters.shift_size)
                work_windows[int(asu['asu_id'])] = res
                works_shifts[int(asu['asu_id'])] = {1: 1, 2: 1}  # АЗС работает в обе смены
            else:
                interval = list(map(str, time_int[0].split('-')))

                lint = self.time_normalization(list(map(int, interval[0].split(':')))[0]) + list(map(int, interval[0].split(':')))[1] / 60
                rint = self.time_normalization(list(map(int, interval[1].split(':')))[0]) + list(map(int, interval[1].split(':')))[1] / 60

                res = {1: (0, 0), 2: (0, 0)}
                if lint < rint <= self.parameters.shift_size:
                    works_shifts[int(asu['asu_id'])] = {1: 1, 2: 0}
                    res[1] = (lint, rint)
                elif self.parameters.shift_size <= lint < rint:
                    works_shifts[int(asu['asu_id'])] = {1: 0, 2: 1}
                    res[2] = (lint - self.parameters.shift_size, rint - self.parameters.shift_size)
                elif rint < lint:
                    if lint - rint <= 1:
                        res[1] = (0, 12)
                        res[2] = (0, 12)
                        works_shifts[int(asu['asu_id'])] = {1: 1, 2: 1}
                    else:
                        # Невозможный вариант, так как образует рванный интервал в одной из смен
                        works_shifts[int(asu['asu_id'])] = {1: 0, 2: 0}
                elif lint <= self.parameters.shift_start_time <= rint:
                    works_shifts[int(asu['asu_id'])] = {1: 1, 2: 1}
                    res[1] = (lint, 12)
                    res[2] = (0, rint - self.parameters.shift_start_time)
                else:
                    # TODO нужны договоренности
                    works_shifts[int(asu['asu_id'])] = {1: 1, 2: 1}
                    if lint < rint:
                        res[1] = (lint, 12)
                        res[2] = (0, rint)
                    else:
                        res[1] = (0, rint)
                        res[2] = (lint - 12, 12)
                work_windows[int(asu['asu_id'])] = res
        return works_shifts, work_windows

    @staticmethod
    def convert_asu_parameters(pd_asu):
        # TODO множество получаемых баков шире чем initial_states
        asu_parameters = {}
        asu_automatic = {}
        asu_pump = {}
        asu_address = {}
        for idx, val in pd_asu.iterrows():
            asu_id = int(val['asu_id'])
            asu_parameters[asu_id] = [int(val['drain_side_left']),
                                      int(val['drain_side_right']),
                                      int(val['non_bulky'])]  # asu_id -> drain_side_left, drain_side_right, non_bulky
            asu_automatic[asu_id] = int(val['is_automatic'])
            if 'is_pump' in val:
                asu_pump[asu_id] = int(val['is_pump'])
            else:
                asu_pump[asu_id] = 0
            asu_address[asu_id] = val['asu_address']
        return asu_parameters, asu_automatic, asu_pump, asu_address

    @staticmethod
    def allowed_asu_treat(input_data_row):
        if type(input_data_row) == int:
            return [input_data_row]
        elif type(input_data_row) == float:
            return []
        else:
            return list(map(int, input_data_row.split(';')))

    def treat_vehicles(self, pd_vehicles):
        trucks = {}  # index
        load_after_list = []
        for idx, car_parameters in pd_vehicles.iterrows():
            section_volumes = list(map(float, car_parameters['sections'].split(';')))
            capacity = car_parameters['capacity']
            index = car_parameters['idx']
            np_petrol = list(map(int, str(car_parameters['np_petrol']).split(';')))
            np_diesel = list(map(int, str(car_parameters['np_diesel']).split(';')))
            np_mix = list(map(int, str(car_parameters['np_mix']).split(';')))
            np_petrol.sort()
            np_diesel.sort()
            np_mix.sort()
            # Убран случай с только дизелем при получении минимальной машины [np_petrol, np_mix, np_diesel]
            max_removed_section = max_empty_section(section_volumes, [np_petrol, np_mix])
            # max_removed_section = max([float(section_volumes[car_parameters['np_petrol'] - 1]),
            #                             float(section_volumes[car_parameters['np_diesel'] - 1]),
            #                             float(section_volumes[car_parameters['np_mix'] - 1])])
            volume_min = capacity - max_removed_section
            section_volumes = section_volumes[::-1]  # Reverse sections
            uet = car_parameters['uet'] if 'uet' in car_parameters and car_parameters['uet'] and \
                                           (isinstance(car_parameters['uet'], str) or not math.isnan(car_parameters['uet'])) \
                else self.parameters.uet_name
            asu_allowed = self.allowed_asu_treat(car_parameters['asu_allowed']) if 'asu_allowed' in car_parameters and car_parameters[
                'asu_allowed'] else []
            depot_allowed = [] if 'depot_allowed' not in car_parameters else self.allowed_asu_treat(car_parameters['depot_allowed'])
            if 'shift_size' in car_parameters and math.isnan(car_parameters['shift_size']):
                print("<FOR_USER>\nДля БВ %d (%s) не указана длины смены!\n</FOR_USER>" % (index, car_parameters['car_number']))
            shift_size = car_parameters['shift_size'] if 'shift_size' in car_parameters else self.parameters.shift_size
            load_after = car_parameters['load_after'] if 'load_after' in car_parameters \
                                                         and not math.isnan(car_parameters['load_after']) \
                else car_parameters['is_owner']
            section_fuel = None if 'section_fuel' not in car_parameters else car_parameters['section_fuel'].split(';')
            if section_fuel is not None and \
                (any(map(lambda x: x not in ('petrol', 'diesel', 'none'), section_fuel)) or
                 (len(section_fuel) != len(section_volumes))):
                print("<FOR_USER>\nДля БВ %d (%s) не верно указаны НП секций!\n</FOR_USER>" % (index, car_parameters['car_number']))
            if load_after == 1:
                load_after_list.append(index)

            cost_per_hour = car_parameters['cost_per_hour'] if 'cost_per_hour' in car_parameters \
                                                               and not math.isnan(car_parameters['cost_per_hour']) else 0

            "Скользкая ошибка"
            if ('trailer_license' not in car_parameters) or (not car_parameters['trailer_license']):
                print("<FOR_USER>\nНет лицензии прицепа для БВ %d\n</FOR_USER>" % index)
                print(car_parameters['car_number'])
                exit(1)

            trucks[index] = Car(number=index,
                                volume_max=capacity,
                                volume_min=volume_min,
                                sections_volumes=section_volumes,
                                drain_side_left=car_parameters['drain_side_left'],
                                drain_side_right=car_parameters['drain_side_right'],
                                is_bulky=car_parameters['is_bulky'],
                                sec_empty={'np_petrol': np_petrol,
                                           'np_diesel': np_diesel,
                                           'np_mix': np_mix},
                                vehicle_number=car_parameters['car_number'],
                                trailer_license=car_parameters['trailer_license'],
                                is_own=car_parameters['is_owner'],
                                uet=uet,
                                asu_allowed=asu_allowed,
                                depot_allowed=depot_allowed,
                                shift_size=shift_size,
                                load_after=load_after,
                                section_fuel=section_fuel,
                                cost_per_hour=cost_per_hour)

        return trucks, load_after_list

    @staticmethod
    def asu_vehicles_connection(pd_asu, vehicles):
        # TODO сгруппировать АЗС по сторонам слива и размеру, сократить количество пробегов в цикле.
        asu_vehicle_avg_volume = {}
        asu_vehicle_avg_section = {}
        asu_vehicle_max_volume = {}

        for idx, asu in pd_asu[['asu_id', 'drain_side_left', 'drain_side_right', 'non_bulky', 'is_automatic']].iterrows():
            set_of_vehicles = list(filter(lambda x: (vehicles[x].drain_side_left == asu['drain_side_left'] or
                                                     vehicles[x].drain_side_right == asu['drain_side_right']) and
                                                    vehicles[x].is_bulky <= 1 - asu['non_bulky'] and
                                                    vehicles[x].is_own >= asu['is_automatic'] and
                                                    (int(asu['asu_id']) in vehicles[x].asu_allowed or not vehicles[x].asu_allowed),
                                          vehicles.keys()))
            if not set_of_vehicles:
                print('No Car for asu %d' % asu['asu_id'])
            set_volume = []
            set_section = []
            set_max_volume = [0]
            for trailer in set_of_vehicles:
                set_volume.append(vehicles[trailer].volume_min)
                set_section.extend(vehicles[trailer].sections_volumes)
                set_max_volume.append(vehicles[trailer].volume_max)

            asu_vehicle_avg_volume[int(asu['asu_id'])] = scipy.stats.mstats.mquantiles(set_volume, prob=[0.75, 0.8, 0.1])[0]
            asu_vehicle_avg_section[int(asu['asu_id'])] = scipy.stats.mstats.mquantiles(set_section, prob=[0.01, 0.8, 0.1])[0]
            asu_vehicle_max_volume[int(asu['asu_id'])] = max(set_max_volume)

        return asu_vehicle_avg_volume, asu_vehicle_avg_section, asu_vehicle_max_volume

    @staticmethod
    def sku_set(pd_start_volume, pd_densities):
        sku_start_volumes = pd_start_volume[['sku']].drop_duplicates()
        sku_densities = pd_densities[['sku', 'sku_name']].drop_duplicates()
        sku_intersection = pd.merge(sku_start_volumes, sku_densities, how='inner', on=['sku'])
        sku_dict = {}

        for idx, sku in sku_intersection.iterrows():
            sku_dict[int(sku['sku'])] = sku['sku_name']
        return sku_dict

    def sku_consumption_sum(self, pd_consumption, pd_start_volume):
        merge = pd.merge(pd_consumption[['asu_id', 'n', 'sku', 'day', 'time', 'consumption']],
                         pd_start_volume[['asu_id', 'n']],
                         how='inner',
                         on=['asu_id', 'n'])
        consumption_in_period = merge[(merge['time'] >= self.parameters.absolute_period_start) &
                                      (merge['time'] < self.parameters.absolute_period_start + self.parameters.absolute_period_duration)].groupby(
            ['sku'], as_index=False).sum()

        consumption_in_period_by_asu_n = merge[(merge['time'] >= self.parameters.absolute_period_start) &
                                               (merge['time'] < self.parameters.absolute_period_start +
                                                self.parameters.absolute_period_duration)].groupby(
            ['asu_id', 'n'], as_index=False).sum()

        print('==== Consumption by sku for the period ====')
        print(consumption_in_period[['sku', 'consumption']])
        return consumption_in_period, consumption_in_period_by_asu_n

    @staticmethod
    def asu_depot_to_dict(pd_asu): # DS чтение из gas_station
        asu_depot = {}
        for idx, val in pd_asu.iterrows():
            asu_depot[int(val['asu_id'])] = float(val['depot_id'])  # asu -> depot #DS почему тут float?
        return asu_depot

    @staticmethod
    def fuel_group_to_dict(pd_densities):
        fuel_groups = {}
        fuel_depots = {}
        fuel_depots_inverse = {}
        for idx, val in pd_densities.iterrows():
            fuel_groups[int(val['sku'])] = str(val['fuel_group'])  # sku -> density
            fuel_depots_inverse[int(val['sku'])] = int(val['depot_opens'])
            if int(val['depot_opens']) in fuel_depots:
                fuel_depots[int(val['depot_opens'])].append(int(val['sku']))
            else:
                fuel_depots[int(val['depot_opens'])] = [int(val['sku'])]

        return fuel_groups, fuel_depots, fuel_depots_inverse

    def depots_to_dict(self, pd_depots):
        depots = {}
        depot_names = {}
        depot_load_time = {}
        # depots_work_shifts = self.depot_work_shift_calc(pd_depots)
        for idx, depot in pd_depots.iterrows():
            depots[int(depot['depot_id'])] = int(depot['depot_traffic_capacity'])
            depot_names[int(depot['depot_id'])] = depot['depot_name']

            depot_load_time[int(depot['depot_id'])] = float(depot['load_time']) if 'load_time' in depot and depot['load_time'] else \
                self.parameters.petrol_load_time

        self.parameters.petrol_load_time = sum(depot_load_time.values()) / len(list(depot_load_time.values()))

        return depots, depot_names, depot_load_time

    @staticmethod
    def vehicles_busy_to_dict(pd_vehicles_busy):
        """Returns the list of vehicle busy states:
            [(truck, shift)] """

        result_dict = []
        for idx, row in pd_vehicles_busy.iterrows():
            result_dict.append((int(row['idx']), int(row['shift'])))
        return result_dict

    @staticmethod
    def vehicles_busy_hours_to_dict(pd_vehicles_busy_hours):
        """Returns the dict of vehicle busy hours:
            {truck, shift: (hours, location)} """

        def is_number(s):
            try:
                float(s)
                return True
            except ValueError:
                return False

        result_dict = {}
        for idx, row in pd_vehicles_busy_hours.iterrows():
            if is_number(str(row['location'])):
                if math.isnan(row['location']):
                    val = None
                else:
                    val = int(row['location'])
            else:
                val = str(row['location'])
            result_dict[int(row['idx']), int(row['shift'])] = (float(row['hours']), val)  # TODO Парсинг строки

        return result_dict

    @staticmethod
    def vehicles_cut_off_shift_to_dict(pd_vehicles_cut_off_shift):
        """Returns the dict of vehicle busy hours on end of shift:
            {truck, shift: hours} """

        result_dict = {}
        for idx, row in pd_vehicles_cut_off_shift.iterrows():
            result_dict[int(row['idx']), int(row['shift'])] = float(row['hours'])

        return result_dict

    @staticmethod
    def volumes_add_to_dict(pd_volumes_add):
        """Returns the dict of volumes in the way or loads in previous shift:
            {truck, shift: status_busy} """

        result_dict = {}
        for idx, row in pd_volumes_add.iterrows():
            key = int(row['asu_id']), int(row['n']), int(row['time'])
            if key not in result_dict:
                result_dict[key] = 0
            result_dict[key] += float(
                row['volume'])  # TODO Изменено 21.03 Теперь в файле volumes_add могут быть несколько записей с одинаковым ключом
        return result_dict

    def block_window_to_dict(self, pd_block_window, existed_dict):
        unwork_time_dict = {}
        for idx, row in pd_block_window.iterrows():
            asu_id = int(row['asu_id'])
            shift = int(row['time'])
            time_convert_lb = list(map(int, str(row['left_bound']).split(':')))
            lb = self.time_normalization(time_convert_lb[0] + time_convert_lb[1] / 60)
            time_convert_ub = list(map(int, str(row['right_bound']).split(':')))
            ub = self.time_normalization(time_convert_ub[0] + time_convert_ub[1] / 60)

            if (asu_id, shift) in unwork_time_dict:
                unwork_time_dict[asu_id, shift] = [(0, self.parameters.shift_size)]
            else:
                shift_correction = 0 if shift % 2 != 0 else 12
                unwork_time_dict[asu_id, shift] = [(lb - shift_correction, ub - shift_correction)]

        block_window_filter(unwork_time_dict, self.asu_work_time)

        for key, val in unwork_time_dict.items():
            existed_dict.setdefault(key, []).extend(val)

        # return unwork_time_dict

    def trip_duration(self, asu_id, truck=None):
        """Route rough duration:
            - Drive time from uet to nb
            - Truck load time
            - Drive time from nb to asu1
            - Truck unload time
            - Drive time from asu1 to uet"""
        depot_set = set([to_ for (from_, to_) in self.distances_asu_uet if isinstance(to_, int) and to_ <= 10000])
        distance = 0
        depot = self.asu_depot[asu_id]
        # TODO Функция использует старые привязки!!!
        '''Drive time from uet to depot'''
        if truck:
            distance += get_distance(self.vehicles[truck].uet, depot, self.distances_asu_uet)
        else:
            avg_distance_from_uet = 0 #sum(sum(get_distance(self.vehicles[truck].uet, depot_, self.distances_asu_uet)
                                      #  for truck in self.vehicles) for depot_ in depot_set) / (len(self.vehicles) * len(depot_set))
            count = 0
            for truck in self.vehicles:
                for depot_ in depot_set:
                    if (self.vehicles[truck].uet, depot_) in self.distances_asu_uet:
                        avg_distance_from_uet += get_distance(self.vehicles[truck].uet, depot_, self.distances_asu_uet)
                        count += 1

            distance += avg_distance_from_uet / (count + 0.001)

        '''Truck load'''
        distance += self.parameters.petrol_load_time
        '''Drive time from depot to asu'''
        avg_distance_to_asu = 0
        count = 0
        for depot_ in depot_set:
            if (depot_, asu_id) in self.distances_asu_uet:
                avg_distance_to_asu += get_distance(depot_, asu_id, self.distances_asu_uet)
                count += 1

        distance += avg_distance_to_asu / (count + 0.001)
        # distance += sum(get_distance(depot_, asu_id, self.distances_asu_depot) for depot_ in depot_set) / len(depot_set)
        '''Truck unload time'''
        distance += unload_time_calculation(asu_id, self.parameters, self)
        '''Drive time from second asu to uet'''
        if truck:
            distance += get_distance(asu_id, self.vehicles[truck].uet, self.distances_asu_uet)
        else:
            avg_distance_to_uet = sum(get_distance(asu_id, self.vehicles[truck].uet, self.distances_asu_uet)
                                      for truck in self.vehicles) / len(self.vehicles)
            distance += avg_distance_to_uet

        return distance

    @staticmethod
    def asu_work_time_parsing(pd_asu, obj_name, obj_windows):
        works_shifts = {}
        work_windows = {}
        block_window = {}

        for idx, asu in pd_asu[[obj_name, obj_windows]].iterrows():
            day, night = convert_time_windows(asu[obj_windows])
            # Метка работы АЗС в смену
            works_shifts[int(asu[obj_name])] = {1: 1 if day['window'] != (0, 0) else 0,
                                                2: 1 if night['window'] != (0, 0) else 0}
            work_windows[int(asu[obj_name])] = {1: day['window'],
                                                2: night['window']}
            # {(asu_id, shift): [(lb, ub), (lb2, ub2)]} TODO количество смен планирования + 1
            for shift in range(1, 5):
                if shift % 2 == 1 and day['blocks']:
                    block_window.setdefault((int(asu[obj_name]), shift), []).extend(day['blocks'])
                elif shift % 2 == 0 and night['blocks']:
                    block_window.setdefault((int(asu[obj_name]), shift), []).extend(night['blocks'])

        return works_shifts, work_windows, block_window

    def redefine_asu_work_shifts(self):
        # Смена АЗС длительностью не более 1 часа, смежная со следующей, переносится на следующую.
        check_shift = lambda x: x[0] >= (self.parameters.shift_size - 1) and x[1] <= self.parameters.shift_size
        for asu, shifts in self.asu_work_time.items():
            check_result = {shift: check_shift(v) for shift, v in shifts.items()}
            for shift, check in check_result.items():
                if check:
                    lb, ub = self.asu_work_time[asu][shift]
                    self.asu_work_time[asu][shift] = (0.0, 0.0)
                    self.asu_work_shift[asu][shift] = 0

                    next_shift = 3 - shift
                    if self.asu_work_shift[asu][next_shift]:
                        next_lb, next_ub = self.asu_work_time[asu][next_shift]
                        self.asu_work_time[asu][next_shift] = (lb - self.parameters.shift_size, next_ub)
                        if next_lb > ub - self.parameters.shift_size:
                            block = (ub - self.parameters.shift_size, next_lb)
                            for day in range(self.parameters.absolute_period_duration // 2 + 1):
                                self.block_window_asu.setdefault((asu, next_shift + day * 2), []).append(block)
                        for block_lb, block_up in self.block_window_asu.get((asu, shift), []):
                            if block_up > lb:
                                block = (block_lb - self.parameters.shift_size, block_up - self.parameters.shift_size)
                                for day in range(self.parameters.absolute_period_duration // 2 + 1):
                                    self.block_window_asu.setdefault((asu, next_shift + day * 2), []).append(block)

    def clear_short_asu_work_shifts(self):
        # АЗС работает, если она принимает более 6 часов в смену.
        for asu, shifts in self.asu_work_time.items():
            for shift, (lb, ub) in shifts.items():
                if 0 < ub - lb < 6:
                    self.asu_work_time[asu][shift] = (0.0, 0.0)
                    self.asu_work_shift[asu][shift] = 0

    @staticmethod
    def depot_queue_parsing(pd_depot_queue):
        depot_work_decrease = {}

        for idx, row in pd_depot_queue.iterrows():
            depot = int(row['depot_id'])
            time = int(row['time'])
            shift = 1 - time % 2

            lb = row['left_bound']
            ub = row['right_bound']
            block = convert_time_windows('-'.join((lb, ub)))[shift]['window']

            depot_work_decrease.setdefault((depot, time), []).append(block)
        return depot_work_decrease

    def check_depot_queue_capacity(self):
        for (depot, time), intervals in self.depot_work_decrease.items():
            for interval in intervals:
                count = 0
                for another_interval in intervals:
                    if another_interval[0] <= interval[0] < another_interval[1]:
                        count += 1
                if count > self.depot_capacity[depot]:
                    print('В момент %0.2f смены %d превышено количество занятых ворот на НБ %d' %
                          (interval[0], time, depot))
                    exit()

    def erase_depot_queue_capacity(self):
        for (depot, time), intervals in self.depot_work_decrease.items():
            intervals.sort()

            accepted_intervals = []
            temp_queue = []

            def check(i):
                lb, ub = i
                count = 0
                for t in temp_queue + [i]:
                    t_lb, t_ub = t
                    if t_lb <= lb:
                        count += 1
                    if t_ub <= lb:
                        count -= 1
                return count <= self.depot_capacity[depot]

            while intervals:
                i = intervals.pop(0)
                for t_i in temp_queue.copy():
                    if t_i[1] <= i[0]:
                        accepted_intervals.append(t_i)
                        temp_queue.remove(t_i)
                    elif t_i[0] > i[0]:
                        intervals.append(t_i)
                        temp_queue.remove(t_i)
                intervals.sort()

                while not check(i):
                    lb, ub = i
                    new_lb = min(temp_queue + [i], key=lambda x: x[1])[1]
                    if new_lb >= ub:
                        i = tuple()
                        break
                    i = (new_lb, ub)
                if i:
                    temp_queue.append(i)

            accepted_intervals.extend(temp_queue)
            self.depot_work_decrease[(depot, time)] = accepted_intervals

    def extend_depot_blocks_by_shift_scrap(self):
        for depot, shifts in self.depot_work_time.items():
            for shift, (window_begin, window_end) in shifts.items():
                if window_begin != 0:
                    for sh in range(shift, 5, 2):
                        self.block_window_depot.setdefault((depot, sh), []).append((0, window_begin))
                if window_end != 12:
                    for sh in range(shift, 5, 2):
                        self.block_window_depot.setdefault((depot, sh), []).append((window_end, 12))

    def _read_xlsx(self):
        # idx, depot_id, depot_name, depot_address, lon, lat, depot_time_window, depot_traffic_capacity, max_weight
        pd_depots = pd.ExcelFile(self.path + "/depots.xlsx").parse('depots')  # Инфо НБ
        # idx, asu_id, lon, lat, asu_address, asu_time_windows, depot_id, drain_side_left, drain_side_right, non_bulky
        pd_asu = pd.ExcelFile(self.path + "/gas_stations.xlsx").parse('asu')  # Инфо АЗС
        # idx, asu_id, capacity_max, capacity, capacity_min, drain_side_left, drain_side_right, n, sku, non_bulky
        pd_tanks = pd.ExcelFile(self.path + "/gas_tanks.xlsx").parse('tanks')  # Инфо Баки
        # idx, is_owner, trailer_license, capacity, sections, drain_side_left, drain_side_right, is_bulky, np_petrol,
        # np_diesel, np_mix
        pd_vehicles = pd.ExcelFile(self.path + "/vehicles.xlsx").parse('vehicles')  # Инфо ПП
        # idx, sku, density, sku_name
        pd_densities = pd.ExcelFile(self.path + "/densities.xlsx").parse('densities')  # Инфо Плотности
        # asu_id, n, sku, sku_name, residue
        pd_start_volume = pd.ExcelFile(self.path + "/start_volume.xlsx").parse('start_volume')  # Инфо остатки
        # asu_id, n, sku, sku name, day, time, consumption
        pd_consumption = pd.ExcelFile(self.path + "/consumption.xlsx").parse('consumption')  # Инфо Потребление
        # from, to, distance_km
        pd_set_distances = pd.ExcelFile(self.path + "/data_distances.xlsx")  # Инфо Расстояния
        pd_dist_asu_depot = pd_set_distances.parse('asu_depots')  # Инфо Расстояния АЗС-НБ
        pd_dist_uet = pd_set_distances.parse('uet')  # Инфо Расстояния УЭТ
        # idx, depot_id, sku, day, volume
        pd_restrictions = pd.ExcelFile(self.path + "/flow_restrictions.xlsx").parse('restrict')  # Инфо Открытия НБ
        # idx, shift
        pd_vehicles_busy = pd.ExcelFile(self.path + "/vehicles_busy.xlsx").parse('vehicles_busy')
        pd_vehicles_busy_hours = pd.ExcelFile(self.path + "/vehicles_busy.xlsx").parse('vehicles_busy_time')
        if 'vehicles_cutted_off_time' in pd.ExcelFile(self.path + "/vehicles_busy.xlsx").sheet_names:
            pd_vehicles_cut_off_shift = pd.ExcelFile(self.path + "/vehicles_busy.xlsx").parse('vehicles_cutted_off_time')
        else:
            pd_vehicles_cut_off_shift = pd.DataFrame()
        # asu_id, n, shift, volume
        pd_volumes_add = pd.ExcelFile(self.path + "/volumes_add.xlsx").parse('volumes_add')
        pd_block_window = pd.ExcelFile(self.path + "/volumes_add.xlsx").parse('block_window')
        if os.path.isfile(self.path + "/depot_queue.xlsx"):
            pd_depot_queue = pd.ExcelFile(self.path + "/depot_queue.xlsx").parse('queue_time')
        else:
            pd_depot_queue = pd.DataFrame()
        return pd_depots, pd_asu, pd_tanks, pd_vehicles, pd_densities, pd_start_volume, pd_consumption, \
               pd_set_distances, pd_dist_asu_depot, pd_dist_uet, pd_restrictions, pd_vehicles_busy, pd_volumes_add, \
               pd_vehicles_busy_hours, pd_vehicles_cut_off_shift, pd_block_window, pd_depot_queue

    """Initialization of input data:
        - Distances (asu, depot, uet
        - Depots
        - Tanks
        - Consumption with corrections
        - Initial states with corrections
        - Densities
        - Vehicles"""

    def read_data(self):
        pd_depots, \
        pd_asu, \
        pd_tanks, \
        pd_vehicles, \
        pd_densities, \
        pd_start_volume, \
        pd_consumption, \
        pd_set_distances, \
        pd_dist_asu_depot, \
        pd_dist_uet, \
        pd_restrictions, \
        pd_vehicles_busy, \
        pd_volumes_add, \
        pd_vehicles_busy_hours, \
        pd_vehicles_cut_off_shift, \
        pd_block_window, \
        pd_depot_queue = self._read_xlsx()

        # =================Validation=============
        # intersection_tanks_cons = self.validation_tanks(pd_consumption,
        #                                                 pd_tanks,
        #                                                 'Consumption and Tanks',
        #                                                 ['asu_id', 'n'])
        # intersection_tanks_start = self.validation_tanks(pd_tanks, pd_start_volume,
        #                                                  'Start Volumes and Tanks',
        #                                                  ['asu_id', 'n'])
        intersection_cons_start = self.validation_tanks(pd_consumption, pd_start_volume,
                                                        'Start Volumes and Consumption',
                                                        ['asu_id', 'n'])

        pd_asu = pd.merge(intersection_cons_start[['asu_id']].drop_duplicates(), pd_asu, how='left', on=['asu_id'])  # TODO Need test

        # Чтение обновленных файлов справочника sku и связей с с depot_sku

        self.sku_reference, self.fuel_groups = self.read_sku_reference(self.path + "/sku_reference.xlsx")
        self.fuel_in_depot, self.fuel_in_depot_inverse, self.groups_for_openings_sum, self.sku_deficit = self.read_sku_resource(self.path + "/sku_reference.xlsx")
        # self.sku_resource = self.read_sku_resource(self.path + "/sku_reference.xlsx")

        # =================Distances==============
        self.distances_asu_depot = self.convert_distances_to_dict(pd_dist_asu_depot)  # (from, to) -> distance_hours
        self.distances_asu_uet = self.convert_distances_to_dict(pd_dist_uet)  # (from, to) -> distance_hours
        self.distributions = self.convert_distributions_to_dict(pd_dist_asu_depot)  # from -> [to]

        # =================Flow Restrictions==============
        '''Если нет открытий на день, то ограничения по открытиям нет'''
        self.restricts = self.convert_restrictions_to_dict(pd_restrictions)

        # =================Initial State==============
        '''Запускается раньше convert_consumption_to_dict чтобы устранять баги в данных'''
        self.initial_fuel_state, self.tank_sku = self.convert_initial_state_to_dict(pd_start_volume, intersection_cons_start)

        # =================Consumption==============
        self.consumption = self.convert_consumption_to_dict(pd_consumption, intersection_cons_start)
        self.consumption_correction()  # Data mistakes corrections

        # =================SKU==============
        self.sku_vs_sku_name = self.sku_set(pd_start_volume, pd_densities)

        # =================Tanks==============
        '''Возвращает Pandas.DataFrame '''
        self.tanks, self.tank_max_vol, self.tank_death_vol = self.treat_tanks(pd_asu, pd_start_volume)

        # =================Densities==============
        self.densities = self.convert_densities_to_dict(pd_densities)

        # =================Asu parameters==============
        self.asu_parameters, self.asu_automatic_status, self.asu_pump, self.asu_address_dict = self.convert_asu_parameters(pd_asu)

        # =================Asu work time==============
        self.asu_work_shift, self.asu_work_time, self.block_window_asu = self.asu_work_time_parsing(pd_asu, 'asu_id', 'asu_time_windows')
        self.clear_short_asu_work_shifts()

        # ==================Block window===========
        self.block_window_to_dict(pd_block_window, self.block_window_asu)  # TODO проверить пересечения с блокировками из asu_work_time_parsing
            #self.convert_work_time_to_dict(pd_asu)

        # =================Depot work time==============
        self.depot_work_shift, self.depot_work_time, self.block_window_depot = self.asu_work_time_parsing(pd_depots, 'depot_id', 'depot_time_window')

        # =================Vehicles==============
        self.vehicles, self.truck_load_after_allowed = self.treat_vehicles(pd_vehicles)
        print('Number of vehicles = %d' % len(self.vehicles))
        print('*'*50 + ' Load after allowed ' + '*'*50)
        print(self.truck_load_after_allowed)

        # =================Asu - Vehicles connections==============
        self.asu_vehicle_avg_volume, self.asu_vehicle_avg_section, self.asu_vehicle_max_volume = \
            self.asu_vehicles_connection(pd_asu, self.vehicles)

        # =================Period consumption==============
        self.absolute_period_consumption, self.absolute_period_consumption_by_asu_n = self.sku_consumption_sum(pd_consumption,
                                                                                                               pd_start_volume)

        # =================SKU==============
        self.asu_depot = self.asu_depot_to_dict(pd_asu)

        # # =================Fuel groups==============
        # self.fuel_groups, self.fuel_in_depot, self.fuel_in_depot_inverse = self.fuel_group_to_dict(pd_densities)

        # ==================Depot capacities===========
        self.depot_capacity, self.depot_names_dict, self.depot_load_time = self.depots_to_dict(pd_depots)

        # =================Depot queue decrease==============
        self.depot_work_decrease = self.depot_queue_parsing(pd_depot_queue)
        self.erase_depot_queue_capacity()

        # # ==================Depot-Asu reallocation===========
        # self.asu_depot_reallocation, self.asu_reallocated = self.depot_asu_reallocation_in_period()
        # print('==== Asu Reallocated ====')
        # print(self.asu_reallocated)

        # ==================Vehicles busy===========
        self.vehicles_busy = self.vehicles_busy_to_dict(pd_vehicles_busy)
        self.vehicles_busy_hours = self.vehicles_busy_hours_to_dict(pd_vehicles_busy_hours)
        self.vehicles_cut_off_shift = {} if pd_vehicles_cut_off_shift.empty else self.vehicles_cut_off_shift_to_dict(
            pd_vehicles_cut_off_shift)
        # ==================Volumes to add===========
        self.volumes_to_add = self.volumes_add_to_dict(pd_volumes_add)

        # ================== ASU visit duration ===========
        """Run after fill the data from files"""
        self.trip_durations = {asu_id: self.trip_duration(asu_id) for asu_id in self.asu_parameters}

        """Далекие АЗС"""
        self.far_asu = [asu_id for asu_id, duration in self.trip_durations.items() if duration > self.parameters.shift_size + 1.5]

    """Extract fuel types in load"""

    def fuel_types(self, asu_n_set):
        fuel_types = []
        for asu, n in asu_n_set:
            sku = self.tank_sku[asu, n]
            fuel_types.append(self.fuel_groups[sku])

        return set(fuel_types)

    """Calculate number of empty section"""

    def empty_section_number(self, truck_num, asu_n_set):
        fuel_types = self.fuel_types(asu_n_set)

        if len(fuel_types) == 1:
            if 'diesel' in fuel_types:
                return self.vehicles[truck_num].sec_empty['np_diesel']
            else:
                return self.vehicles[truck_num].sec_empty['np_petrol']
        elif 'diesel' in fuel_types:
            return self.vehicles[truck_num].sec_empty['np_mix']
        else:
            return self.vehicles[truck_num].sec_empty['np_petrol']

    """Calculate useful sections in truck"""

    def sections_to_load(self, truck_num, asu_n_set):
        sections = self.vehicles[truck_num].sections_volumes.copy()
        number_of_sections = len(sections)
        empty_section_numbers = self.empty_section_number(truck_num, asu_n_set)

        if empty_section_numbers != [0]:
            for empty_section_number in empty_section_numbers:
                sections.pop(number_of_sections - empty_section_number)
            return sections
        else:
            return sections

    # """Depot-asu-sku-time connection for fuel restrictions"""
    #
    # def depot_asu_connection_allocation(self, asu_id, n, time, asu_reallocated):
    #     sku = self.tank_sku[asu_id, n]  # Тип топлива  на АЗС (НП)
    #     sku_depot = self.fuel_in_depot_inverse[sku]  # Тип топлива на НБ
    #     depot_id = self.asu_depot[asu_id]  # Номер НБ привязанной к asu_id
    #     day = day_calculation_by_shift(time)
    #     fuel_limit = self.restricts.get((depot_id, sku_depot, day), 10 ** 10)  # открытия на НБ TODO unlimited opens
    #
    #     asu_depot_reallocation = {}
    #
    #     if fuel_limit <= 0:
    #         depot_and_dist = {depot_id: 999999}
    #         for depot in self.depot_capacity:
    #             opens = self.restricts.get((depot, sku_depot, day), 10 ** 10)
    #             if opens > 0:
    #                 depot_and_dist[depot] = self.distances_asu_depot[depot, asu_id]
    #         depot_new = min(depot_and_dist, key=depot_and_dist.get)
    #         asu_depot_reallocation[asu_id, n, time] = depot_new
    #         if depot_new != depot_id:
    #             asu_reallocated.append(asu_id)
    #     else:
    #         asu_depot_reallocation[asu_id, n, time] = depot_id
    #
    #     return asu_depot_reallocation
    #
    # """Tanks reallocation to depots"""
    #
    # def depot_asu_reallocation_in_period(self):
    #     asu_reallocated_dict = {}
    #     asu_depot_reallocation = {}
    #     for time in range(self.parameters.absolute_period_start,
    #                       self.parameters.absolute_period_start + 2 * self.parameters.hidden_period):  # TODO absolute period is not equals to local
    #         asu_reallocated = []
    #         for idx, row in self.tanks.iterrows():
    #             asu_depot_reallocation.update(
    #                 self.depot_asu_connection_allocation(extract_asu_id(row), extract_tank_id(row), time, asu_reallocated))
    #
    #         asu_reallocated_dict[time] = asu_reallocated
    #
    #     return asu_depot_reallocation, asu_reallocated_dict

    """Test the compatibility of vehicle and depot"""

    def depot_vehicles_compatibility(self, truck_number, depot):

        allowed = (depot in self.vehicles[truck_number].depot_allowed or not self.vehicles[truck_number].depot_allowed)

        return allowed

    """Test the compatibility of vehicle and asu"""

    def asu_vehicles_compatibility(self, truck_number, asu_id):
        drain_sides = self.vehicles[truck_number].drain_side_left == self.asu_parameters[asu_id][0] or \
                      self.vehicles[truck_number].drain_side_right == self.asu_parameters[asu_id][1]

        bulky = self.vehicles[truck_number].is_bulky <= 1 - self.asu_parameters[asu_id][2]

        # automatic = self.vehicles[truck_number].is_own >= self.asu_automatic_status[asu_id]
        automatic = True

        allowed = (asu_id in self.vehicles[truck_number].asu_allowed or not self.vehicles[truck_number].asu_allowed)

        return drain_sides and bulky and automatic and allowed

    def average_section(self):
        # Средняя секция по всем машинам
        set_section = []

        for vehicle_num, vehicle in self.vehicles.items():
            set_section.extend(vehicle.sections_volumes)

        asu_vehicle_avg_section = scipy.stats.mstats.mquantiles(set_section, prob=[0.4, 0.8, 0.1])[0]

        return asu_vehicle_avg_section

    def get_depot_blocks_for_extended_shift(self, depot, time, lb, ub):
        time_blocks = self.block_window_depot.get((depot, time), []).copy()
        if lb:
            lb = self.parameters.shift_size - lb
            extended_time_blocks = self.block_window_depot.get((depot, time - 1), [])
            for block in extended_time_blocks:
                if block[1] > lb:
                    time_blocks.append((max(lb, block[0]) - self.parameters.shift_size,
                                        block[1] - self.parameters.shift_size))
        if ub:
            extended_time_blocks = self.block_window_depot.get((depot, time + 1), [])
            for block in extended_time_blocks:
                if block[0] < ub:
                    time_blocks.append((block[0] + self.parameters.shift_size,
                                        min(ub, block[1]) + self.parameters.shift_size))
        return time_blocks

    def get_depot_decrease_for_extended_shift(self, depot, time, lb, ub):
        time_decrease = self.depot_work_decrease.get((depot, time), []).copy()
        if lb:
            lb = self.parameters.shift_size - lb
            extended_time_decrease = self.depot_work_decrease.get((depot, time - 1), [])
            for decrease in extended_time_decrease:
                if decrease[1] > lb:
                    time_decrease.append((max(lb, decrease[0]) - self.parameters.shift_size,
                                          decrease[1] - self.parameters.shift_size))
        if ub:
            extended_time_decrease = self.depot_work_decrease.get((depot, time + 1), [])
            for decrease in extended_time_decrease:
                if decrease[0] < ub:
                    time_decrease.append((decrease[0] + self.parameters.shift_size,
                                          min(ub, decrease[1]) + self.parameters.shift_size))
        return time_decrease


def unload_time_calculation(asu_id, dp_parameters: Parameters, data: StaticData,
                            truck=None, sku_volume=None, section_count=0):
    """Truck unload time calculation"""
    # TODO добавить слив МОК
    """Truck volume, section_count, thousand_pour_velocity"""
    if sku_volume:
        sku_volume = sku_volume
        section_count = section_count
    elif truck:
        truck_volume = (data.vehicles[truck].volume_min + data.vehicles[truck].volume_max) / 2
        the_densest_sku = max(data.sku_reference, key=lambda x: data.sku_reference[x]['density'])
        sku_volume = {the_densest_sku: truck_volume}
        section_count = len(data.vehicles[truck].sections_volumes) - \
                        sum(map(len, data.vehicles[truck].sec_empty.values())) / 3
    else:
        truck_volume = data.asu_vehicle_avg_volume[asu_id]
        the_densest_sku = max(data.sku_reference, key=lambda x: data.sku_reference[x]['density'])
        sku_volume = {the_densest_sku: truck_volume}
        section_count = 5  # Magic constant

    """Unload time"""
    unload_time = sum(volume / 1000 * dp_parameters.thousand_pour * data.sku_reference[sku]['density']
                      for sku, volume in sku_volume.items()) + \
                  dp_parameters.docs_fill + \
                  (dp_parameters.automatic_load if data.asu_automatic_status[asu_id] else 0) - \
                  (dp_parameters.pump_load * section_count if data.asu_pump[asu_id] else 0)

    return unload_time


def block_window_filter(block_filter: dict, asu_time_windows: dict):
    delete_items = []
    for (asu_id, time), block_window_list in block_filter.items():
        block_window = block_window_list[0]
        shift_num = 2 - time % 2
        if asu_id in asu_time_windows:
            asu_window = asu_time_windows[asu_id][shift_num]
            # Окно занято до или после окна приема
            if block_window[1] <= asu_window[0] or block_window[0] >= asu_window[1] or asu_window[0] == asu_window[1]:
                delete_items.append((asu_id, time))
            # Если окно приемки перекрыто окном занятости
            elif asu_window[0] >= block_window[0] and asu_window[1] <= block_window[1]:
                block_filter[asu_id, time] = [(asu_window[0], asu_window[1])]
            # Окно занятости пересекает правую границу окна приемки
            elif block_window[0] <= asu_window[0] <= block_window[1]:
                block_filter[asu_id, time] = [(asu_window[0], block_window[1])]
            # Окно занятости пересекает левую границу окна приемки
            elif block_window[0] <= asu_window[1] <= block_window[1]:
                block_filter[asu_id, time] = [(block_window[0], asu_window[1])]

    for key in delete_items:
        block_filter.pop(key)


# Returns distance if exists in input data, else return large const
def get_distance(from_val, to_val, dist_set):
    if from_val == to_val:
        return 0
    if (from_val, to_val) in dist_set:
        if dist_set[from_val, to_val] == 0:
            # print('the distance from ' + str(from_val) + ' to ' + str(to_val) + ' = 0. Check it pls')
            return 0
        return dist_set[from_val, to_val]
    else:
        # print('No distance from %s to %s' % (str(from_val), str(to_val)))
        return 1000


# Return shift number
def shift_number_calculation(shift):
    # Two possibilities: day's shift, night's shift
    # day's shift starts at 08:00, ends at 20:00
    # night's shift starts at 20:00, ends at 08:00
    if shift % 2 == 1:
        return 1  # day shift
    else:
        return 2  # night shift


if __name__ == '__main__':
    parameters_ = Parameters()
    data = StaticData('../input/scenario_2', parameters_)
