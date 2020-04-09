from data_reader.input_data import StaticData, Parameters, unload_time_calculation, get_distance, shift_number_calculation
from detailed_planning.dp_parameters import DParameters
from detailed_planning.functions import get_depot_allocation
from detailed_planning.best_truck_load_linear import define_depot


'''Route rough duration:
    - Drive time from uet to nb
    - Truck load time
    - Drive time from nb to asu1
    - Truck unload time
    - Drive time from asu1 to asu2
    - Drive time from asu2 to uet'''


# Check the route duration with shift size, return true/false
# The fictive asu should be checked in input
def route_duration_calculation(asu1_orig, asu2_orig, shift, data: StaticData, parameters: Parameters,
                               dp_parameters: DParameters, work_time, truck=None):
    shift_number = shift_number_calculation(shift)  # Shift number
    # depot = data.asu_depot[asu1]  # Depot connected to asu
    # depot = get_depot_allocation([asu1_orig, asu2_orig], data, dp_parameters)
    asu_n_list = [(asu, n) for asu in (asu1_orig, asu2_orig) for a, n in data.tank_sku if a == asu]
    depot = define_depot(asu_n_list, data, dp_parameters)
    if depot is None:
        return False
    asu1 = dp_parameters.asu_decoder(asu1_orig)
    asu2 = dp_parameters.asu_decoder(asu2_orig)

    '''If asu doesn't work at this shift'''
    if data.asu_work_shift[asu1][shift_number] == 0 or data.asu_work_shift[asu2][shift_number] == 0:
        return False
    '''Initialize distance of route'''
    distance = 0
    '''Drive time from uet to depot'''
    if truck:
        distance += get_distance(data.vehicles[truck].uet, depot, data.distances_asu_uet)
    else:
        avg_distance_from_uet = min(get_distance(data.vehicles[vehicle].uet, depot, data.distances_asu_uet)
                                    for vehicle in data.vehicles)
        distance += avg_distance_from_uet
    '''Truck load'''
    distance += data.depot_load_time[depot]  # parameters.petrol_load_time
    '''Drive time from depot to asu'''
    distance += get_distance(depot, asu1, data.distances_asu_depot)
    '''Time windows check'''
    if distance > data.asu_work_time[asu1][shift_number][1]:
        return False  # If asu is closed for trucks
    else:
        distance = max(data.asu_work_time[asu1][shift_number][0], distance)  # Waiting till asu opens
    '''Half truck unload time'''
    distance += unload_time_calculation(asu1, dp_parameters, data) * 0.6
    '''Drive time from asu1 to asu2'''
    distance += get_distance(asu1, asu2, data.distances_asu_depot)
    '''Time windows check for second asu'''
    if distance > data.asu_work_time[asu2][shift_number][1]:
        return False  # If asu2 is closed for trucks
    else:
        distance = max(data.asu_work_time[asu2][shift_number][0], distance)  # Waiting till asu2 opens
    '''Half truck unload time'''
    distance += unload_time_calculation(asu2, dp_parameters, data) * 0.6
    '''Drive time from second asu to uet'''
    if truck:
        distance += get_distance(asu2, data.vehicles[truck].uet, data.distances_asu_uet)
    else:
        avg_distance_to_uet = min(get_distance(asu2, data.vehicles[vehicle].uet, data.distances_asu_uet)
                                  for vehicle in data.vehicles)
        distance += avg_distance_to_uet

    return distance <= work_time


# Check truck capacity: vol in route < maxTruckVolume
def check_truck_capacity(asu1_orig, asu2_orig, data: StaticData, dp_parameters: DParameters):
    asu1 = dp_parameters.asu_decoder(asu1_orig)
    asu2 = dp_parameters.asu_decoder(asu2_orig)

    asu1_volume = sum(volume[0] for key, volume in dp_parameters.load_info[asu1_orig].items())
    asu2_volume = sum(volume[0] for key, volume in dp_parameters.load_info[asu2_orig].items())

    return asu1_volume + asu2_volume <= data.asu_vehicle_max_volume[asu1] and \
           asu1_volume + asu2_volume <= data.asu_vehicle_max_volume[asu2]


# Check truck capacity: vol in route < maxTruckVolume
def check_asu_for_full_truck(asu1_orig, data: StaticData, dp_parameters: DParameters):
    asu1 = dp_parameters.asu_decoder(asu1_orig)

    asu1_volume = sum(volume[0] for key, volume in dp_parameters.load_info[asu1_orig].items())

    return asu1_volume <= 1 * data.asu_vehicle_max_volume[asu1]


'''Route generator
    - Create possible routes
    - Relaxed check of route duration'''


# TODO checker of volume: vol in route < maxTruckVolume
def route_generator(asu_to_visit: list, data: StaticData, parameters: Parameters, dp_parameters: DParameters):

    """ -Input: [asu_id1, asu_id2, ...], time, asu_decoder, data, parameters
        -Output: [[asu_id1], [asu_id1, asu_id2],...]
        -Return: combinations of asu, which can be visited during one shift using one truck"""

    asu_combinations = []
    min_time_to_death = {}
    for asu in asu_to_visit:
        list_of_vals = [dp_parameters.asu_tank_death[dp_parameters.asu_decoder(asu2), n] for asu2, n in dp_parameters.load_info[asu]]
        list_of_vals.append(5)
        min_time_to_death[asu] = min(list_of_vals)

    for asu1 in asu_to_visit:
        asu_combinations.append((asu1,))  # TODO Comment of problem
        asu1_orig = dp_parameters.asu_decoder(asu1)
        # for asu2 in [asu_val for asu_val in asu_to_visit
        #              if dp_parameters.asu_decoder(asu_val) != dp_parameters.asu_decoder(asu1) and
        #                 data.asu_depot[dp_parameters.asu_decoder(asu1)] == data.asu_depot[dp_parameters.asu_decoder(asu_val)]]:
        for asu2 in [asu_val for asu_val in asu_to_visit]:
            asu2_orig = dp_parameters.asu_decoder(asu2)
            if asu2_orig in data.distributions.get(asu1_orig, []):
                # if not check_truck_capacity(asu1, asu2, data, dp_parameters):
                #     continue
                # If the trip duration approximation is less then shift size
                if route_duration_calculation(asu1, asu2, dp_parameters.time, data, parameters, dp_parameters, dp_parameters.shift_size):
                    # if one of Asu is critical, it should be first in the route

                    trip_arrive_time = (data.trip_durations[dp_parameters.asu_decoder(asu1)] % dp_parameters.shift_size) / (4 * dp_parameters.shift_size)
                    # TODO Check removed
                    # if min_time_to_death[asu1] - trip_arrive_time <= 0.75 or (min_time_to_death[asu1] - trip_arrive_time <= 1.25 and data.asu_work_shift[asu1_orig][shift_number_calculation(dp_parameters.time + 1)] == 0):
                    # if check_asu_for_full_truck(asu1, data, dp_parameters):
                    asu_combinations.append((asu1, asu2))
    print('End of route generation shift = %d' % dp_parameters.time)
    return asu_combinations
