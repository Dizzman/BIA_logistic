import xlsxwriter
import pandas
import datetime
from data_reader.input_data import StaticData, Parameters
from data_reader.objects_classes import Car


class Section:
    def __init__(self, number: int, asu: int, tank: int, sku: int, volume: int, time_start: float,
                 depot: int, is_empty: bool, should_be_empty: bool):
        self.number = number
        self.asu = asu
        self.tank = tank
        self.sku = sku
        self.volume = volume
        self.time_start = time_start
        self.depot = depot
        self.is_empty = is_empty
        self.should_be_empty = should_be_empty


class Route:
    def __init__(self, time: int, truck: int, trip_number: int, fuel_map: tuple, load_before: bool, last_load: bool):
        self.time = time
        self.truck = truck
        self.trip_number = trip_number
        self.fuel_map = fuel_map
        self.is_filled = load_before
        self.last_load = last_load

    def copy(self):
        return Route(self.time, self.truck, self.trip_number, self.fuel_map, self.is_filled, self.last_load)

    def get_sku_set(self):
        sku_set = set(section.sku for section in self.fuel_map)
        if 0 in sku_set:
            sku_set.remove(0)
        return sku_set

    def get_sku_volume(self, sku: int):
        return sum(section.volume for section in self.fuel_map if section.sku == sku)

    def get_asu_count(self):
        asu_set = set(section.asu for section in self.fuel_map)
        if 0 in asu_set:
            asu_set.remove(0)
        return len(asu_set)


