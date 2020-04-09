class Delivery:
    def __init__(self, pandas_line, volumes_add=False):
        if not volumes_add:
            self.shift = int(pandas_line['shift'])
            self.truck = int(pandas_line['truck'])
            self.section_number = int(pandas_line['section_number'])
            self.section_volume = int(pandas_line['section_volume'])
            self.is_empty = float(pandas_line['is_empty'])
            self.should_be_empty = int(pandas_line['should_be_empty'])
            self.asu = float(pandas_line['asu'])
            self.sku = None
            self.n = int(pandas_line['n'])
            self.depot = int(pandas_line['depot'])
            self.trip_number = int(pandas_line['trip_number'])
            self.time = pandas_line['time']
            self.load_before = int(pandas_line['load_before'])
            self.load_after = int(pandas_line['load_after'])
            self.is_additional = False
        else:
            self.shift = int(pandas_line['time'])
            self.asu = int(pandas_line['asu_id'])
            self.n = int(pandas_line['n'])
            self.sku = None
            self.section_volume = int(pandas_line['volume'])
            self.truck = None
            self.is_additional = True