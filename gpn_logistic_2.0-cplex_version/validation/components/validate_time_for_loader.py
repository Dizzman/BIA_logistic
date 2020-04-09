from validation.components.validate_depots_queues import is_allowable_to_load_at_nb, queue_at_depot
from validation.utils.time_windows_parser import parse_time_period_to_time_segment, convert_minutes_to_time


def is_truck_of_the_company(vehicle_id, vehicles):
    for vehicle in vehicles:
        if vehicle_id == vehicle.id:
            if vehicle.is_owner:
                return True

    return False


def validate_time_for_loader(parameters, deliveries, operations, excluded_trucks, vehicles, distances, depots, log):
    planning_time_beginning = parameters['planning_start']
    planning_time_end = parameters['planning_start'] + parameters['planning_duration'] - 1

    for checking_shift in range(planning_time_beginning, planning_time_end + 1):
        trips_to_check = {}

        # Выбираем все рейсы, которые нужно проверить на время для загрузки под сменщика

        for operation in operations:
            if operation.operation == 'слив' and operation.shift == checking_shift and operation.truck and \
                    is_truck_of_the_company(operation.truck, vehicles):
                if (operation.shift, operation.truck) in trips_to_check:
                    if trips_to_check[(operation.shift, operation.truck)]['time_end'] < operation.end_time:
                        trips_to_check[(operation.shift, operation.truck)]['time_end'] = operation.end_time
                        trips_to_check[(operation.shift, operation.truck)]['location'] = operation.location
                elif (operation.shift, operation.truck) not in excluded_trucks:
                    trips_to_check[(operation.shift, operation.truck)] = {
                        'location': operation.location,
                        'time_end': operation.end_time,
                        'next_depot': None,
                        'for_loader': False
                    }

        for operation in operations:
            if operation.operation == 'налив' and operation.shift == checking_shift:
                if (operation.shift, operation.truck) in trips_to_check:
                    if operation.end_time > trips_to_check[(operation.shift, operation.truck)]['time_end']:
                        trips_to_check[(operation.shift, operation.truck)]['next_depot'] = operation.location
                        trips_to_check[(operation.shift, operation.truck)]['for_loader'] = True
                        trips_to_check[(operation.shift, operation.truck)]['duration'] = operation.duration

        for operation in operations:
            if operation.operation == 'налив' and operation.shift == checking_shift + 1:
                if (checking_shift, operation.truck) in trips_to_check:
                    if not trips_to_check[(checking_shift, operation.truck)]['next_depot']:
                        trips_to_check[(checking_shift, operation.truck)]['next_depot'] = operation.location
                        trips_to_check[(checking_shift, operation.truck)]['duration'] = operation.duration

        trips_not_to_consider = set()

        for key, item in trips_to_check.items():
            if not item['next_depot']:
                trips_not_to_consider.add(key)

        for el in trips_not_to_consider:
            del trips_to_check[el]

        # Вычисляем остатки времени для каждого рейса

        for key, item in trips_to_check.items():
            item['rest'] = 12 - item['time_end']

        # Вычисляем УЭТ для каждого рейса

        for key, item in trips_to_check.items():
            truck_id = key[1]

            for vehicle in vehicles:
                if vehicle.id == truck_id:
                    item['uet_id'] = vehicle.uet

            if not item['next_depot']:
                continue

        for key, item in trips_to_check.items():
            item['from_station_to_depot'] = distances[(item['location'], item['next_depot'])]
            item['from_depot_to_uet'] = distances[(item['next_depot'], item['uet_id'])]

        for key, item in trips_to_check.items():
            if not item['for_loader']:
                total_duration = item['from_station_to_depot'] + item['from_depot_to_uet'] + item['duration']

                if total_duration < item['rest']:
                    loading_possible_start = item['time_end'] + item['from_station_to_depot']
                    loading_possible_end = 12.0 - item['from_depot_to_uet'] - item['duration']

                    checking_period = parse_time_period_to_time_segment(checking_shift,
                                                                        loading_possible_start,
                                                                        loading_possible_end)

                    for _key, val in checking_period.items():
                        if val:
                            if is_allowable_to_load_at_nb(checking_shift, _key, item['next_depot'], depots, operations):
                                current_depot_queue = queue_at_depot(checking_shift, _key, item['next_depot'], depots, operations)
                                log.add_message(module='validate_time_for_loader',
                                                shift=checking_shift,
                                                time=convert_minutes_to_time(_key),
                                                depot_id=item['next_depot'],
                                                truck_id=key[1],
                                                message="БВ может быть загружен под сменщика. "
                                                        "В момент времени {} очередь на НБ {} составляет {} БВ.".
                                                format(convert_minutes_to_time(_key), item['next_depot'], current_depot_queue))
                                break
