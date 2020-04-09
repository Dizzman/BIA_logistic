class Reservoir:
    def __init__(self, pandas_line):
        """Инициализация объекта Reservoir из строки объекта Pandas DataFrame
        :param pandas_line: Строка входного DataFrame
        """
        self.asu_id = pandas_line['asu_id']
        self.n = pandas_line['n']
        self.sku = pandas_line['sku']
        self.capacity = pandas_line['capacity']
        self.capacity_min = pandas_line['capacity_min']
        self.states = []

    def add_state(self, state):
        self.states.append(state)
