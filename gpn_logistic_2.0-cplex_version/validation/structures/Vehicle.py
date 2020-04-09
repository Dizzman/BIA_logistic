class Vehicle:
    def __init__(self, pandas_line):
        self.id = pandas_line['idx']
        self.is_owner = int(pandas_line['is_owner'])
        self.capacity = int(pandas_line['capacity'])
        self.sections = pandas_line['sections'].split(";")
        self.drain_side_left = int(pandas_line['drain_side_left'])
        self.drain_side_right = int(pandas_line['drain_side_right'])
        self.is_bulky = int(pandas_line['is_bulky'])
        self.np_petrol = list(map(int, str(pandas_line['np_petrol']).split(";")))
        self.np_diesel = list(map(int, str(pandas_line['np_diesel']).split(";")))
        self.np_mix = list(map(int, str(pandas_line['np_mix']).split(";")))
        self.uet = pandas_line['uet']