class Schedule:
    def __init__(self, static_data: StaticData, parameters: Parameters,
                 timetable_data: pandas.DataFrame = pandas.DataFrame(), asu_death_data: pandas.DataFrame = pandas.DataFrame(),
                 start_time: int = None, duration: int = None):
        self.static_data = static_data
        self.parameters = parameters
        self.route_map = self.get_route_map_from_pandas(timetable_data)
        self.asu_death = self.get_asu_death_from_pandas(asu_death_data)  # {asu, n, time: days_to_death}
        self.start_time = start_time or self.get_min_time()
        self.end_time = (self.start_time + duration - 1) if duration else self.get_max_time()

    def update_data(self, timetable_data: pandas.DataFrame = pandas.DataFrame(), asu_death_data: pandas.DataFrame = pandas.DataFrame(), write_file: bool = False, **kwargs):
        new_schedule = Schedule(self.static_data, self.parameters, timetable_data, asu_death_data)
        self.route_map.update(new_schedule.route_map)
        self.asu_death.update(new_schedule.asu_death)
        self.correct_load_after_and_before()
        self.end_time = self.end_time if self.end_time >= self.get_max_time() else self.get_max_time()
        if write_file:
            new_schedule.write_schedule_file(**kwargs)

    def get_route_map_from_pandas(self, timetable_data: pandas.DataFrame):
        route_map = {}
        if timetable_data.empty:
            return route_map
        route_keys = timetable_data.filter(['shift', 'truck', 'trip_number']).drop_duplicates()
        for i, key in route_keys.iterrows():
            route_data = timetable_data[(timetable_data['shift'] == key['shift']) &
                                        (timetable_data['truck'] == key['truck']) &
                                        (timetable_data['trip_number'] == key['trip_number'])]
            route_key = int(key['shift']), int(key['truck']), int(key['trip_number'])
            fuel_map = []
            for j, row in route_data.iterrows():
                tanks_data = self.static_data.tanks
                sku = 0
                if not row['is_empty']:
                    sku = int(tanks_data[(tanks_data['asu_id'] == row['asu']) &
                                         (tanks_data['n'] == row['n'])]['sku'].head(1))
                section_info = Section(number=int(row['section_number']),
                                       asu=int(row['asu']),
                                       tank=int(row['n']),
                                       sku=sku,
                                       volume=int(row['section_volume']),
                                       time_start=float(row['time']),
                                       depot=int(row['depot']),
                                       is_empty=int(row['is_empty']) == 1,
                                       should_be_empty=int(row['should_be_empty']) == 1)
                fuel_map.append(section_info)
            load_before = max(route_data['load_before'])
            last_load = max(route_data['load_after'])
            route_map[route_key] = Route(*route_key, tuple(fuel_map), load_before, last_load)
        return route_map

    def correct_load_after_and_before(self):
        max_shift = self.get_max_time()
        routes_by_truck = self.get_routes_by_truck()
        for truck in routes_by_truck:
            for route_key in routes_by_truck[truck]:
                shift, truck, trip_number = route_key
                route = self.route_map[route_key]
                if route.last_load and shift != max_shift:
                    next_shift_key = (shift + 1, truck, 1)
                    if next_shift_key not in routes_by_truck[truck] or not self.route_map[next_shift_key].is_filled:
                        route.last_load = False
                if route.is_filled and shift != 1:
                    previous_shift_key = (shift - 1, truck, 1)
                    if previous_shift_key not in routes_by_truck[truck]:
                        self.route_map[previous_shift_key] = Route(*previous_shift_key, tuple(), False, True)
                    elif not self.route_map[previous_shift_key].last_load:
                        route.is_filled = False

    def get_day_offset(self):
        return self.get_day(self.start_time) - 1

    def get_asu_death_from_pandas(self, asu_death_data: pandas.DataFrame):
        asu_death = {}
        if asu_death_data.empty:
            return asu_death
        for i, row in asu_death_data.iterrows():
            asu_death[int(row['asu_id']), int(row['n']), int(row['shift']) + 1] = float(row['days_to_death'])
        return asu_death

    def write_schedule_file(self, file_name: str = '', output_folder: str = '', file_path: str = '', first_date_str: str = ''):
        # file_name: str - имя выходного файла, './output/'
        # output_folder: str - директория выходного файла, 'car_schedule.xlsx'
        # file_path: str - полный путь до выходного файла, output_folder + file_name
        # first_date: str - дата первой смены, '14.01.2019'

        kwargs = {'file_name': file_name, 'output_folder': output_folder, 'file_path': file_path, 'first_date': first_date_str}
        kwargs = {key: item for key, item in kwargs.items() if item}
        if 'first_date' in kwargs:
            kwargs = datetime.date(*reversed(list(map(int, first_date_str.split('.')))))
        schedule_writer = ScheduleWriter(self, self.static_data, self.parameters, **kwargs)
        schedule_vehicle_writer = ScheduleWriter(self, self.static_data, self.parameters, **kwargs, vehicle_names=True)

        start_time = datetime.datetime.now()
        schedule_writer.write_output_file()
        schedule_vehicle_writer.write_output_file()
        end_time = datetime.datetime.now()
        print('=== Schedule is saved (in %.3f sec)' % ((end_time - start_time).microseconds / 1000000))

    def get_max_trip_count(self):
        if self.route_map:
            return max(route.trip_number for key, route in self.route_map.items())
        return 0

    def get_shifts(self):
        shifts = {}
        for key, route in self.route_map.items():
            if route.time not in shifts:
                shifts[route.time] = Schedule(self.static_data, self.parameters)
            shifts[route.time].route_map[key] = route
        times = list(shifts)
        times.sort()
        shifts = [shifts[time] for time in times]
        return shifts

    def get_min_time(self):
        if self.route_map:
            return min(route.time for key, route in self.route_map.items())
        return 0

    def get_max_time(self):
        if self.route_map:
            return max(route.time for key, route in self.route_map.items())
        return 0

    def get_routes_by_truck(self):
        routes_by_truck = {}
        for key, route in self.route_map.items():
            if route.truck not in routes_by_truck:
                routes_by_truck[route.truck] = []
            routes_by_truck[route.truck].append(key)
            routes_by_truck[route.truck].sort(key=lambda x: (self.route_map[x].time, self.route_map[x].trip_number))
        return routes_by_truck

    def get_next_car_route(self, route_key: ()):
        truck = self.route_map[route_key].truck
        shifts = self.get_routes_by_truck()
        if truck in shifts and route_key in shifts[truck]:
            route_index = shifts[truck].index(route_key)
            if route_index < len(shifts[truck]) - 1:
                return shifts[truck][route_index+1]
        return

    def get_previous_car_route(self, route_key: ()):
        truck = self.route_map[route_key].truck
        shifts = self.get_routes_by_truck()
        if truck in shifts and route_key in shifts[truck]:
            route_index = shifts[truck].index(route_key)
            if route_index > 0:
                return shifts[truck][route_index-1]
        return

    def get_route_count(self, owner: int = -1):
        route_count = sum([1 for key, route in self.route_map.items()
                           if (owner == -1 or self.static_data.vehicles[route.truck].is_own == owner) and route.fuel_map])
        return route_count

    def get_car_count(self, owner: int = -1):
        car_count = len(set(route.truck for key, route in self.route_map.items()
                            if (owner == -1 or self.static_data.vehicles[route.truck].is_own == owner) and route.fuel_map))
        return car_count

    def get_turnaround(self, owner: int = -1):
        min_day = self.get_day(self.start_time)
        max_day = self.get_day(self.end_time)
        if min_day == max_day:
            car_count = self.get_car_count(owner)
            if car_count == 0:
                return 0
            turnaround = self.get_route_count(owner) / car_count
        else:
            turnaround_sum = 0
            for day in range(min_day, max_day + 1):
                cut_schedule = self.get_cut_schedule(day * 2 - 1, day * 2)
                turnaround_sum += cut_schedule.get_turnaround(owner)
            turnaround = turnaround_sum / (max_day - min_day + 1)
        return turnaround

    def get_sku_set(self):
        sku_set = set()
        for key, route in self.route_map.items():
            sku_set.update(route.get_sku_set())
        return sku_set

    def get_tank_count(self):
        return len(self.static_data.tank_sku)

    def get_routes_by_time(self):
        routes_by_time = {}
        for key, route in self.route_map.items():
            if route.time not in routes_by_time:
                routes_by_time[route.time] = []
            routes_by_time[route.time].append(key)
        return routes_by_time

    def get_cut_schedule(self, first_time: int, last_time: int):
        routes_by_time = self.get_routes_by_time()
        cut_route_map = {route: self.route_map[route] for time in routes_by_time
                                 if first_time <= time <= last_time for route in routes_by_time[time]}
        cut_schedule = Schedule(self.static_data, self.parameters)
        cut_schedule.route_map = cut_route_map
        cut_schedule.start_time = cut_schedule.get_min_time()
        cut_schedule.end_time = cut_schedule.get_max_time()
        return cut_schedule

    def get_satisfaction_level(self, sku: int, first_time: int = 0, last_time: int = 100):
        load_sum = self.get_load_volume_by_sku(sku) + self.get_added_load_volume_by_sku(sku, first_time, last_time)
        max_time = self.get_max_time()
        consumption_sum = sum(volume for (asu, n, time), volume in self.static_data.consumption.items()
                              if self.static_data.tank_sku[asu, n] == sku and first_time <= time <= last_time
                              and self.parameters.absolute_period_start <= time <=
                              (self.end_time if max_time else self.parameters.absolute_period_duration))
        if consumption_sum == 0 and load_sum == 0:
            return 1
        elif consumption_sum == 0:
            return 999
        satisfaction_level = load_sum / consumption_sum
        return satisfaction_level

    def get_added_load_volume_by_sku(self, sku: int, first_time: int, last_time: int):
        max_time = self.get_max_time()
        filtered_added_volume = sum(volume for (asu, n, time), volume in self.static_data.volumes_to_add.items()
                                   if first_time <= time <= last_time and self.parameters.absolute_period_start <= time <=
                                   (self.end_time if max_time else self.parameters.absolute_period_duration) and
                                   self.static_data.tank_sku[asu, n] == sku)
        return filtered_added_volume

    def get_load_volume_by_sku(self, sku: int):
        volume = 0
        for key, route in self.route_map.items():
            volume += route.get_sku_volume(sku)
        return volume

    def get_death_tank_count(self, first_shift, last_shift):
        tank_count = 0
        for (asu, n, time), time_death in self.asu_death.items():
            if time == self.start_time and first_shift <= (time_death * 2 + 1) // 1 <= last_shift:
                tank_count += 1
        return tank_count

    def get_part_of_direct_route(self):
        min_day = self.get_day(self.start_time)
        max_day = self.get_day(self.end_time)
        if min_day == max_day:
            route_count = self.get_route_count()
            if route_count == 0:
                return 0
            part_of_direct_route = self.get_direct_route_count() / route_count
        else:
            part_of_direct_route_sum = 0
            for day in range(min_day, max_day + 1):
                cut_schedule = self.get_cut_schedule(day * 2 - 1, day * 2)
                part_of_direct_route_sum += cut_schedule.get_part_of_direct_route()
            part_of_direct_route = part_of_direct_route_sum / (max_day - min_day + 1)
        return part_of_direct_route

    def get_direct_route_count(self):
        count = 0
        for key, route in self.route_map.items():
            if route.get_asu_count() == 1:
                count += 1
        return count

    @staticmethod
    def get_day(time: int):
        return (time + 1) // 2

    @staticmethod
    def get_shift(time: int):
        return 1 - time % 2


