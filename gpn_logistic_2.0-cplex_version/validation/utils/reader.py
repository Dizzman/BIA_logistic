import pandas as pd
from validation.structures.Depot import Depot
from validation.structures.Station import Station
from validation.structures.Reservoir import Reservoir
from validation.structures.State import State
from validation.structures.Operation import Operation
from validation.structures.Delivery import Delivery
from validation.structures.Vehicle import Vehicle


def read_input_depots(path):
    """Функция считывания информации о нефтебазах из входного файла в объекты
    класса Depot
    :param path: Путь к входному файлу
    :return: List of Depot objects
    """
    depots_array = []

    input_file = pd.read_excel(path)
    records_number = len(input_file)
    for line_id in range(0, records_number):
        new_depot = Depot(input_file.iloc[line_id])
        depots_array.append(new_depot)

    return depots_array


def read_input_stations(path):
    """Функция считывания информации об АЗС из входного файла в объекты
    класса Station
    :param path: Путь к входному файлу
    :return: List of Station objects
    """
    stations_array = []

    input_file = pd.read_excel(path)
    records_number = len(input_file)
    for line_id in range(0, records_number):
        new_station = Station(input_file.iloc[line_id])
        stations_array.append(new_station)

    return stations_array


def read_input_reservoirs(path, asu_objects_local):
    """Функция считывания информации о резервуарах из входного файла в объекты
    класса Reservoir
    :param path: путь к входному файлу
    :param asu_objects_local: Список АЗС, к которым привязываются резервуары
    :return: List of Reservoir objects
    """

    input_file = pd.read_excel(path)
    record_number = len(input_file)
    for line_id in range(0, record_number):
        new_reservoir = Reservoir(input_file.iloc[line_id])

        for asu_obj in asu_objects_local:
            if new_reservoir.asu_id == asu_obj.asu_id:
                asu_obj.connect_reservoir(new_reservoir)


def read_output_states(path, asu_objects_local):
    """Функция считывания выходной информации о состояниях резервуаров.
    :param path: Путь к выходному файлу
    :param asu_objects_local: Список АЗС, к которым привязываются состояния по сменам
    :return: List of...
    """

    input_file = pd.read_excel(path)
    records_number = len(input_file)
    for line_id in range(0, records_number):

        new_state = State(input_file.iloc[line_id])

        for asu_obj in asu_objects_local:
            for reservoir_obj in asu_obj.reservoirs:
                if reservoir_obj.asu_id == new_state.asu_id and \
                        reservoir_obj.n == new_state.n:
                    reservoir_obj.states.append(new_state)


def read_output_timetables(path):
    """Функция считывания выходной информации о расписании движения рейсов
    :param path: Путь к файлу c расписанием рейсов
    :return: Список операций
    """
    operations_array = []

    input_file = pd.read_excel(path, sheet_name='full_timetable')

    records_number = len(input_file)

    for line_id in range(0, records_number):
        new_operation = Operation(input_file.iloc[line_id])
        operations_array.append(new_operation)

    return operations_array


def read_additional_trips(path):
    """Функция считывания из файла рейсов, запланированных вручную
    :param path: Путь к файлу c расписанием рейсов
    :return: Список операций
    """

    deliveries_array = []
    operations_array = []

    input_file = pd.read_excel(path, sheet_name='volumes_add')

    records_number = len(input_file)

    for line_id in range(0, records_number):
        new_delivery = Delivery(input_file.iloc[line_id], volumes_add=True)
        deliveries_array.append(new_delivery)

    input_file = pd.read_excel(path, sheet_name='block_window')

    records_number = len(input_file)

    for line_id in range(0, records_number):
        current_asu_id = int(input_file.iloc[line_id]['asu_id'])
        current_shift = int(input_file.iloc[line_id]['time'])

        for delivery in deliveries_array:
            if delivery.asu == current_asu_id and delivery.shift == current_shift:
                new_operation = Operation(input_file.iloc[line_id], volumes_add=True)
                delivery.time = new_operation.start_time

                number_of_operations_like_this = 0

                for operation in operations_array:
                    if operation.location == new_operation.location and \
                            operation.shift == new_operation.shift and \
                            operation.start_time == operation.start_time and \
                            operation.end_time == operation.end_time:
                        number_of_operations_like_this += 1

                if number_of_operations_like_this < 1:
                    operations_array.append(new_operation)

    return operations_array, deliveries_array


