from data_reader.input_data import StaticData
from detailed_planning.dp_parameters import DParameters
from docplex.mp.model import Model
from math import ceil


def write_lp(model: Model, dp_parameters: DParameters):
    if dp_parameters.write_asu_splitter_model:
        model.export_as_lp(dp_parameters.path_to_save_splitter)


def get_result_asu_splitter(v_vars):
    return {v: round(v_vars[v].solution_value, 2) for v in v_vars if round(v_vars[v].solution_value, 2) > 0}


def get_reallocated_trip_count(n_volumes: dict, reallocated_status: list, asu_vehicle_avg_volume: float):
    reallocated_volume = sum(n_volumes[n] for n in n_volumes if n in reallocated_status)
    return ceil(reallocated_volume / asu_vehicle_avg_volume)


"""ASU splitter:
    - divide volumes to one asu for n trips
    - satisfy min_section and avg_truck volumes
    - minimize sum of divisions"""


def asu_splitter(n_volumes: dict, asu_id: int, data: StaticData, trip_amount: int,
                 dp_parameters: DParameters, death_status: list, reallocated_status: list):
    """Model and var_dict initialization"""
    model = Model('ASU splitter')
    v_vars = {}  # # Объемы для перевозки по типам НП   (номер бака; № рейса) --> объем
    y_vars = {}  # Бинарная переменная, наличия заезда (номер бака, № рейса) --> бинарный указатель выезда

    truck_volume_overfit = {}  # словарь переменных соответствующих переполнению
    n_volume_overfit = {}  # словарь переменных соответствующих переполнениям БВ одним резервуаром

    """Add truck volume restriction constraints"""
    truck_volume_correction = max(data.asu_vehicle_avg_volume[asu_id] + 1, sum(n_volumes.values()) / trip_amount)

    """Привязки резервуаров"""
    allocation_dict = {n: data.asu_depot_reallocation.get((asu_id, n, dp_parameters.time), data.asu_depot[asu_id]) for n in n_volumes}

    """Create variables and add constraints"""
    for n in n_volumes:
        for trip_num in range(trip_amount):
            """
            Create variables:
                - v_n_trip --- the volume loaded to trip for n
                - y_n_trip --- the status of load n into trip
            """
            v = model.continuous_var(lb=0, ub=n_volumes[n], name='v_%d_%d' % (n, trip_num))
            v_vars[n, trip_num] = v
            y = model.binary_var(name='y_%d_%d' % (n, trip_num))
            y_vars[n, trip_num] = y

            """Add vehicles parameters constraints"""
            model.add_constraint_(v >= y * min(data.asu_vehicle_avg_section[asu_id] - 1, n_volumes[n]),
                                  ctname='Min_section_%d_%d' % (n, trip_num))
            model.add_constraint_(v <= 1.1 * y * truck_volume_correction, ctname='Max_section_%d_%d' % (n, trip_num))

        """Add fixed volume division constraints"""
        n_overfit_var = model.continuous_var(lb=0, name='overfit_n_%d' % n)
        n_volume_overfit[n] = n_overfit_var
        model.add_constraint_(sum(v_vars[n, trip] for trip in range(trip_amount)) + n_overfit_var
                              == n_volumes[n], ctname='Volume_sum_%d' % n)

    """Add truck volume restriction constraints"""
    truck_volume_correction = max(data.asu_vehicle_avg_volume[asu_id] + 1, sum(n_volumes.values()) / trip_amount)

    # for trip_num in range(trip_amount):
    #     model.add_constraint_(sum(v_vars[n, trip_num] for n in n_volumes if data.asu_vehicle_avg_section[asu_id]) <= truck_volume_correction, ctname='Truck_volume_restriction_%d' % trip_num)  # +1 to avoid rounding problems

    for trip_num in range(trip_amount):
        truck_volume_overfit[trip_num] = model.continuous_var(lb=0, name='overfit_%d' % trip_num)
        model.add_constraint_(sum(v_vars[n, trip_num] for n in n_volumes if data.asu_vehicle_avg_section[asu_id]) -
                              truck_volume_overfit[trip_num] <= truck_volume_correction, ctname='Truck_volume_restriction_%d' % trip_num)  # +1 to avoid rounding problems

    """Add reallocated tanks constraint"""
    reallocated_trip_count = get_reallocated_trip_count(n_volumes, reallocated_status, truck_volume_correction)
    if reallocated_trip_count and reallocated_trip_count < trip_amount:
        reallocated_trips = []
        for trip_num in range(trip_amount):
            reallocated_trip = model.binary_var(name='Reallocated_trip_%d' % trip_num)
            reallocated_trips.append(reallocated_trip)
            model.add_constraint_(sum(y_vars[val] for val in y_vars if val[0] in reallocated_status and val[1] == trip_num) <=
                                  reallocated_trip * len(reallocated_status), ctname='Reallocated_tanks_%d' % trip_num)
        model.add_constraint_(sum(reallocated_trips) <= reallocated_trip_count, ctname='Reallocated_trip_count')

    "Распределение объемов относительно привязок включается в случае привязки резервуаров к двум НБ"
    depot_list = list(set(allocation_dict.values()))
    if len(list(set(allocation_dict.values()))) == 2:
        "Словарь переменных идентификатора привязки рейса группы резервуаров к НБ"
        depot_vars = {}  # {trip_num: {depot: depot_var}}
        for trip_num in range(trip_amount):
            for depot in depot_list:
                depot_var = model.binary_var(name='depot_%d_%d' % (depot, trip_num))
                depot_vars.setdefault(trip_num, {})[depot] = depot_var
                filtered_vars = [var for (n, trip_num_), var in y_vars.items()
                                 if allocation_dict[n] == depot and trip_num_ == trip_num]
                model.add_constraint_(model.sum(filtered_vars) <= 20 * depot_var, ctname='depot_allocation_%d_%d' % (depot, trip_num))
            model.add_constraint_(model.sum(depot_vars[trip_num].values()) == 1, ctname='depot_uniquines_in_trip_%d' % trip_num)

    """Set objective function: minimize number of divisions"""
    model.minimize(sum(y_vars[val] for val in y_vars) - 2 * sum(y_vars[val] for val in y_vars if val[1] == 0 and val[0] in death_status) +
                   10 * sum(truck_volume_overfit.values()) + 11 * model.sum(n_volume_overfit.values()))

    '''Console output switcher'''

    model.log_output = False

    """Optimize"""
    result = model.solve()

    if not result:
        print('ASU SPLITTER PROBLEM. DATA INCONSISTENCY')
        #model.computeIIS()
        #model.write('asu_splitter_inconsistencies_%d.ilp' % asu_id)
        """Write model"""
        write_lp(model, dp_parameters)

    """Returns: [n, trip_num]: volume"""
    return get_result_asu_splitter(v_vars)
