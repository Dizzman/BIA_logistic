from data_reader.input_data import StaticData, Parameters
from output_writer.output_stations_state import OutputCreatorStations
from copy import deepcopy
from asu_nb_connecting.update_static_data import update_static_data
from validation.components.prevalidate_reservoir_overflow import validate_reservoir_overflow
import os
from os import listdir
from os.path import isfile, join
import shutil
import pandas as pd
import numpy as np
import math


"""Небходимо разбить данные:
    - АЗС (по критичности равномерно)
    - Остатки по АЗС
    - Общие открытия на НБ
    - Парк БВ"""


class DSplitter:
    def __init__(self, data: StaticData, parameters: Parameters,
                 output_states_collection: OutputCreatorStations):
        self.data = data
        self.parameters = parameters
        self.output_states_collection = output_states_collection
        self.data_avg_depot = self.data_convert_to_common_depot()
        self.sum_scheck = 0

    def death_estimater(self):
        """Функиця оценки кол-ва смен до остновки АЗС
           Расчет обьемов потребления за смену
        Returns: сортированный {asu_id: time_to_death, ...},
                 {asu_id: {sku: volume_consumed, ...}, ... }"""
        asu_death_dict = {}
        volume_consumed = {}
        shifts = [shift + self.parameters.absolute_period_start
                  for shift in range(0, self.parameters.absolute_period_duration)]

        for _, tank in self.data.tanks.to_dict('index').items():
            asu_id = int(tank['asu_id'])
            tank_id = int(tank['n'])
            sku = int(tank['sku'])
            volume_consumed[asu_id] = {} if asu_id not in volume_consumed else volume_consumed[asu_id]

            asu_death_dict.setdefault(asu_id, {})[tank_id] = self.output_states_collection.get_time_to_death(
                            self.parameters.absolute_period_start - 1, asu_id, tank_id)
            for shift in shifts:
                volume_consumed[asu_id][sku] = volume_consumed[asu_id].get(sku, 0) + \
                                               self.data.consumption.get((asu_id, tank_id, shift), 0)

        asu_death_dict = {asu_id: min(list(tank_death.values())) for asu_id, tank_death in asu_death_dict.items()}

        return sorted(asu_death_dict, key=asu_death_dict.get), volume_consumed

    def data_convert_to_common_depot(self):
        """Обновление входных данных данных под среднюю НБ
        Returns: StaticData()"""
        updated_data = deepcopy(self.data)
        update_static_data(updated_data)
        validate_reservoir_overflow(data=updated_data,
                                    parameters=self.parameters,
                                    horizon=(self.parameters.absolute_period_start,
                                             self.parameters.absolute_period_duration))

        return updated_data

    def partitioning(self):
        """
        Функция разбиения АЗС на группы по критичности
        Returns: {group_id: [asu_id, ...], ...},
                 {group_id, depot_sku: consumption},
                 number_of_groups
        """
        data_avg_depot = self.data_avg_depot  # self.data_convert_to_common_depot()
        sorted_asu_death_list = list(self.death_estimater()[0])
        volume_consumed = self.death_estimater()[1]
        "Вычисление кол-ва групп"
        number_of_groups = int(math.ceil(len(sorted_asu_death_list) / self.parameters.group_size))
        "Разбиение АЗС на группы"
        asu_groups = {}
        group_consumption = {}

        for idx, asu_id in enumerate(sorted_asu_death_list):
            group_id = idx % number_of_groups
            asu_groups.setdefault(group_id, []).append(asu_id)
            for (depot_id, depot_sku), asu_sku_list in data_avg_depot.fuel_in_depot.items():
                for sku in asu_sku_list:
                    group_consumption[group_id, depot_sku] = group_consumption.get((group_id, depot_sku), 0) + \
                                                             volume_consumed[asu_id].get(sku, 0)

        return asu_groups, group_consumption, number_of_groups

    @staticmethod
    def start_volume_filter(asu_list, directory):
        """
        Функция фильтрации начальных остатков для расчета
        Args:
            asu_list: список АЗС
            directory: путь к файлу start_volume.xlsx

        Returns:
                Ничего. Перезаписывает файл в соответствующем пакете
        """
        start_volumes = pd.ExcelFile(directory + 'start_volume.xlsx').parse('start_volume')
        start_volumes = start_volumes[start_volumes['asu_id'].isin(asu_list)]
        start_volumes.to_excel(directory + "start_volume.xlsx", sheet_name='start_volume')

    def update_depot_opens(self, group_consumption: dict, group_id: int, directory):
        """
        Функция обновления информации об открытиях для каждой группы
        Args:
            group_consumption: потребление на всех АЗС за период в разрезе НП
            group_id: номер группы
            directory: путь создания/перезаписи файла

        Returns: Ничего

        """
        restricts = self.data_avg_depot.restricts
        restricts_filtered = []

        common_consumption = {}
        current_group_consumption = {}
        for (group_id_, depot_sku), consumption in group_consumption.items():
            common_consumption[depot_sku] = common_consumption.get(depot_sku, 0) + consumption
            if group_id_ == group_id:
                current_group_consumption[depot_sku] = consumption

        for depot_sku, volume in current_group_consumption.items():
            for day, vol in {day_: vol_
                             for (depot_id_, sku_, day_), vol_ in restricts.items() if depot_sku == sku_}.items():
                volume_part = vol * volume / (common_consumption[depot_sku] + 1)
                restricts_filtered.append((0, depot_sku, day, volume_part))

        writer = pd.ExcelWriter(directory + 'flow_restrictions.xlsx')
        restricts_pd = pd.DataFrame(restricts_filtered, columns=['depot_id', 'sku', 'day', 'volume'])
        restricts_pd.to_excel(writer, sheet_name='restrict')
        writer.save()

    @staticmethod
    def update_model_parameters(directory, group_number, group_id):
        model_parameters = pd.ExcelFile(directory + 'model_parameters.xlsx').parse('model_parameters')
        model_parameters = model_parameters.append({'Parameter': 'truck_capacity_part', 'Value': round(1/group_number, 2)},
                                                   ignore_index=True)
        model_parameters = model_parameters.append({'Parameter': 'package_num', 'Value': group_id},
                                                   ignore_index=True)
        model_parameters.to_excel(directory + "model_parameters.xlsx", sheet_name='model_parameters')

    def sku_resource_update(self, directory):
        """
        Функция обновления данных по типам НП под среднюю НБ
        Args:
            directory: путь записи/перезаписи файла sku_reference

        Returns: Ничего

        """
        sku_resource = []
        for depot_sku, sku_dict in self.data_avg_depot.groups_for_openings_sum.items():
            for sku in sku_dict['sku_merged']:
                sku_resource.append((0, sku, depot_sku, 0))

        sku_reference = pd.ExcelFile(directory + 'sku_reference.xlsx').parse('sku_reference')

        writer = pd.ExcelWriter(directory + 'sku_reference.xlsx')
        restricts_pd = pd.DataFrame(np.array(sku_resource), columns=['depot_id', 'sku', 'sku_depot', 'deficit'])
        sku_reference.to_excel(writer, sheet_name='sku_reference')
        restricts_pd.to_excel(writer, sheet_name='sku_resource')
        writer.save()

    def depot_update(self, directory):
        """
        Функция обновления данных по открытиям
        Args:
            directory: путь записи/перезаписи файла depots

        Returns: Ничего

        """
        writer = pd.ExcelWriter(directory + 'depots.xlsx')
        col_names = ['depot_id', 'depot_name', 'depot_address',
                     'lon', 'lat', 'depot_time_window', 'depot_traffic_capacity', 'max_weight', 'load_time']
        load_times = list(self.data.depot_load_time.values())
        row = [[0, 'None', 'None', 0, 0, '00:00-23:59', 20, 44, sum(load_times) / (len(load_times) + 0.001)]]
        depots = pd.DataFrame(np.array(row), columns=col_names)
        depots.to_excel(writer, sheet_name='depots')
        writer.save()

    @staticmethod
    def depot_queue_update(directory):
        """
        Функция обновления данных по очередям на НБ
        Args:
             directory: путь записи/перезаписи файла depot_queue

        Returns: Ничего

        """
        writer = pd.ExcelWriter(directory + 'depot_queue.xlsx')
        depot_queue = pd.ExcelFile(directory + 'depot_queue.xlsx').parse('queue_time')
        depot_queue['depot_id'] = 0
        depot_queue.to_excel(writer, sheet_name='queue_time')

        writer.save()

    def generate_outputs(self, data_in, data_out):
        """
        Функция генерации пакетов данных
        Args:
            data_in: путь к исходным данным
            data_out: путь к выходным данным

        Returns: Ничего

        """
        directory = data_in  # '../input/scenario_2/'
        files = [f for f in listdir(directory) if isfile(join(directory, f))]

        asu_groups, group_consumption, number_of_groups = self.partitioning()

        for group_id, asu_list in asu_groups.items():
            path_out = data_out + 'input_data_%d/' % group_id
            if not os.path.exists(path_out):
                os.makedirs(path_out)
            for file in files:
                shutil.copyfile(directory + file, path_out + file)
            self.start_volume_filter(asu_list, path_out)
            self.update_depot_opens(group_consumption, group_id, path_out)
            self.sku_resource_update(path_out)
            self.depot_update(path_out)
            self.depot_queue_update(path_out)
            self.update_model_parameters(path_out, number_of_groups, group_id)


if __name__ == '__main__':
    scenario = 2
    path = '../input/scenario_' + str(scenario)

    parameters_test = Parameters()  # Parameters initialization
    data_test = StaticData(path, parameters_test)  # Initial data initialization
    initial_state = data_test.initial_fuel_state.copy()

    output_states_collection_test = OutputCreatorStations(data=data_test,
                                                          parameters=parameters_test,
                                                          init_states=initial_state,
                                                          time_zero=parameters_test.absolute_period_start - 1)

    data_splitter_test = DSplitter(data=data_test,
                                   parameters=parameters_test,
                                   output_states_collection=output_states_collection_test)

    data_splitter_test.generate_outputs('../input/scenario_2/', './')
