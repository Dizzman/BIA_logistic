class Response:
    def __init__(self):
        self.warnings = []

    def add_message(self, module, shift = None, time = None, depot_id = None, station_id = None, truck_id = None, reservoir_id = None, message = None):
        case = {'module': module}

        if shift:
            case['shift'] = shift
        if time:
            case['time'] = time
        if depot_id:
            case['depot_id'] = depot_id
        if station_id:
            case['station_id'] = station_id
        if truck_id:
            case['truck_id'] = truck_id
        if reservoir_id:
            case['reservoir_id'] = reservoir_id
        if message:
            case['message'] = message

        self.warnings.append(case)

    def print(self):
        with open("output/validation_log.txt", "w+") as output_file:
            for el in self.warnings:
                output_file.write("{}\n".format(el))