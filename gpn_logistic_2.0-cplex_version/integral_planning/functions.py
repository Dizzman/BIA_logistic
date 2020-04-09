
def extract_asu_id(tank):
    return int(tank['asu_id'])


def extract_depot_id(tank):
    return int(tank['depot_id'])


def extract_tank_id(tank):
    return int(tank['n'])


def extract_sku(tank):
    return int(tank['sku'])


def extract_capacity(tank):
    return int(tank['capacity'])


def extract_capacity_min(tank):
    return int(tank['capacity_min'])


def extract_basic_const(tank, t):
    return (extract_asu_id(tank),
            extract_depot_id(tank),
            extract_tank_id(tank),
            extract_sku(tank),
            t)


def extract_tank_from_vars(v):
    return v[0], v[1], v[4]  # asu_id, depot_id, time


def extract_sku_from_vars(a):
    return a[3]  # sku


def extract_time_from_vars(a):
    return a[4]  # time


def extract_time_from_truck_vars(z):
    return z[2]  # time


def extract_from_to_truck_vars(z):
    return z[0], z[1]


def extractor_asu_output(v):
    return v[0]


def extractor_depot_output(v):
    return v[1]


def extractor_n_output(v):
    return v[2]


def extractor_sku_output(v):
    return v[3]


def dep_shift_available(asu_shift_available, shift, upper_bound):
    shift_number = shift % 2  # Number of shift
    if shift_number == 0:
        return asu_shift_available[2] * upper_bound
    else:
        return asu_shift_available[shift_number] * upper_bound


def consumption_filter(consumption, asu_id, n_id, shift):
    if (asu_id, n_id, shift) in consumption:
        return consumption[asu_id, n_id, shift]
    else:
        print('No data for asu: %d n: %d shift: %d' % (asu_id, n_id, shift))
        return 0


def day_calculation_by_shift(shift):
    return (shift - 1) // 2 + 1


def convert_flows_shifts_to_days(shift_start, shift_end, flows_dict):
    flows_dict_by_days = {}
    for shift in range(shift_start, shift_end):
        if day_calculation_by_shift(shift) in flows_dict_by_days:
            flows_dict_by_days[day_calculation_by_shift(shift)].update(flows_dict[shift].copy())
        else:
            flows_dict_by_days[day_calculation_by_shift(shift)] = flows_dict[shift].copy()

    return flows_dict_by_days


def converter_day_to_shift(day):
    return 2*day - 1


'''Function to calculate the reserve volume on asu'''


def death_volume_with_risk(asu_id, n, depot, shift_current, consumption, capacity_min, parameters, data):
    death_volume_with_reservation = capacity_min
    # TODO 21.03 выбор среднее расстояния от uet до depot
    avg_distance_from_uet = sum(data.distances_asu_uet[data.vehicles[vehicle].uet, depot]
                                for vehicle in data.vehicles)/len(data.vehicles)
    delivery_distance = avg_distance_from_uet + parameters.petrol_load_time + data.distances_asu_depot[depot, asu_id]
    # delivery_distance = data.distances_asu_uet[parameters.uet_name, depot] + parameters.petrol_load_time + data.distances_asu_depot[depot, asu_id]
    shift_amount = delivery_distance // parameters.shift_size  # кол-во смен для доставки
    consum = 0

    for shift in range(int(shift_amount)):
        consum += consumption_filter(consumption, asu_id, n, shift_current + shift + 1)

    shift_part = (delivery_distance % parameters.shift_size + parameters.fuel_reserve) / parameters.shift_size  # кол-во часов для доставки
    consum += shift_part * consumption_filter(consumption, asu_id, n, shift_current + shift_amount + 1)

    return death_volume_with_reservation + consum


'''Distance to delivery for n reduction'''


def overload_risk(asu_id, depot, parameters, data):
    avg_distance_from_uet = sum(data.distances_asu_uet[data.vehicles[vehicle].uet, depot]
                                for vehicle in data.vehicles)/len(data.vehicles)
    # delivery_distance = avg_distance_from_uet + parameters.petrol_load_time + data.distances_asu_depot[depot, asu_id]
    delivery_distance = avg_distance_from_uet + data.distances_asu_depot[depot, asu_id] - parameters.risk_tank_overload

    shift_part = (delivery_distance % parameters.shift_size) / parameters.shift_size  # кол-во часов для доставки

    return 1 - shift_part


def truck_available(trucks_busy, trucks_in_use, shift):
    """Calculate the available trucks in the set"""
    trucks_blocked = [truck for truck, time in trucks_busy if shift == time]
    return [truck for truck in trucks_in_use if truck not in trucks_blocked]


