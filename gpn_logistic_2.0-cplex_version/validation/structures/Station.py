from validation.utils.time_windows_parser import parse_time_windows_to_time_scale


class Station:
    def __init__(self, pandas_line):
        """Инициализация объекта Station из строки объекта Pandas DataFrame
        :param pandas_line: Строка входного DataFrame
        """
        self.asu_id = pandas_line["asu_id"]
        self.asu_time_windows = pandas_line["asu_time_windows"]
        self.depot_id = pandas_line["depot_id"]
        self.drain_side_left = pandas_line["drain_side_left"]
        self.drain_side_right = pandas_line["drain_side_right"]
        self.non_bulky = pandas_line["non_bulky"]
        self.is_automatic = pandas_line["is_automatic"]
        self.reservoirs = []

        self.availability_timeline = parse_time_windows_to_time_scale(
            self.asu_time_windows
        )

    def is_available_at_the_moment(self, time_moment):
        """Проверка доступности АЗС в определенный момент времени
        :param time_moment: Номер минуты в рамках суток
        :return: True / False
        """
        if self.availability_timeline[time_moment] == 1:
            return True

        return False

    def connect_reservoir(self, reservoir):
        self.reservoirs.append(reservoir)