class ScheduleWriter:
    output_folder = './output/'
    file_name = 'car_schedule.xlsx'
    first_date = datetime.date.today()

    def __init__(self, schedule: Schedule, static_data: StaticData, parameters: Parameters,
                 file_name: str = file_name, output_folder: str = output_folder,
                 file_path: str = '', first_date: datetime.date = first_date, vehicle_names: bool=False):
        if vehicle_names:
            file_name = file_name[:-5] + '_vehicles' + file_name[-5:]
        self.schedule = schedule
        self.static_data = static_data
        self.parameters = parameters
        if not file_path:
            file_path = output_folder + file_name
        self.workbook = xlsxwriter.Workbook(file_path)
        self.workbook.add_worksheet('schedule')
        self.worksheet_schedule = self.workbook.get_worksheet_by_name('schedule')
        self.workbook.add_worksheet('KPI')
        self.worksheet_kpi = self.workbook.get_worksheet_by_name('KPI')
        self.first_date = first_date
        self.vehicle_names = vehicle_names

    left_info_column_count = 4
    route_column_count = 7
    max_route_count = 1
    last_column = 1
    car_description_count = 3

    color_map = {
        'grey': '#DBDBDB',
        'light_grey': '#F0F0F0',
        'yellow': '#FFF814',
        'red': '#CF3F3F',
        'green': '#C1EA95',
        'pink': '#FFEBEB'
    }

    # Запись выходного файла
    def write_output_file(self):
        self.max_route_count = self.schedule.get_max_trip_count() + 1
        self.last_column = self.left_info_column_count + self.route_column_count * self.max_route_count
        shifts = self.schedule.get_shifts()
        for shift in shifts:
            self.write_shift(shift)
        self.write_stat()
        self.workbook.close()

    # Запись статистики
    def write_stat(self):
        head_format = self.set_format({'border': 1, 'bold': 1})
        right_format = self.set_format({'align': 'left', 'border': 1})
        cell_format = self.set_format({'border': 1})
        board_format = self.set_format({'bottom': 2})

        offset = 2 * self.schedule.get_day_offset()
        second_shift_offset = 1 - self.schedule.start_time % 2

        columns = [{'name': 'Наименование показателя'},
                   {'name': '12 часов', 'param': (1 + offset, 1 + offset + second_shift_offset)},
                   {'name': '24 часа', 'param': (1 + offset, 2 + offset)},
                   {'name': 'от 24 до 48 часов', 'param': (3 + offset, 4 + offset)},
                   {'name': 'Среднее за 48 часов', 'param': (1 + offset, 4 + offset)},
                   {'name': 'более 48 часов', 'param': (5 + offset, 100)},
                   {'name': 'Среднее за период', 'param': (0, 100)},
                   {'name': 'Всего за период', 'param': (0, 100)}]

        sku_set = self.schedule.get_sku_set()
        tank_count = self.schedule.get_tank_count()
        death_tank_count = {}

        def get_death_tank_count(time):
            if time not in death_tank_count:
                death_tank_count[time] = self.schedule.get_death_tank_count(*time)
            return death_tank_count[time]

        self.worksheet_kpi.set_column(0, 0, 30)
        self.worksheet_kpi.set_column(1, len(columns)-1, 22)

        kpi_rows = [{'name': 'Оборачиваемость БВ (собственный парк).',
                     'func': lambda x, y: round(x.get_turnaround(owner=1), 2),
                     'columns': [True, True, True, True, True, False, True, False]},
                    {'name': 'Оборачиваемость БВ (сторонний парк).',
                     'func': lambda x, y: round(x.get_turnaround(owner=0), 2),
                     'columns': [True, True, True, True, True, False, True, False]},
                    {'name': 'Оборачиваемость БВ (весь парк).',
                     'func': lambda x, y: round(x.get_turnaround(), 2),
                     'columns': [True, True, True, True, True, False, True, False]},
                    {'name': 'Доля рейсов без развозов (%).',
                     'func': lambda x, y: round(x.get_part_of_direct_route() * 100, 2),
                     'columns': [True, True, True, True, True, False, True, False]},
                    {'name': 'Доля рейсов с развозами (%).',
                     'func': lambda x, y: round((1 - x.get_part_of_direct_route()) * 100, 2) if x.get_part_of_direct_route() else 0,
                     'columns': [True, True, True, True, True, False, True, False]},
                    {'name': 'Количество АЗС, по которым ожидается остановка реализации (шт. резервуаров).',
                     'func': lambda x, y: str(get_death_tank_count(y)) + ' (' + str(round((get_death_tank_count(y)/tank_count) * 100, 2)) + ' %)',
                     'columns': [True, True, True, True, False, True, False, False]},
                    *[{'name': 'Уровень удовлетворённости спроса АЗС (%). ' + self.static_data.sku_vs_sku_name[sku] + '.',
                       'func': lambda x, y, sku=sku: round(x.get_satisfaction_level(sku, *y) * 100, 2),
                       'columns': [True, True, True, True, False, True, False, True]} for sku in sku_set]]

        stat_rows = [{'name': 'Количество машин (собственный парк).',
                      'func': lambda x, y: x.get_car_count(owner=1),
                      'columns': [True, True, True, True, False, True, False, True]},
                     {'name': 'Количество рейсов (собственный парк).',
                      'func': lambda x, y: x.get_route_count(owner=1),
                      'columns': [True, True, True, True, False, True, False, True]},
                     {'name': 'Количество машин (сторонний парк).',
                      'func': lambda x, y: x.get_car_count(owner=0),
                      'columns': [True, True, True, True, False, True, False, True]},
                     {'name': 'Количество рейсов (сторонний парк).',
                      'func': lambda x, y: x.get_route_count(owner=0),
                      'columns': [True, True, True, True, False, True, False, True]},
                     {'name': 'Количество машин (весь парк).',
                      'func': lambda x, y: x.get_car_count(),
                      'columns': [True, True, True, True, False, True, False, True]},
                     {'name': 'Количество рейсов (весь парк).',
                      'func': lambda x, y: x.get_route_count(),
                      'columns': [True, True, True, True, False, True, False, True]}]

        for j, c in enumerate(columns):
            cut_schedule = Schedule(self.static_data, self.parameters)
            if j > 0:
                cut_schedule = self.schedule.get_cut_schedule(*c['param'])
            row_counter = 0
            self.worksheet_kpi.write(row_counter, j, c['name'], head_format)
            row_counter += 1
            for r in kpi_rows:
                if j == 0:
                    self.worksheet_kpi.write(row_counter, j, r['name'], right_format)
                elif r['columns'][j]:
                    self.worksheet_kpi.write(row_counter, j, r['func'](cut_schedule, c['param']), cell_format)
                else:
                    self.worksheet_kpi.write(row_counter, j, '', cell_format)
                row_counter += 1
            self.worksheet_kpi.write(row_counter, j, '', board_format)
            row_counter += 2
            for r in stat_rows:
                if j == 0:
                    self.worksheet_kpi.write(row_counter, j, r['name'], right_format)
                elif r['columns'][j]:
                    self.worksheet_kpi.write(row_counter, j, r['func'](cut_schedule, c['param']), cell_format)
                else:
                    self.worksheet_kpi.write(row_counter, j, '', cell_format)
                row_counter += 1

    # Запись смены
    def write_shift(self, shift: Schedule):
        # Header
        self.write_header(shift.get_min_time())
        # Cars
        car_routes = shift.get_routes_by_truck()
        for car in car_routes:
            routes = [shift.route_map[route_key] for route_key in car_routes[car]]
            self.write_car(self.static_data.vehicles[car], routes)
        # Tail
        self.write_tail(shift.get_route_count(), shift.get_car_count(), shift.get_turnaround())

    # Итоговое количество рейсов за смену
    def write_tail(self, route_count: int, car_count: int, kpi: float):
        line = self.current_last_line(self.worksheet_schedule)
        cell_format = self.set_format({'bottom': 1, 'left': 2, 'right': 1})
        self.worksheet_schedule.write(line - 1, self.last_column - 1, 'Итого рейсов:', cell_format)
        self.worksheet_schedule.write(line, self.last_column - 1, 'Количество машин:', cell_format)
        cell_format = self.set_format({'bottom': 2, 'left': 2, 'right': 1})
        self.worksheet_schedule.write(line + 1, self.last_column - 1, 'Оборачиваемость:', cell_format)
        cell_format = self.set_format({'bottom': 1, 'right': 2, 'bold': 1})
        self.worksheet_schedule.write(line - 1, self.last_column, route_count, cell_format)
        self.worksheet_schedule.write(line, self.last_column, car_count, cell_format)
        cell_format = self.set_format({'bottom': 2, 'right': 2, 'bold': 1})
        self.worksheet_schedule.write(line + 1, self.last_column, round(kpi, 2), cell_format)

    # Запись машины
    def write_car(self, car: Car, routes: list):
        line = self.current_last_line(self.worksheet_schedule)
        # CarDescription
        section_count = car.get_section_amount()
        left_format = self.set_format({'bold': 1, 'right': 2, 'bg_color': self.color_map['light_grey']})
        right_format = self.set_format({'border': 1, 'right': 2})
        drain_format = self.set_format({'bold': 1, 'right': 2, 'bg_color': self.color_map['yellow'], 'font_color': self.color_map['red']})
        row_count = max(section_count, self.car_description_count)
        for i in range(row_count):
            if i == row_count-1:
                left_format = self.set_format({'bold': 1, 'right': 2, 'bg_color': self.color_map['light_grey'], 'bottom': 2})
                right_format = self.set_format({'border': 1, 'right': 2, 'bottom': 2})
                drain_format = self.set_format({'bold': 1, 'right': 2, 'bg_color': self.color_map['yellow'],
                                                'font_color': self.color_map['red'], 'bottom': 2})
            if i == 0:
                number = car.vehicle_number if self.vehicle_names else car.number
                self.worksheet_schedule.write('A' + str(line + i), number, left_format)
            elif i == 1:
                self.worksheet_schedule.write('A' + str(line + i), car.trailer_license, left_format)
            elif i == 2:
                drain = ''
                drain_left_format = left_format
                if car.drain_side_left + car.drain_side_right == 1:
                    drain = 'ПРАВЫЙ СЛИВ' if car.drain_side_right == 1 else 'ЛЕВЫЙ СЛИВ'
                    drain_left_format = drain_format
                self.worksheet_schedule.write('A' + str(line + i), drain, drain_left_format)
            else:
                self.worksheet_schedule.write('A' + str(line + i), '', left_format)
            section_number = (i + 1) if i < section_count else ''
            section_volume = car.sections_volumes[section_count - i - 1] if i < section_count else ''
            self.worksheet_schedule.write('B' + str(line + i), section_number, right_format)
            self.worksheet_schedule.write('C' + str(line + i), section_volume, right_format)
        cell_format = self.set_format({'border': 2})
        self.worksheet_schedule.merge_range('D' + str(line) + ':D' + str(line + row_count - 1), 'АО "Газпромнефть-Транспорт"', cell_format)
        # Routes
        for route in routes:
            self.write_route(car, route, line, last_load=False)
        last_load = any([route.last_load for route in routes])
        if last_load:
            last_route = routes[-1]
            next_route_key = self.schedule.get_next_car_route((last_route.time, last_route.truck, last_route.trip_number))
            if next_route_key:
                next_route = self.schedule.route_map[next_route_key]
                if next_route.is_filled:
                    last_load_route = next_route.copy()
                    last_load_route.time = last_route.time
                    last_load_route.trip_number = self.max_route_count
                    last_load_route.is_filled = False
                    self.write_route(car, last_load_route, line, last_load=True)
            else:
                last_load_route = Route(last_route.time, last_route.truck, self.max_route_count, [], False, True)
                self.write_route(car, last_load_route, line, last_load=True)
        # ShiftCount
        cell_format = self.set_format({'border': 2, 'bold': 1, 'font_size': 20})
        self.worksheet_schedule.merge_range(line - 1, self.last_column, line + row_count - 2, self.last_column,
                                            sum(1 for route in routes if route.fuel_map), cell_format)

    # Запись рейса
    def write_route(self, car: Car, route: Route, line: int, last_load: bool):
        section_count = car.get_section_amount()
        row_count = max(section_count, self.car_description_count)
        if route.trip_number == 1:
            self.write_empty_routes(line, row_count)
        cell_format = self.set_format({'right': 1, 'bottom': 1})
        right_format = self.set_format({'right': 2, 'bottom': 1})
        color_format = self.set_format({'right': 1, 'bottom': 1, 'bg_color': self.color_map['green']})
        empty_format = self.set_format({'right': 1, 'bottom': 1, 'bg_color': self.color_map['light_grey']})
        must_empty_format = self.set_format({'right': 1, 'bottom': 1, 'bg_color': self.color_map['pink']})
        for i, section in enumerate(reversed(route.fuel_map)):
            if i >= section_count:
                break
            elif section.is_empty:
                asu_number = asu_address = asu_tank = depot_name = fuel_name = time_start = ''
                if section.should_be_empty:
                    depot_format = data_format = must_empty_format
                else:
                    depot_format = data_format = empty_format
            else:
                asu_number = section.asu
                asu_address = self.static_data.asu_address_dict[section.asu]
                asu_tank = section.tank
                fuel_name = self.static_data.sku_vs_sku_name[section.sku]
                if not last_load:
                    shift = 1 - route.time % 2
                    time_start = self.float_to_time(section.time_start, shift)
                else:
                    time_start = ''
                if not route.is_filled:
                    depot_name = self.static_data.depot_names_dict[section.depot]
                    depot_format = data_format = cell_format
                else:
                    depot_name = 'Загружена'
                    depot_format = color_format
                    data_format = cell_format
            self.worksheet_schedule.write(line + i - 1, self.left_info_column_count + self.route_column_count * (route.trip_number - 1), depot_name, depot_format)
            self.worksheet_schedule.write(line + i - 1, self.left_info_column_count + self.route_column_count * (route.trip_number - 1) + 1, str(asu_number), data_format)
            self.worksheet_schedule.write(line + i - 1, self.left_info_column_count + self.route_column_count * (route.trip_number - 1) + 2, str(asu_address), data_format)
            self.worksheet_schedule.write(line + i - 1, self.left_info_column_count + self.route_column_count * (route.trip_number - 1) + 3, str(asu_tank), data_format)
            self.worksheet_schedule.write(line + i - 1, self.left_info_column_count + self.route_column_count * (route.trip_number - 1) + 4, str(fuel_name), data_format)
            self.worksheet_schedule.write(line + i - 1, self.left_info_column_count + self.route_column_count * (route.trip_number - 1) + 5, str(time_start), data_format)
            if not last_load:
                self.worksheet_schedule.write(line + i - 1, self.left_info_column_count + self.route_column_count * (route.trip_number - 1) + 6, '', right_format)
            if i == row_count - 2:
                cell_format = self.set_format({'right': 1, 'bottom': 2})
                right_format = self.set_format({'right': 2, 'bottom': 2})
                color_format = self.set_format({'right': 1, 'bottom': 2, 'bg_color': self.color_map['green']})
                empty_format = self.set_format({'right': 1, 'bottom': 2, 'bg_color': self.color_map['light_grey']})
                must_empty_format = self.set_format({'right': 1, 'bottom': 2, 'bg_color': self.color_map['pink']})
        if last_load:
            cell_format = self.set_format({'border': 2, 'left': 1, 'bold': 1, 'bg_color': self.color_map['green']})
            self.worksheet_schedule.merge_range(line - 1, self.left_info_column_count + self.route_column_count * (route.trip_number - 1) + 6, line + section_count - 2,
                                                self.left_info_column_count + self.route_column_count * (route.trip_number-1) + 6, 'Загрузка\nпод сменщика', cell_format)

    # Определение времени доставки
    def float_to_time(self, time_float: float, shift: int):
        time_float = round(time_float * 60, 0) / 60
        time = datetime.timedelta(hours=(time_float + 8 + shift*12) % 24)
        return time

    def write_empty_routes(self, line: int, row_count: int):
        for trip_number in range(self.max_route_count):
            cell_format = self.set_format({'right': 1, 'bottom': 2})
            right_format = self.set_format({'right': 2, 'bottom': 2})
            for i in range(row_count)[::-1]:
                data_format = cell_format
                self.worksheet_schedule.write(line + i - 1, self.left_info_column_count + self.route_column_count * trip_number, '', data_format)
                self.worksheet_schedule.write(line + i - 1, self.left_info_column_count + self.route_column_count * trip_number + 1, '', data_format)
                self.worksheet_schedule.write(line + i - 1, self.left_info_column_count + self.route_column_count * trip_number + 2, '', data_format)
                self.worksheet_schedule.write(line + i - 1, self.left_info_column_count + self.route_column_count * trip_number + 3, '', data_format)
                self.worksheet_schedule.write(line + i - 1, self.left_info_column_count + self.route_column_count * trip_number + 4, '', data_format)
                self.worksheet_schedule.write(line + i - 1, self.left_info_column_count + self.route_column_count * trip_number + 5, '', data_format)
                self.worksheet_schedule.write(line + i - 1, self.left_info_column_count + self.route_column_count * trip_number + 6, '', right_format)
                if i == row_count-1:
                    cell_format = self.set_format({'right': 1, 'bottom': 1})
                    right_format = self.set_format({'right': 2, 'bottom': 1})

    # Шапка таблицы
    def write_header(self, shift_number: int):
        line = self.current_last_line(self.worksheet_schedule)
        # HeadLine
        current_day = self.first_date + datetime.timedelta(int((shift_number + 1) / 2) - 1)
        shift = 'ДЕНЬ' if shift_number % 2 == 1 else 'НОЧЬ'
        cell_format = self.set_format({'bold': 1, 'font_size': 11})
        shift_header = 'План работы бензовозов компании АО "Газпромнефть-Транспорт" на %02d.%02d.%d (%s)' % \
                       (current_day.day, current_day.month, current_day.year, shift)
        self.worksheet_schedule.merge_range(line, 0, line, self.last_column, shift_header, cell_format)
        # LeftAndCountInfo
        cell_format = self.set_format({'border': 2, 'bg_color': self.color_map['grey']})
        self.worksheet_schedule.merge_range(line + 1, 0, line + 3, 0, 'Гос.номер машины\nГос.номер прицепа', cell_format)
        self.worksheet_schedule.merge_range(line + 1, 1, line + 3, 1, '№ Секции', cell_format)
        self.worksheet_schedule.merge_range(line + 1, 2, line + 3, 2, 'Тарировка', cell_format)
        self.worksheet_schedule.merge_range(line + 1, 3, line + 3, 3, 'Очередность /\nвремя выезда из гаража', cell_format)
        self.worksheet_schedule.merge_range(line + 1, self.last_column, line + 3, self.last_column, 'Количество\nвыполненных\nрейсов', cell_format)
        self.worksheet_schedule.set_column(0, 0, 12)
        self.worksheet_schedule.set_column(1, 1, 5)
        self.worksheet_schedule.set_column(2, 2, 7)
        self.worksheet_schedule.set_column(3, 3, 15)
        self.worksheet_schedule.set_column(self.last_column, self.last_column, 10)
        # TableHeader
        for i in range(self.max_route_count):  # перечисление рейсов
            first_column = self.left_info_column_count + i * self.route_column_count
            cell_format = self.set_format({'border': 2, 'bg_color': self.color_map['grey'], 'bold': 1, 'bottom': 1})
            self.worksheet_schedule.merge_range(line + 1, first_column, line + 1, first_column + self.route_column_count - 1, 'Рейс ' + str(i + 1), cell_format)
            cell_format = self.set_format({'border': 2, 'bg_color': self.color_map['grey'], 'top': 1, 'right': 1})
            self.worksheet_schedule.merge_range(line + 2, first_column, line + 3, first_column, 'Место загрузки', cell_format)
            cell_format = self.set_format({'border': 1, 'bg_color': self.color_map['grey']})
            self.worksheet_schedule.merge_range(line + 2, first_column + 1, line + 2, first_column + 3, 'АЗС', cell_format)
            cell_format = self.set_format({'border': 1, 'bottom': 2, 'bg_color': self.color_map['grey']})
            self.worksheet_schedule.write(line + 3, first_column + 1, '№', cell_format)
            self.worksheet_schedule.write(line + 3, first_column + 2, 'Адрес', cell_format)
            self.worksheet_schedule.write(line + 3, first_column + 3, 'Рез. АЗС', cell_format)
            cell_format = self.set_format({'border': 1, 'bg_color': self.color_map['grey'], 'bottom': 2})
            self.worksheet_schedule.merge_range(line + 2, first_column + 4, line + 3, first_column + 4, 'Марка топлива', cell_format)
            self.worksheet_schedule.merge_range(line + 2, first_column + 5, line + 3, first_column + 5, 'Время доставки', cell_format)
            cell_format = self.set_format({'border': 2, 'bg_color': self.color_map['grey'], 'top': 1, 'left': 1})
            self.worksheet_schedule.merge_range(line + 2, first_column + 6, line + 3, first_column + 6, 'Примечание', cell_format)
            self.worksheet_schedule.set_column(first_column, first_column, 11)
            self.worksheet_schedule.set_column(first_column + 1, first_column + 1, 4)
            self.worksheet_schedule.set_column(first_column + 2, first_column + 2, 25)
            self.worksheet_schedule.set_column(first_column + 3, first_column + 3, 3)
            self.worksheet_schedule.set_column(first_column + 4, first_column + 4, 9)
            self.worksheet_schedule.set_column(first_column + 5, first_column + 5, 10)
            self.worksheet_schedule.set_column(first_column + 6, first_column + 6, 13)

    # Задание формата
    def set_format(self, param: dict):
        format_param = {'font_name': 'Arial', 'font_size': 9, 'valign': 'vcenter', 'align': 'center'}
        format_param.update(param)
        return self.workbook.add_format(format_param)

    # Текущая последняя строка
    def current_last_line(self, sheet):
        return 0 if sheet.dim_rowmax is None else sheet.dim_rowmax + 2
