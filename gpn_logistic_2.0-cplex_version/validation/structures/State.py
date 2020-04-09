class State:
    def __init__(self, pandas_line):
        self.asu_id = pandas_line['asu_id']
        self.n = int(pandas_line['n'])
        self.shift = int(pandas_line['shift'])
        self.asu_state = pandas_line['asu_state']
        self.death_vol = pandas_line['death_vol']
        self.capacity = pandas_line['capacity']
        self.days_to_death = pandas_line['days_to_death']
        self.consumption = pandas_line['consumption']
        self.delivery = pandas_line['delivery']
