from data_reader.input_data import Parameters

# Ф-я  возвращает пользователю состояние расчёта в процентах (очень грубая осреднённая оценка)


class CalcPercent:
    def __init__(self):
        # Примерная продолжительность в сек (по результатам тестов на локальном компе)
        self._markers = [
            5,  # reading data
            5,  # integral model
            10,  # asu nb connection
            10,  # detailed model preparing (main shift)
            100,  # detailed model (main shift)
            100,  # timetable calculation (main shift)
            50,  # load after calculation (main shift)
            5,  # processing (main shift)
            10,  # detailed model preparing (next shift)
            100,  # detailed model (next shift)
            100,  # timetable calculation (next shift)
            50,  # timetable calculation (next shift)
            5,  # processing (next shift)
            5  # ending
        ]

        self._index = -1
        self._current_sum = 0
        self._total = lambda: sum(self._markers)

    def next(self):
        self._index += 1
        self._current_sum += self._markers[self._index]
        if self._index < len(self._markers):
            return self._current_sum / self._total() * 100
        else:
            return 100

    def set_integral_time_limit(self, time):
        self._markers[1] = time

    def set_asu_group_count(self, count):
        if count == 0:
            count = 1
        common_time = self._markers[self._index + 1]
        part_time = common_time / count
        self._markers.pop(self._index + 1)
        for index in range(self._index + 1, self._index + 1 + count):
            self._markers.insert(index, part_time)

    def display_percent(self):
        print("<PERCENT>\n%.1f %%\n</PERCENT>" % self.next())


percents = CalcPercent()
