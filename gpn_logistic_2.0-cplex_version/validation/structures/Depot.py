from validation.utils.time_windows_parser import parse_time_windows_to_time_scale


class Depot:
    def __init__(self, pandas_line):
        """Инициализация объекта Depot из строки объекта Pandas DataFrame
        :param pandas_line: Строка входного DataFrame
        """
        self.depot_id = pandas_line['depot_id']
        self.depot_name = pandas_line['depot_name']
        self.depot_time_window = pandas_line['depot_time_window']
        self.depot_traffic_capacity = pandas_line['depot_traffic_capacity']

        self.availability_timeline = parse_time_windows_to_time_scale(
            self.depot_time_window
        )

    def is_available_at_the_moment(self, time_moment):
        """Проверка доступности НБ в определенный момент времени
        :param time_moment: Номер минуты в рамках суток
        :return: True / False
        """
        if self.availability_timeline[time_moment] == 1:
            return True

        return False