def read_output_timetables_detailed(path):
    """Функция считывания выходной информации о расписании движения рейсов
    :param path: Путь к файлу c расписанием рейсов
    :return: Список операций
    """
    deliveries_array = []

    input_file = pd.read_excel(path, sheet_name='timetable')

    records_number = len(input_file)

    for line_id in range(0, records_number):
        delivery = Delivery(input_file.iloc[line_id])
        deliveries_array.append(delivery)

    return deliveries_array


def read_input_vehicles(path):
    vehicles_array = []

    input_file = pd.read_excel(path)

    records_number = len(input_file)

    for line_id in range(0, records_number):
        new_vehicle = Vehicle(input_file.iloc[line_id])
        vehicles_array.append(new_vehicle)

    return vehicles_array


def read_params(path):
    """Функция считывания параметров расчёта из файла model_parameters.
    :param path: Путь к файлу.
    :return: Dict config
    """

    config = {}

    input_file = pd.read_excel(path)

    records_number = len(input_file)

    for line_id in range(0, records_number):
        key = input_file.iloc[line_id]['Parameter']
        val = input_file.iloc[line_id]['Value']
        config[key] = val

    config['planning_start'] = int(config['planning_start'])
    config['planning_duration'] = int(config['planning_duration'])
    config['hidden_period'] = int(config['hidden_period'])
    config['absolute_period_start'] = int(config['absolute_period_start'])
    config['absolute_period_duration'] = int(config['absolute_period_duration'])

    return config


def read_distances(path):
    distances = {}

    input_file = pd.read_excel(path, sheet_name='asu_depots')

    records_number = len(input_file)

    for line_id in range(0, records_number):
        from_id = int(input_file.iloc[line_id]['from'])
        to_id = int(input_file.iloc[line_id]['to'])
        dist = float(input_file.iloc[line_id]['distance'])
        distances[(from_id, to_id)] = dist

    input_file = pd.read_excel(path, sheet_name='uet')

    records_number = len(input_file)

    for line_id in range(0, records_number):
        from_id = input_file.iloc[line_id]['from']
        if type(from_id) == float:
            from_id = int(from_id)
        to_id = input_file.iloc[line_id]['to']
        if type(to_id) == float:
            to_id = int(to_id)
        dist = float(input_file.iloc[line_id]['distance'])
        distances[(from_id, to_id)] = dist

    return distances


def read_excluded_trucks(path):
    excluded_trucks = set()

    input_file = pd.read_excel(path, sheet_name='vehicles_cutted_off_time')

    records_number = len(input_file)

    for line_id in range(0, records_number):
        truck_id = int(input_file.iloc[line_id]['idx'])
        shift_id = int(input_file.iloc[line_id]['shift'])
        excluded_trucks.add((shift_id, truck_id))

    return excluded_trucks


def read_all(data_paths):
    """Функция считывания всех необходимых данных для осуществления проверки.
    :param data_paths: Словарь путей к требуемым входных файлам
    :return: depots_data, asu_data, timetables_data - списки с информацией
    о НБ, АЗС и резервуарах, расписаниях рейсов
    """

    parameters = read_params(data_paths['params'])
    depots_data = read_input_depots(data_paths['in_depots'])
    vehicles_data = read_input_vehicles(data_paths['in_vehicles'])
    asu_data = read_input_stations(data_paths['in_stations'])
    read_input_reservoirs(data_paths['in_reservoirs'], asu_data)
    read_output_states(data_paths['out_states'], asu_data)
    timetables_data = read_output_timetables(data_paths['out_timetables'])
    deliveries_data = read_output_timetables_detailed(data_paths['out_timetables'])
    excluded_trucks = read_excluded_trucks(data_paths['in_busy'])
    distances = read_distances(data_paths['distances'])

    additional_operations, additional_deliveries = read_additional_trips(data_paths['in_addition'])

    timetables_data.extend(additional_operations)
    deliveries_data.extend(additional_deliveries)

    return parameters, depots_data, asu_data, timetables_data, deliveries_data, vehicles_data, excluded_trucks, distances
