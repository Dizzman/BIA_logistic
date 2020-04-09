from validation.utils.reader import read_all
from validation.components.validate_depots_queues import validate_depots_queues
from validation.components.validate_stations_queues import validate_stations_queues
from validation.components.validate_depots_time_windows import validate_depots_time_windows
from validation.components.validate_stations_time_windows import validate_stations_time_windows
from validation.components.validate_reservoir_overflow_advanced import validate_reservoir_overflow_advanced
from validation.components.validate_reservoir_shortage_advanced import validate_reservoir_shortage_advanced
from validation.components.validate_loading_composition import validate_loading_composition
from validation.components.validate_time_for_loader import validate_time_for_loader

from validation.structures.Response import Response


def validate_result(input_path, output_path, planning_start, planning_duration):

    paths = dict()

    paths['in_depots'] = '{}/depots.xlsx'.format(input_path)
    paths['in_stations'] = '{}/gas_stations.xlsx'.format(input_path)
    paths['in_reservoirs'] = '{}/start_volume.xlsx'.format(input_path)
    paths['in_addition'] = '{}/volumes_add.xlsx'.format(input_path)
    paths['in_vehicles'] = '{}/vehicles.xlsx'.format(input_path)
    paths['out_timetables'] = '{}/timetable.xlsx'.format(output_path)
    paths['out_states'] = '{}asu_states_until_shift_{}.xlsx'.format(output_path, planning_start)
    paths['in_busy'] = '{}/vehicles_busy.xlsx'.format(input_path)
    paths['distances'] = '{}/data_distances.xlsx'.format(input_path)
    paths['params'] = '{}/model_parameters.xlsx'.format(input_path)

    parameters, depots_data, stations_data, timetables_data, deliveries_data, vehicles_data, excluded_trucks, distances = read_all(paths)

    log = Response()

    validate_depots_queues(parameters, depots_data, timetables_data, log)
    validate_stations_queues(parameters, stations_data, timetables_data, log)
    validate_depots_time_windows(parameters, depots_data, timetables_data, log)
    validate_stations_time_windows(parameters, stations_data, timetables_data, log)
    validate_reservoir_overflow_advanced(parameters, stations_data, timetables_data, deliveries_data, log)
    validate_reservoir_shortage_advanced(parameters, stations_data, timetables_data, deliveries_data, log)
    validate_loading_composition(parameters, deliveries_data, stations_data, vehicles_data, log)
    validate_time_for_loader(parameters, deliveries_data, timetables_data, excluded_trucks, vehicles_data, distances, depots_data, log)


    log.print()
